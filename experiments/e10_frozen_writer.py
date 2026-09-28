"""E10: the Python writer freezes in the middle of a command-slot write.

Rust reads the command slot with a sequence lock but tries at most 3 times
per tick; if every try sees a write in progress it keeps the last complete
command. Here we leave the slot half-written (sequence number odd, a new
chunk's header written, its actions only partly) for 2 s, then finish the
write. We check that Rust kept its rate, never played the half-written
chunk, fell back to a hold once the heartbeat went stale, and accepted the
chunk as soon as the write completed.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, read_ticks, RESULTS, Shm  # noqa: E402
from rtvla.bridge import Bridge  # noqa: E402
from rtvla.services import Ctx  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
FREEZE_S = 2.0


def line(p, n, dx):
    return [[p[0] + dx * k, p[1], p[2], 0, 0, 0, 0.0] for k in range(n)]


def main():
    log = "/tmp/e10.csv"
    rust = start_rust(N * (FREEZE_S + 2.5) + 10, log)
    shm = Shm()
    trials = []
    for i in range(N):
        ctx = Ctx({})
        br = Bridge(ctx)
        br.start()
        while ctx.robot.get() is None or br.next_id is None:
            time.sleep(0.005)
        tok = ctx.ownership.take(1, "approach")
        p = ctx.robot.get()["pose"]
        ctx.inbox.put({"token": tok, "node": "approach", "version": 1, "run": 0, "owner": 1,
                       "start": ctx.robot.get()["tick"] + 2, "built_on": 0,
                       "actions": line(p, 50, 0.0005), "target": p[:3]})
        time.sleep(0.4)                        # chunk A is playing
        br.stop_flag = True                    # we become the only writer
        br.join()
        st = shm.read_state()
        cid = max(st["last_chunk_seen"], shm.read_command_field("chunk_id")) + 1
        # ---- begin a write and freeze in the middle of it
        seq = shm._get("command", "seq") + 1
        if seq % 2 == 0:
            seq += 1
        shm._put("command", "seq", seq)        # odd: write in progress
        shm._put("command", "chunk_id", cid)
        shm._put("command", "start_tick", st["tick"] + 2)
        shm._put("command", "token", tok)
        shm._put("command", "steps_used", 30)
        half = line(p, 30, -0.002)[:10]        # only a third of the actions written
        shm._put("command", "actions", [v for a in half for v in a])
        t_freeze = time.monotonic()
        tick_freeze = st["tick"]
        time.sleep(FREEZE_S)                   # writer frozen
        # ---- finish the write
        full = line(shm.read_state()["pose"], 30, -0.002)
        shm._put("command", "actions", [v for a in full for v in a])
        shm._put("command", "start_tick", shm.read_state()["tick"] + 2)
        shm._put("command", "heartbeat", shm._get("command", "heartbeat") + 1)
        shm._put("command", "seq", seq + 1)    # even: write complete
        tick_release = shm.read_state()["tick"]
        time.sleep(1.2)
        trials.append({"cid": cid, "tick_freeze": tick_freeze, "tick_release": tick_release,
                       "t_freeze": t_freeze})
    shm.write_command(quit=1)
    rust.wait()
    rows = read_ticks(log)
    by = {int(r["tick"]): r for r in rows}
    out = []
    for t in trials:
        win = [by[k] for k in range(t["tick_freeze"], t["tick_release"] + 1) if k in by]
        w = [int(r["write_us"]) for r in win]
        played_during = sum(1 for r in win if int(r["chunk"]) == t["cid"] and r["step"] != "-1")
        first_hold = next((int(r["tick"]) for r in win if r["reason"] == "4"), None)
        after = [by[k] for k in range(t["tick_release"], t["tick_release"] + 10) if k in by]
        first_play = next((int(r["tick"]) for r in after if int(r["chunk"]) == t["cid"] and r["step"] != "-1"), None)
        out.append({"late_during": sum(1 for r in win if int(r["late_us"]) > 33000),
                    "max_gap_ms": max(b - a for a, b in zip(w, w[1:])) / 1000,
                    "half_chunk_steps_played": played_during,
                    "ticks_to_hold": None if first_hold is None else first_hold - t["tick_freeze"],
                    "ticks_after_release_to_play": None if first_play is None else first_play - t["tick_release"]})
    summ = {"trials": N, "freeze_s": FREEZE_S,
            "late_during_total": sum(x["late_during"] for x in out),
            "max_gap_ms": max(x["max_gap_ms"] for x in out),
            "half_chunk_steps_played": sum(x["half_chunk_steps_played"] for x in out),
            "ticks_to_hold": sorted(set(x["ticks_to_hold"] for x in out)),
            "ticks_after_release_to_play": sorted(set(x["ticks_after_release_to_play"] for x in out))}
    print(json.dumps(summ))
    json.dump({"summary": summ, "trials": out}, open(os.path.join(RESULTS, "e10_frozen_writer.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
