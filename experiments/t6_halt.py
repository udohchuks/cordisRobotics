"""E6 (v2): halting chunks that are already in Rust. Rust owns the halt state.

Python only asks ("halt every chunk with token <= N"); Rust raises its halt
floor, drops queued and playing chunks at or below it, holds, and confirms
the request in the state slot. Two cases, N trials each:
  queued:  the halted node's chunk is queued in Rust (starts 10 ticks ahead);
           a new owner takes over at once but its chunk arrives 0.6 s later.
  playing: the halted node's chunk is already playing (halt ~0.3 s into it).
Measured: halt latency (request -> Rust state shows the halt applied),
steps of the halted chunk played after the request, and whether the new
owner's chunk still played.
"""
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, read_ticks, RESULTS, Shm  # noqa: E402
from rtvla.bridge import Bridge  # noqa: E402
from rtvla.services import Ctx  # noqa: E402

N = 50
CASES = ["queued", "playing"]


def line_chunk(ctx, token, node, start, n=40, dx=0.001):
    p = ctx.robot.get()["pose"]
    acts = [[p[0] + dx * k, p[1], p[2], 0, 0, 0, 0.0] for k in range(n)]
    return {"token": token, "node": node, "version": 1, "run": 0, "owner": 1,
            "start": start, "built_on": 0, "actions": acts, "target": acts[-1][:3]}


def wait_ack(shm, seq, t_req, timeout=1.0):
    """Poll the state slot (every 0.2 ms) until Rust confirms halt `seq`."""
    while time.monotonic() - t_req < timeout:
        s = shm.read_state()
        if s and s["halt_ack"] >= seq:
            return (time.monotonic() - t_req) * 1000, s["halt_ack_tick"]
        time.sleep(0.0002)
    return None, None


def run(case):
    log = f"/tmp/t6h_{case}.csv"
    rust = start_rust(N * 2.0 + 8, log)
    ctx = Ctx({})
    br = Bridge(ctx)
    br.start()
    while ctx.robot.get() is None or br.next_id is None:
        time.sleep(0.01)
    shm = Shm()
    trials = []
    for i in range(N):
        a = ctx.ownership.take(1, "approach")
        t0 = ctx.robot.get()["tick"]
        ctx.inbox.put(line_chunk(ctx, a, "approach", t0 + (10 if case == "queued" else 2)))
        time.sleep(0.1 if case == "queued" else 0.35)
        st = shm.read_state()
        state_at_halt = "queued" if st["chunk_queued"] and not st["step_playing"] >= 0 else \
                        ("playing" if st["step_playing"] >= 0 else "none")
        t_req = time.monotonic()
        ctx.revoke(a)                         # halt: Python asks, Rust decides
        b = ctx.ownership.take(2, "vla")      # the next owner takes over at once
        seq = ctx.halt_seq
        lat_ms, ack_tick = wait_ack(shm, seq, t_req)
        time.sleep(0.6 if case == "queued" else 0.2)
        ctx.inbox.put(line_chunk(ctx, b, "vla", ctx.robot.get()["tick"] + 2, n=10, dx=-0.001))
        time.sleep(0.45)
        ctx.ownership.release(b)
        ctx.inbox.put_owner_none()
        time.sleep(0.3)
        trials.append({"stale": a, "fresh": b, "ack_ms": lat_ms, "ack_tick": ack_tick,
                       "req_tick": st["tick"], "state_at_halt": state_at_halt})
    br.stop_flag = True
    time.sleep(0.1)
    br.quit_rust()
    rust.wait()
    rows = read_ticks(log)
    out = []
    for t in trials:
        stale_rows = [r for r in rows if int(r["token"]) == t["stale"] and r["step"] != "-1"]
        after = [r for r in stale_rows if t["ack_tick"] is not None and int(r["tick"]) >= t["ack_tick"]]
        fresh = sum(1 for r in rows if int(r["token"]) == t["fresh"] and r["step"] != "-1")
        after_req = [r for r in stale_rows if int(r["tick"]) > t["req_tick"]]
        out.append({**t, "stale_steps_total": len(stale_rows), "stale_steps_after_ack": len(after),
                    "stale_steps_after_request": len(after_req), "fresh_steps": fresh})
    lat = sorted(x["ack_ms"] for x in out if x["ack_ms"] is not None)
    late = sum(1 for r in rows if int(r["late_us"]) > 33000)
    summ = {"case": case, "trials": N,
            "state_at_halt": {k: sum(1 for x in out if x["state_at_halt"] == k) for k in ("queued", "playing", "none")},
            "acked": len(lat), "ack_ms_median": lat[len(lat) // 2], "ack_ms_p95": lat[int(len(lat) * 0.95)],
            "ack_ms_max": lat[-1],
            "stale_steps_after_ack_total": sum(x["stale_steps_after_ack"] for x in out),
            "stale_steps_after_request_max": max(x["stale_steps_after_request"] for x in out),
            "stale_steps_after_request_total": sum(x["stale_steps_after_request"] for x in out),
            "stale_steps_total_queued_case": sum(x["stale_steps_total"] for x in out) if case == "queued" else None,
            "fresh_played": sum(1 for x in out if x["fresh_steps"] > 0),
            "late_ticks": late, "ticks": len(rows)}
    return summ, out


if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    CASES = sys.argv[2].split(",") if len(sys.argv) > 2 else CASES
    res = {}
    for c in CASES:
        s, detail = run(c)
        res[c] = s
        res[c + "_trials"] = detail
        print(json.dumps(s), flush=True)
    json.dump(res, open(os.path.join(RESULTS, "t6_halt.json"), "w"), indent=1)
