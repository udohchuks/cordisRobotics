"""E6: the stale-chunk gap and the Rust control epoch.

A code node's chunk is queued (starts 10 ticks ahead). The node is halted
and a new owner takes over in the same moment, but the new owner's chunk
only arrives 0.6 s later (like a VLA call). Question: do any steps of the
halted node's chunk play in between?
  epoch off: Rust does not know the token was revoked -> the stale chunk plays.
  epoch on:  Python writes revoked_max; Rust drops the chunk and holds.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, read_ticks, RESULTS  # noqa: E402
from rtvla.bridge import Bridge  # noqa: E402
from rtvla.services import Ctx  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 50


def line_chunk(ctx, token, node, start, n=40, dx=0.001):
    p = ctx.robot.get()["pose"]
    acts = [[p[0] + dx * k, p[1], p[2], 0, 0, 0, 0.0] for k in range(n)]
    return {"token": token, "node": node, "version": 1, "run": 0, "owner": 1,
            "start": start, "built_on": 0, "actions": acts, "target": acts[-1][:3]}


def run(epoch):
    log = f"/tmp/t6_{'on' if epoch else 'off'}.csv"
    rust = start_rust(N * 1.6 + 8, log)
    ctx = Ctx({})
    ctx.epoch_enabled = epoch
    br = Bridge(ctx)
    br.start()
    while ctx.robot.get() is None or br.next_id is None:
        time.sleep(0.01)
    trials = []
    for i in range(N):
        a = ctx.ownership.take(1, "approach")
        ctx.inbox.put(line_chunk(ctx, a, "approach", ctx.robot.get()["tick"] + 10))
        time.sleep(0.1)                      # bridge sends it: queued in Rust
        ctx.revoke(a)                        # halt (cube moved)...
        b = ctx.ownership.take(2, "vla")     # ...and the VLA takes over at once
        t_halt_tick = ctx.robot.get()["tick"]
        time.sleep(0.6)                      # VLA inference
        ctx.inbox.put(line_chunk(ctx, b, "vla", ctx.robot.get()["tick"] + 2, n=10, dx=-0.001))
        time.sleep(0.4)
        ctx.ownership.release(b)
        ctx.inbox.put_owner_none()
        time.sleep(0.4)
        trials.append({"stale": a, "fresh": b, "halt_tick": t_halt_tick})
    br.stop_flag = True
    time.sleep(0.1)
    br.quit_rust()
    rust.wait()
    rows = read_ticks(log)
    played = {}
    for r in rows:
        if r["step"] != "-1":
            played[int(r["token"])] = played.get(int(r["token"]), 0) + 1
    stale_steps = [played.get(t["stale"], 0) for t in trials]
    fresh_ok = sum(1 for t in trials if played.get(t["fresh"], 0) > 0)
    return {"trials": N, "trials_with_stale_steps": sum(1 for x in stale_steps if x > 0),
            "stale_steps_total": sum(stale_steps), "stale_steps_max": max(stale_steps),
            "fresh_chunk_played": fresh_ok,
            "hold_revoked_ticks": sum(1 for r in rows if r["reason"] == "6")}


if __name__ == "__main__":
    res = {"epoch_off": run(False), "epoch_on": run(True)}
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(RESULTS, "t6_epoch.json"), "w"), indent=1)
