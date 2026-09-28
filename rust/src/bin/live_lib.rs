//! Rust live loop, LIBERO mode: actions are LIBERO's 7-D commands
//! (end-effector position and rotation deltas in [-1, 1], gripper -1 open / +1 close).
//! The driver is a separate LIBERO plant process that steps the simulator once
//! per tick with the command written here. Holding = zero motion delta,
//! gripper kept at its last command.
//!
//! Every tick (33 ms): read the command slot (seqlock), accept a new chunk,
//! pick the step for this tick, blend at a switch, run the safety limiter,
//! step the sim, write the state slot, and append one row to the tick log.
//! Nothing here ever waits on Python.

use memmap2::MmapMut;
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::sync::atomic::{fence, Ordering};
use std::time::{Duration, Instant};

// ----------------------------------------------------------------- layout
struct Layout {
    cmd: HashMap<String, usize>,
    st: HashMap<String, usize>,
    pl: HashMap<String, usize>,
    max_steps: usize,
    act: usize,
}

fn load_layout(path: &str) -> Layout {
    let v: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(path).expect("layout.json")).unwrap();
    let grab = |slot: &str| -> HashMap<String, usize> {
        v[slot]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, f)| (k.clone(), f["offset"].as_u64().unwrap() as usize))
            .collect()
    };
    Layout {
        cmd: grab("command"),
        st: grab("state"),
        pl: grab("plant"),
        max_steps: v["max_steps"].as_u64().unwrap() as usize,
        act: v["act"].as_u64().unwrap() as usize,
    }
}

// ----------------------------------------------------------------- shm
struct Shm {
    _m: MmapMut,
    p: *mut u8,
}
impl Shm {
    fn ru(&self, o: usize) -> u64 {
        unsafe { (self.p.add(o) as *const u64).read_volatile() }
    }
    fn ri(&self, o: usize) -> i64 {
        unsafe { (self.p.add(o) as *const i64).read_volatile() }
    }
    fn rf(&self, o: usize) -> f64 {
        unsafe { (self.p.add(o) as *const f64).read_volatile() }
    }
    fn wu(&self, o: usize, v: u64) {
        unsafe { (self.p.add(o) as *mut u64).write_volatile(v) }
    }
    fn wi(&self, o: usize, v: i64) {
        unsafe { (self.p.add(o) as *mut i64).write_volatile(v) }
    }
    fn wf(&self, o: usize, v: f64) {
        unsafe { (self.p.add(o) as *mut f64).write_volatile(v) }
    }
}

// ----------------------------------------------------------------- data
#[derive(Clone)]
struct Chunk {
    id: u64,
    built_on: u64,
    start: i64,
    owner: u64,
    token: u64,
    node_id: u64,
    actions: Vec<[f64; 7]>,
}

#[derive(Clone, Copy)]
struct CmdHeader {
    boot_id: u64,
    heartbeat: u64,
    chunk_id: u64,
    reset_seq: u64,
    reset_cube: [f64; 3],
    quit: u64,
    py_session: u64,
    halt_seq: u64,
    halt_token: u64,
}

const REASON_IDLE: u64 = 0;
const REASON_PLAY: u64 = 1;
const REASON_HOLD_EMPTY: u64 = 2;
const REASON_HOLD_OWNER_NONE: u64 = 3;
const REASON_HOLD_HEARTBEAT: u64 = 4;
const REASON_BLEND: u64 = 5;
const REASON_HOLD_HALTED: u64 = 6;

// limiter constants (joint space, rad and s); index 5 is the gripper
const NJ: usize = 7;
const DMAX: f64 = 1.0; // LIBERO's normalised command range
const HB_STALE_TICKS: u64 = 6;
const HB_GRACE_STEPS: u64 = 10;
const START_AHEAD_MAX: i64 = 50;

fn norm5(v: &[f64]) -> f64 {
    v.iter().take(5).map(|x| x * x).sum::<f64>().sqrt()
}

fn main() {
    // ------------------------------------------------------------- args
    let args: Vec<String> = std::env::args().collect();
    let get = |k: &str, d: &str| -> String {
        args.iter()
            .position(|a| a == k)
            .map(|i| args[i + 1].clone())
            .unwrap_or(d.to_string())
    };
    let layout_path = get("--layout", "../layout.json");
    let shm_path = get("--shm", "/dev/shm/rtvla.shm");
    let tick_ms: f64 = get("--tick-ms", "33").parse().unwrap();
    let duration_s: f64 = get("--duration", "60").parse().unwrap();
    let log_path = get("--log", "ticks.csv");

    let lay = load_layout(&layout_path);
    let file = OpenOptions::new().read(true).write(true).open(&shm_path).expect("shm file");
    let mut m = unsafe { MmapMut::map_mut(&file).unwrap() };
    let p = m.as_mut_ptr();
    let shm = Shm { _m: m, p };
    let c = |k: &str| lay.cmd[k];
    let s = |k: &str| lay.st[k];

    let boot_id: u64 = (std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos() as u64)
        | 1;
    let dt = tick_ms / 1000.0;
    let period = Duration::from_micros((tick_ms * 1000.0) as u64);

    let pl = |k: &str| lay.pl[k];
    // read the plant slot (seqlock written by the plant); None if torn 3x
    let read_plant = |shm: &Shm| -> Option<([f64; NJ], u64, f64)> {
        for _ in 0..3 {
            let s1 = shm.ru(pl("p_seq"));
            if s1 % 2 == 1 || s1 == 0 {
                continue;
            }
            fence(Ordering::Acquire);
            let mut q = [0.0; NJ];
            for i in 0..NJ {
                q[i] = shm.rf(pl("p_lstate") + 8 * i);
            }
            let (st, rtf) = (shm.ru(pl("p_step")), shm.rf(pl("p_rtf")));
            fence(Ordering::Acquire);
            if shm.ru(pl("p_seq")) == s1 {
                return Some((q, st, rtf));
            }
        }
        None
    };
    // wait (at most 10 s) for the plant, start commanding from where it is
    let wait0 = Instant::now();
    let mut plant = read_plant(&shm);
    while plant.is_none() && wait0.elapsed() < Duration::from_secs(10) {
        std::thread::sleep(Duration::from_millis(2));
        plant = read_plant(&shm);
    }
    let mut plant = plant.expect("plant never published state");

    // ------------------------------------------------------------- state
    let mut pos: [f64; NJ] = [0.0; NJ]; // command handed to the plant this tick
    let mut grip_last: f64 = -1.0; // gripper command kept while holding (open)
    let mut last_cmd = [0.0f64; 7];
    let mut current: Option<Chunk> = None;
    let mut pending: Option<Chunk> = None;
    let mut last_seen: u64 = shm.ru(c("chunk_id")); // ignore anything left from before boot
    let mut last_hb = 0u64;
    let mut hb_stale = 0u64;
    let mut hb_grace_used = 0u64;
    let mut owner_none = false;
    let mut halted_hold = false;
    // halt state is owned here: Python only asks, Rust decides and confirms
    let mut session = 0u64;
    let mut halt_floor = 0u64;
    let mut halt_ack = 0u64;
    let mut halt_ack_tick: i64 = -1;
    let mut rejected_bad = 0u64;
    let mut rejected_halted = 0u64;
    let mut last_reset = shm.ru(c("reset_seq"));
    let successes = 0u64;
    let releases = 0u64;
    let attached = false;
    let mut plant_torn = 0u64;
    let mut last_good: Option<CmdHeader> = None;

    let mut log: Vec<String> = Vec::with_capacity(200_000);
    log.push("mono_us,tick,sched_us,write_us,late_us,chunk,step,reason,c0,c1,c2,c3,c4,c5,c6,m0,m1,m2,m3,m4,m5,m6,token,node,mismatch,pstep,rtf,hb_stale,seen,halt_ack,halt_floor,rej_bad,rej_halted,plant_torn".into());

    let t0 = Instant::now();
    let n_ticks = (duration_s / dt) as i64;

    for tick in 0..n_ticks {
        // ---- wait for this tick's scheduled time (never for Python)
        let sched = t0 + period * (tick as u32);
        let now = Instant::now();
        if sched > now {
            std::thread::sleep(sched - now);
        }

        // ---- read command slot header (seqlock, at most 3 tries)
        let mut hdr: Option<CmdHeader> = None;
        let mut new_chunk: Option<(Chunk, u64)> = None; // (chunk, steps_used)
        for _ in 0..3 {
            let s1 = shm.ru(c("seq"));
            if s1 % 2 == 1 {
                continue;
            }
            fence(Ordering::Acquire);
            let h = CmdHeader {
                boot_id: shm.ru(c("boot_id")),
                heartbeat: shm.ru(c("heartbeat")),
                chunk_id: shm.ru(c("chunk_id")),
                reset_seq: shm.ru(c("reset_seq")),
                reset_cube: [
                    shm.rf(c("reset_cube")),
                    shm.rf(c("reset_cube") + 8),
                    shm.rf(c("reset_cube") + 16),
                ],
                quit: shm.ru(c("quit")),
                py_session: shm.ru(c("py_session")),
                halt_seq: shm.ru(c("halt_seq")),
                halt_token: shm.ru(c("halt_token")),
            };
            let mut nc = None;
            if h.chunk_id > last_seen {
                let steps = shm.ru(c("steps_used")).min(lay.max_steps as u64);
                let mut acts = Vec::with_capacity(steps as usize);
                for i in 0..steps as usize {
                    let mut a = [0.0; 7];
                    for j in 0..7 {
                        a[j] = shm.rf(c("actions") + 8 * (i * lay.act + j));
                    }
                    acts.push(a);
                }
                nc = Some((
                    Chunk {
                        id: h.chunk_id,
                        built_on: shm.ru(c("built_on")),
                        start: shm.ri(c("start_tick")),
                        owner: shm.ru(c("owner")),
                        token: shm.ru(c("token")),
                        node_id: shm.ru(c("node_id")),
                        actions: acts,
                    },
                    steps,
                ));
            }
            fence(Ordering::Acquire);
            if shm.ru(c("seq")) == s1 {
                hdr = Some(h);
                new_chunk = nc;
                break;
            }
        }
        if let Some(hh) = hdr {
            last_good = Some(hh);
        }
        let h = last_good.unwrap_or(CmdHeader { boot_id: 0, heartbeat: 0, chunk_id: 0, reset_seq: 0, reset_cube: [0.0; 3], quit: 0, py_session: 0, halt_seq: 0, halt_token: 0 });
        if h.quit != 0 {
            break;
        }

        // ---- heartbeat (counted in ticks)
        if h.heartbeat != last_hb {
            last_hb = h.heartbeat;
            hb_stale = 0;
            hb_grace_used = 0;
        } else {
            hb_stale += 1;
        }

        // ---- sim reset request
        if h.reset_seq != last_reset {
            last_reset = h.reset_seq; // resets are done by the plant process
        }

        // ---- a new Python process: forget old halts and drop old motion
        if h.py_session != session {
            session = h.py_session;
            halt_floor = 0;
            halt_ack = 0;
            if session != 0 {
                current = None;
                pending = None;
            }
        }

        // ---- halt requests: raise the floor, confirm in the state slot
        let mut halted_now = false;
        if h.halt_seq != halt_ack {
            halt_floor = halt_floor.max(h.halt_token);
            halt_ack = h.halt_seq;
            halt_ack_tick = tick;
        }

        // ---- accept a new chunk
        if let Some((ch, steps)) = new_chunk {
            last_seen = ch.id;
            let finite = ch.actions.iter().all(|a| a.iter().all(|v| v.is_finite()));
            if h.boot_id != boot_id {
                // written for another Rust boot: ignore
            } else if steps > 0 && ch.token != 0 && ch.token <= halt_floor {
                rejected_halted += 1;
            } else if !finite {
                rejected_bad += 1;
            } else {
                if steps == 0 {
                    // owner none: hold at once, drop everything
                    current = None;
                    pending = None;
                    owner_none = true;
                } else if ch.start > tick + START_AHEAD_MAX {
                    // start tick too far ahead: reject
                } else if ch.start + steps as i64 <= tick {
                    // every step already late: ignore
                } else {
                    pending = Some(ch); // replaces any older queued chunk
                }
            }
        }

        // ---- a halted token's chunks never play, queued or already playing
        if halt_floor > 0 {
            if pending.as_ref().map_or(false, |p| p.token != 0 && p.token <= halt_floor) {
                pending = None;
                halted_now = true;
            }
            if current.as_ref().map_or(false, |p| p.token != 0 && p.token <= halt_floor) {
                current = None;
                halted_now = true;
            }
        }
        if halted_now {
            halted_hold = true;
        }

        // ---- switch to the pending chunk when its start tick arrives
        let mut mismatch = 0u8;
        let mut switched = false;
        let mut old_step: Option<[f64; 7]> = None;
        if let Some(pch) = &pending {
            if pch.start <= tick {
                let playing_id = current.as_ref().map(|x| x.id).unwrap_or(0);
                // what the outgoing chunk would have commanded at this tick
                old_step = current.as_ref().and_then(|c| {
                    let k = tick - c.start;
                    if k >= 0 && (k as usize) < c.actions.len() { Some(c.actions[k as usize]) } else { None }
                });
                if pch.built_on != playing_id {
                    mismatch = 1;
                }
                current = pending.take();
                owner_none = false;
                halted_hold = false;
                switched = true;
            }
        }

        // ---- choose this tick's target
        let heartbeat_hold = hb_stale >= HB_STALE_TICKS && hb_grace_used >= HB_GRACE_STEPS;
        let reason;
        let mut target: Option<[f64; 7]> = None;
        let mut final_t: Option<[f64; 7]> = None; // last step of the playing chunk
        let mut step_idx: i64 = -1;
        if let Some(cur) = &current {
            let idx = tick - cur.start;
            if idx >= 0 && (idx as usize) < cur.actions.len() && !heartbeat_hold {
                target = Some(cur.actions[idx as usize]);
                final_t = cur.actions.last().copied();
                step_idx = idx;
                if hb_stale >= HB_STALE_TICKS {
                    hb_grace_used += 1;
                }
            }
        }
        reason = if target.is_some() {
            REASON_PLAY
        } else if heartbeat_hold && current.is_some() {
            REASON_HOLD_HEARTBEAT
        } else if halted_hold {
            REASON_HOLD_HALTED
        } else if owner_none {
            REASON_HOLD_OWNER_NONE
        } else if current.is_some() {
            REASON_HOLD_EMPTY
        } else {
            REASON_IDLE
        };

        let _ = (switched, old_step);
        // ---- command: clamp every component to LIBERO's range; hold = no
        //      motion, gripper kept at its last command
        match target {
            Some(t) => {
                for i in 0..NJ {
                    pos[i] = t[i].clamp(-DMAX, DMAX);
                }
                grip_last = pos[6];
            }
            None => {
                for i in 0..6 {
                    pos[i] = 0.0;
                }
                pos[6] = grip_last;
            }
        }
        let _ = final_t;
        for i in 0..NJ {
            last_cmd[i] = pos[i];
        }

        // ---- hand the limited target to the plant (seqlock, Rust is the writer)
        let rs = shm.ru(pl("r_seq"));
        shm.wu(pl("r_seq"), rs + 1);
        fence(Ordering::Release);
        shm.wi(pl("r_tick"), tick);
        for i in 0..NJ {
            shm.wf(pl("r_act") + 8 * i, pos[i]);
        }
        let slot = (tick.rem_euclid(16)) as usize;
        for i in 0..NJ {
            shm.wf(pl("r_ring") + 8 * (slot * NJ + i), pos[i]);
        }
        fence(Ordering::Release);
        shm.wu(pl("r_seq"), rs + 2);
        match read_plant(&shm) {
            Some(p) => plant = p,
            None => plant_torn += 1,
        }
        let write_t = Instant::now(); // the moment the command reaches the driver

        // ---- write state slot (seqlock)
        let seq = shm.ru(s("seq"));
        shm.wu(s("seq"), seq + 1);
        fence(Ordering::Release);
        shm.wu(s("boot_id"), boot_id);
        shm.wi(s("tick"), tick);
        for i in 0..7 {
            shm.wf(s("pose") + 8 * i, plant.0[i]);
            shm.wf(s("last_cmd") + 8 * i, last_cmd[i]);
        }
        shm.wu(s("last_chunk_seen"), last_seen);
        shm.wu(s("chunk_playing"), current.as_ref().map(|x| x.id).unwrap_or(0));
        shm.wu(s("chunk_queued"), pending.as_ref().map(|x| x.id).unwrap_or(0));
        shm.wi(s("step_playing"), step_idx);
        shm.wu(s("reason"), reason);
        shm.wu(s("cube_attached"), attached as u64);
        shm.wu(s("successes"), successes);
        shm.wu(s("releases"), releases);
        shm.wu(s("heartbeat_seen"), last_hb);
        shm.wu(s("halt_floor"), halt_floor);
        shm.wu(s("halt_ack"), halt_ack);
        shm.wi(s("halt_ack_tick"), halt_ack_tick);
        shm.wu(s("rejected_bad"), rejected_bad);
        shm.wu(s("rejected_halted"), rejected_halted);
        shm.wu(s("session_seen"), session);
        fence(Ordering::Release);
        shm.wu(s("seq"), seq + 2);

        // ---- tick log
        let sched_us = (sched - t0).as_micros() as i64;
        let write_us = (write_t - t0).as_micros() as i64;
        let (cid, tok, nid) = match &current {
            Some(x) => (x.id, x.token, x.node_id),
            None => (0, 0, 0),
        };
        let _ = cur_owner(&current);
        let mono_us = {
            let mut ts = libc::timespec { tv_sec: 0, tv_nsec: 0 };
            unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut ts) };
            ts.tv_sec as i64 * 1_000_000 + ts.tv_nsec as i64 / 1000
        };
        log.push(format!(
            "{},{},{},{},{},{},{},{},{:.4},{:.4},{:.4},{:.4},{:.4},{:.4},{:.4},{:.5},{:.5},{:.5},{:.5},{:.5},{:.5},{:.5},{},{},{},{},{:.3},{},{},{},{},{},{},{}",
            mono_us, tick, sched_us, write_us, write_us - sched_us, cid, step_idx, reason,
            pos[0], pos[1], pos[2], pos[3], pos[4], pos[5], pos[6],
            plant.0[0], plant.0[1], plant.0[2], plant.0[3], plant.0[4], plant.0[5], plant.0[6],
            tok, nid, mismatch, plant.1, plant.2,
            hb_stale, last_seen, halt_ack, halt_floor, rejected_bad, rejected_halted, plant_torn
        ));
    }

    // tell the plant to stop
    let rs = shm.ru(pl("r_seq"));
    shm.wu(pl("r_seq"), rs + 1);
    shm.wu(pl("r_quit"), 1);
    shm.wu(pl("r_seq"), rs + 2);
    let mut f = std::fs::File::create(&log_path).unwrap();
    f.write_all(log.join("\n").as_bytes()).unwrap();
    f.write_all(b"\n").unwrap();
    eprintln!("live: wrote {} ticks to {}", log.len() - 1, log_path);
}

fn cur_owner(c: &Option<Chunk>) -> u64 {
    c.as_ref().map(|x| x.owner).unwrap_or(0)
}
