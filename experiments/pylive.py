"""Baseline: the live loop of rust/src/main.rs ported line by line to Python.

Same shared-memory protocol, same 33 ms schedule, same chunk, halt, blend,
limiter and toy-sim logic, same tick log. Used to ask what Rust adds beyond
running the fixed-rate loop in a separate process.
usage: pylive.py --layout L --duration S --log F --shm P
"""
import json
import math
import mmap
import os
import struct
import sys
import time

args = sys.argv[1:]


def get(k, d):
    return args[args.index(k) + 1] if k in args else d


L = json.load(open(get("--layout", "layout.json")))
SHM = get("--shm", "/dev/shm/rtvla.shm")
TICK = float(get("--tick-ms", "33")) / 1000
DUR = float(get("--duration", "60"))
LOG = get("--log", "ticks.csv")
C = {k: v["offset"] for k, v in L["command"].items()}
S = {k: v["offset"] for k, v in L["state"].items()}
MAXS, ACT = L["max_steps"], L["act"]

fd = os.open(SHM, os.O_RDWR)
mm = mmap.mmap(fd, L["total"])
os.close(fd)
Q, q, d = struct.Struct("<Q"), struct.Struct("<q"), struct.Struct("<d")


def ru(o): return Q.unpack_from(mm, o)[0]
def ri(o): return q.unpack_from(mm, o)[0]
def rf(o): return d.unpack_from(mm, o)[0]
def wu(o, v): Q.pack_into(mm, o, v)
def wi(o, v): q.pack_into(mm, o, v)
def wf(o, v): d.pack_into(mm, o, v)


VMAX, AMAX = 0.25, 3.0
WS_MIN, WS_MAX = [-0.35, -0.35, 0.0], [0.35, 0.35, 0.40]
BLEND_TOL, BLEND_K = 0.003, 5
GRASP_R, PLACE_R, CUBE_Z = 0.015, 0.02, 0.02
BOWL = [0.20, -0.10, 0.02]
HB_STALE, HB_GRACE, AHEAD = 6, 10, 50


def norm(v): return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


boot_id = time.time_ns() | 1
pos, vel, grip = [0.0, 0.0, 0.15], [0.0, 0.0, 0.0], 0.0
current = pending = None
last_seen = ru(C["chunk_id"])
last_hb = hb_stale = hb_grace = 0
blend_off, blend_j = [0.0] * 3, BLEND_K
owner_none = halted_hold = False
session = halt_floor = halt_ack = 0
halt_ack_tick = -1
rej_bad = rej_halted = 0
last_reset = ru(C["reset_seq"])
cube, attached, prev_closed, succ, rel = [0.10, 0.05, CUBE_Z], False, False, 0, 0
last_good = None
log = ["tick,sched_us,write_us,late_us,chunk,step,reason,x,y,z,grip,token,node,blend,mismatch,cube_x,cube_y,cube_z,attached,successes,hb_stale,seen,halt_ack,halt_floor,rej_bad,rej_halted"]
t0 = time.monotonic()
n_ticks = int(DUR / TICK)
for tick in range(n_ticks):
    sched = t0 + TICK * tick
    now = time.monotonic()
    if sched > now:
        time.sleep(sched - now)
    hdr = nc = None
    for _ in range(3):
        s1 = ru(C["seq"])
        if s1 % 2:
            continue
        h = {k: ru(C[k]) for k in ("boot_id", "heartbeat", "chunk_id", "reset_seq", "quit", "py_session", "halt_seq", "halt_token")}
        h["reset_cube"] = [rf(C["reset_cube"] + 8 * i) for i in range(3)]
        c = None
        if h["chunk_id"] > last_seen:
            steps = min(ru(C["steps_used"]), MAXS)
            raw = struct.unpack_from("<%dd" % (steps * ACT), mm, C["actions"])
            c = ({"id": h["chunk_id"], "built_on": ru(C["built_on"]), "start": ri(C["start_tick"]),
                  "owner": ru(C["owner"]), "token": ru(C["token"]), "node": ru(C["node_id"]),
                  "actions": [raw[i * ACT:(i + 1) * ACT] for i in range(steps)]}, steps)
        if ru(C["seq"]) == s1:
            hdr, nc = h, c
            break
    if hdr:
        last_good = hdr
    h = last_good or {"boot_id": 0, "heartbeat": 0, "chunk_id": 0, "reset_seq": 0, "quit": 0, "py_session": 0,
                      "halt_seq": 0, "halt_token": 0, "reset_cube": [0, 0, 0]}
    if h["quit"]:
        break
    if h["heartbeat"] != last_hb:
        last_hb, hb_stale, hb_grace = h["heartbeat"], 0, 0
    else:
        hb_stale += 1
    if h["reset_seq"] != last_reset:
        last_reset, cube, attached = h["reset_seq"], list(h["reset_cube"]), False
    if h["py_session"] != session:
        session, halt_floor, halt_ack = h["py_session"], 0, 0
        if session:
            current = pending = None
    halted_now = False
    if h["halt_seq"] != halt_ack:
        halt_floor, halt_ack, halt_ack_tick = max(halt_floor, h["halt_token"]), h["halt_seq"], tick
    if nc:
        ch, steps = nc
        last_seen = ch["id"]
        finite = all(math.isfinite(v) for a in ch["actions"] for v in a)
        if h["boot_id"] != boot_id:
            pass
        elif steps > 0 and ch["token"] and ch["token"] <= halt_floor:
            rej_halted += 1
        elif not finite:
            rej_bad += 1
        elif steps == 0:
            current = pending = None
            owner_none = True
        elif ch["start"] > tick + AHEAD or ch["start"] + steps <= tick:
            pass
        else:
            pending = ch
    if halt_floor:
        if pending and pending["token"] and pending["token"] <= halt_floor:
            pending, halted_now = None, True
        if current and current["token"] and current["token"] <= halt_floor:
            current, halted_now = None, True
    if halted_now:
        halted_hold = True
    mismatch = 0
    switched = False
    if pending and pending["start"] <= tick:
        if pending["built_on"] != (current["id"] if current else 0):
            mismatch = 1
        current, pending, owner_none, halted_hold, switched = pending, None, False, False, True
    hb_hold = hb_stale >= HB_STALE and hb_grace >= HB_GRACE
    target, step_idx = None, -1
    if current:
        idx = tick - current["start"]
        if 0 <= idx < len(current["actions"]) and not hb_hold:
            target, step_idx = list(current["actions"][idx]), idx
            if hb_stale >= HB_STALE:
                hb_grace += 1
    reason = 1 if target else 4 if (hb_hold and current) else 6 if halted_hold else 3 if owner_none else 2 if current else 0
    if target:
        if switched:
            gap = [pos[i] - target[i] for i in range(3)]
            if norm(gap) > BLEND_TOL:
                blend_off, blend_j = gap, 0
            else:
                blend_j = BLEND_K
        if blend_j < BLEND_K:
            blend_j += 1
            w = 1.0 - blend_j / BLEND_K
            for i in range(3):
                target[i] += blend_off[i] * w
            reason = 5
    if target:
        e = [target[i] - pos[i] for i in range(3)]
        dd = norm(e)
        cap = min(VMAX, math.sqrt(2 * AMAX * dd), dd / TICK)
        vdes = [e[i] / dd * cap for i in range(3)] if dd > 1e-9 else [0.0] * 3
    else:
        vdes = [0.0] * 3
    dv = [vdes[i] - vel[i] for i in range(3)]
    n = norm(dv)
    if n > AMAX * TICK:
        dv = [x * AMAX * TICK / n for x in dv]
    for i in range(3):
        vel[i] += dv[i]
        pos[i] = min(max(pos[i] + vel[i] * TICK, WS_MIN[i]), WS_MAX[i])
    if target:
        grip = min(max(target[6], 0.0), 1.0)
    closed = grip >= 0.5
    if closed and not prev_closed and not attached and norm([pos[i] - cube[i] for i in range(3)]) < GRASP_R:
        attached = True
    if attached and not closed:
        attached, rel = False, rel + 1
        cube = [pos[0], pos[1], CUBE_Z]
        if math.hypot(cube[0] - BOWL[0], cube[1] - BOWL[1]) < PLACE_R:
            succ += 1
    if attached:
        cube = list(pos)
    prev_closed = closed
    write_t = time.monotonic()
    seq = ru(S["seq"])
    wu(S["seq"], seq + 1)
    wu(S["boot_id"], boot_id)
    wi(S["tick"], tick)
    lc = [pos[0], pos[1], pos[2], 0.0, 0.0, 0.0, grip]
    struct.pack_into("<7d", mm, S["pose"], *lc)
    struct.pack_into("<7d", mm, S["last_cmd"], *lc)
    wu(S["last_chunk_seen"], last_seen)
    wu(S["chunk_playing"], current["id"] if current else 0)
    wu(S["chunk_queued"], pending["id"] if pending else 0)
    wi(S["step_playing"], step_idx)
    wu(S["reason"], reason)
    struct.pack_into("<3d", mm, S["cube"], *cube)
    struct.pack_into("<3d", mm, S["bowl"], *BOWL)
    wu(S["cube_attached"], int(attached))
    wu(S["successes"], succ)
    wu(S["releases"], rel)
    wu(S["heartbeat_seen"], last_hb)
    wu(S["halt_floor"], halt_floor)
    wu(S["halt_ack"], halt_ack)
    wi(S["halt_ack_tick"], halt_ack_tick)
    wu(S["rejected_bad"], rej_bad)
    wu(S["rejected_halted"], rej_halted)
    wu(S["session_seen"], session)
    wu(S["seq"], seq + 2)
    su, wus = int((sched - t0) * 1e6), int((write_t - t0) * 1e6)
    cid, tok, nid = (current["id"], current["token"], current["node"]) if current else (0, 0, 0)
    log.append(f"{tick},{su},{wus},{wus - su},{cid},{step_idx},{reason},{pos[0]:.7f},{pos[1]:.7f},{pos[2]:.7f},{grip:.2f},"
               f"{tok},{nid},{int(reason == 5)},{mismatch},{cube[0]:.5f},{cube[1]:.5f},{cube[2]:.5f},{int(attached)},{succ},"
               f"{hb_stale},{last_seen},{halt_ack},{halt_floor},{rej_bad},{rej_halted}")
with open(LOG, "w") as f:
    f.write("\n".join(log) + "\n")
print(f"pylive: wrote {len(log) - 1} ticks to {LOG}", file=sys.stderr)
