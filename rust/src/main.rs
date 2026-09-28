//! Rust live loop (Step 1) with a kinematic toy sim as its driver.
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

// limiter / sim constants (toy values; units m, s)
const VMAX: f64 = 0.25; // m/s
const AMAX: f64 = 3.0; // m/s^2
const WS_MIN: [f64; 3] = [-0.35, -0.35, 0.0];
const WS_MAX: [f64; 3] = [0.35, 0.35, 0.40];
const BLEND_TOL: f64 = 0.003; // m
const BLEND_K: usize = 5; // ticks
const GRASP_RADIUS: f64 = 0.015;
const PLACE_RADIUS: f64 = 0.02;
const CUBE_Z: f64 = 0.02;
const BOWL: [f64; 3] = [0.20, -0.10, 0.02];
const HB_STALE_TICKS: u64 = 6;
const HB_GRACE_STEPS: u64 = 10;
const START_AHEAD_MAX: i64 = 50;

fn norm(v: [f64; 3]) -> f64 {
    (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt()
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

    // ------------------------------------------------------------- state
    let mut pos = [0.0, 0.0, 0.15];
    let mut vel = [0.0f64; 3];
    let mut grip = 0.0f64; // 0 open, 1 closed
    let mut last_cmd = [0.0f64; 7];
    let mut current: Option<Chunk> = None;
    let mut pending: Option<Chunk> = None;
    let mut last_seen: u64 = shm.ru(c("chunk_id")); // ignore anything left from before boot
    let mut last_hb = 0u64;
    let mut hb_stale = 0u64;
    let mut hb_grace_used = 0u64;
    let mut blend_off = [0.0f64; 3];
    let mut blend_j = BLEND_K;
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
    let mut cube = [0.10, 0.05, CUBE_Z];
    let mut attached = false;
    let mut prev_closed = false;
    let mut successes = 0u64;
    let mut releases = 0u64;
    let mut last_good: Option<CmdHeader> = None;

    let mut log: Vec<String> = Vec::with_capacity(200_000);
    log.push("tick,sched_us,write_us,late_us,chunk,step,reason,x,y,z,grip,token,node,blend,mismatch,cube_x,cube_y,cube_z,attached,successes,hb_stale,seen,halt_ack,halt_floor,rej_bad,rej_halted".into());

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
            last_reset = h.reset_seq;
            cube = h.reset_cube;
            attached = false;
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
        if let Some(pch) = &pending {
            if pch.start <= tick {
                let playing_id = current.as_ref().map(|x| x.id).unwrap_or(0);
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
        let mut reason;
        let mut target: Option<[f64; 7]> = None;
        let mut step_idx: i64 = -1;
        if let Some(cur) = &current {
            let idx = tick - cur.start;
            if idx >= 0 && (idx as usize) < cur.actions.len() && !heartbeat_hold {
                target = Some(cur.actions[idx as usize]);
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

        // ---- switch blend (position only; gripper never blended)
        if let Some(t) = target {
            if switched {
                let gap = [pos[0] - t[0], pos[1] - t[1], pos[2] - t[2]];
                if norm(gap) > BLEND_TOL {
                    blend_off = gap;
                    blend_j = 0;
                } else {
                    blend_j = BLEND_K;
                }
            }
            if blend_j < BLEND_K {
                blend_j += 1;
                let w = 1.0 - blend_j as f64 / BLEND_K as f64;
                let mut tt = t;
                for i in 0..3 {
                    tt[i] = t[i] + blend_off[i] * w;
                }
                target = Some(tt);
                reason = REASON_BLEND;
            }
        }

        // ---- safety limiter: speed and acceleration caps, workspace clip
        let v_des = match target {
            Some(t) => {
                // speed cap, and never faster than we can brake before the target
                let e = [t[0] - pos[0], t[1] - pos[1], t[2] - pos[2]];
                let d = norm(e);
                let cap = VMAX.min((2.0 * AMAX * d).sqrt()).min(d / dt);
                if d > 1e-9 {
                    [e[0] / d * cap, e[1] / d * cap, e[2] / d * cap]
                } else {
                    [0.0; 3]
                }
            }
            None => [0.0; 3], // hold: decelerate to a stop at the accel cap
        };
        let mut dv = [v_des[0] - vel[0], v_des[1] - vel[1], v_des[2] - vel[2]];
        let n = norm(dv);
        if n > AMAX * dt {
            for i in 0..3 {
                dv[i] *= AMAX * dt / n;
            }
        }
        for i in 0..3 {
            vel[i] += dv[i];
            pos[i] = (pos[i] + vel[i] * dt).clamp(WS_MIN[i], WS_MAX[i]);
        }
        if let Some(t) = target {
            grip = t[6].clamp(0.0, 1.0);
        }
        last_cmd = [pos[0], pos[1], pos[2], 0.0, 0.0, 0.0, grip];

        // ---- toy sim (the "driver")
        let closed = grip >= 0.5;
        if closed && !prev_closed && !attached {
            let d = norm([pos[0] - cube[0], pos[1] - cube[1], pos[2] - cube[2]]);
            if d < GRASP_RADIUS {
                attached = true;
            }
        }
        if attached && !closed {
            attached = false;
            releases += 1;
            cube = [pos[0], pos[1], CUBE_Z];
            if norm([cube[0] - BOWL[0], cube[1] - BOWL[1], 0.0]) < PLACE_RADIUS {
                successes += 1;
            }
        }
        if attached {
            cube = pos;
        }
        prev_closed = closed;
        let write_t = Instant::now(); // the moment the command reaches the driver

        // ---- write state slot (seqlock)
        let seq = shm.ru(s("seq"));
        shm.wu(s("seq"), seq + 1);
        fence(Ordering::Release);
        shm.wu(s("boot_id"), boot_id);
        shm.wi(s("tick"), tick);
        for i in 0..7 {
            shm.wf(s("pose") + 8 * i, last_cmd[i]);
            shm.wf(s("last_cmd") + 8 * i, last_cmd[i]);
        }
        shm.wu(s("last_chunk_seen"), last_seen);
        shm.wu(s("chunk_playing"), current.as_ref().map(|x| x.id).unwrap_or(0));
        shm.wu(s("chunk_queued"), pending.as_ref().map(|x| x.id).unwrap_or(0));
        shm.wi(s("step_playing"), step_idx);
        shm.wu(s("reason"), reason);
        for i in 0..3 {
            shm.wf(s("cube") + 8 * i, cube[i]);
            shm.wf(s("bowl") + 8 * i, BOWL[i]);
        }
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
        log.push(format!(
            "{},{},{},{},{},{},{},{:.7},{:.7},{:.7},{:.2},{},{},{},{},{:.5},{:.5},{:.5},{},{},{},{},{},{},{},{}",
            tick, sched_us, write_us, write_us - sched_us, cid, step_idx, reason,
            pos[0], pos[1], pos[2], grip, tok, nid,
            (reason == REASON_BLEND) as u8, mismatch, cube[0], cube[1], cube[2],
            attached as u8, successes, hb_stale, last_seen, halt_ack, halt_floor,
            rejected_bad, rejected_halted
        ));
    }

    let mut f = std::fs::File::create(&log_path).unwrap();
    f.write_all(log.join("\n").as_bytes()).unwrap();
    f.write_all(b"\n").unwrap();
    eprintln!("live: wrote {} ticks to {}", log.len() - 1, log_path);
}

fn cur_owner(c: &Option<Chunk>) -> u64 {
    c.as_ref().map(|x| x.owner).unwrap_or(0)
}
