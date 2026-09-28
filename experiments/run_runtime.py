"""Run the Python runtime as its own process (so experiments can kill it)."""
import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from common import pin_python  # noqa: E402
from rtvla.runtime import Runtime, NODES  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--approach", default="v2")
ap.add_argument("--delay", type=float, default=0.3)
ap.add_argument("--stall", default="sleep")
ap.add_argument("--gil_n", type=int, default=25)
ap.add_argument("--seconds", type=float, default=60)
ap.add_argument("--episodes", type=int, default=None)
ap.add_argument("--out", default="/tmp/rt.json")
ap.add_argument("--swap_after", type=int, default=None)
ap.add_argument("--swap_to", default="v2")
ap.add_argument("--trial_k", type=int, default=3)
ap.add_argument("--hash_file", default=None)
ap.add_argument("--epoch", type=int, default=0)
ap.add_argument("--swap_mid", type=int, default=0)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--naive", type=int, default=0)             # baseline: plain hot reload
ap.add_argument("--after_swap", type=int, default=None)   # stop N episodes after the swap ends
ap.add_argument("--move_cube_mid", type=int, default=0)   # move the cube during approach in trial episodes
a = ap.parse_args()
if not os.environ.get("RTVLA_NOPIN"):
    pin_python()
if os.environ.get("RTVLA_LOAD_VLA") and a.stall != "smolvla":
    # hold the real SmolVLA weights in memory (as a deployed runtime would);
    # grasps still use the stand-in chunk so episodes can succeed on CPU
    from rtvla import real_vla
    real_vla.load(int(os.environ.get("TORCH_THREADS", "1")))
if a.stall == "smolvla":
    from rtvla import real_vla
    real_vla.load(int(os.environ.get("TORCH_THREADS", "1")))
vla = {"stall": a.stall, "delay": a.delay, "gil_n": a.gil_n,
       "expected_delay": min(a.delay, 1.2) if a.stall == "sleep" else 0.3}
rt = Runtime(approach_path=os.path.join(NODES, f"approach_{a.approach}.py"), vla=vla, seed=a.seed)
t0 = time.monotonic()
swap_log = {}
if a.hash_file:
    from rtvla.services import state_hash

    def write_hash(r):
        st = r.ctx.robot.get()
        with open(a.hash_file, "w") as f:
            json.dump({"tick": st["tick"], "hash": state_hash(r.ctx.blackboard.d, r.ctx.settings.values,
                                                               r.ctx.ownership.snapshot()),
                       "n_loaded": len(r.cordis.fibers), "episodes": len(r.episodes)}, f)
    rt.hooks.append(write_hash)


if a.move_cube_mid:
    moved = set()

    def mover(r):
        n = len(r.episodes)
        if "t_live" not in swap_log or "result" in swap_log or n in moved:
            return
        if "approach" in r.ctx.running and r.ctx.robot.get()["chunk_queued"] + r.ctx.robot.get()["chunk_playing"]:
            rec = [v for v in r.ctx.sent.all().values() if v["node"] == "approach"]
            if rec and rec[-1]["version"] == 2 and len(rec) > 0:
                c = r.ctx.robot.get()["cube"]
                r.bridge.request_reset([c[0], c[1] + 0.04, c[2]])
                moved.add(n)
    rt.hooks.append(mover)


async def main():
    task = asyncio.create_task(rt.run(n_episodes=a.episodes, seconds=a.seconds))
    if a.swap_after is not None:
        while len(rt.episodes) < a.swap_after:
            await asyncio.sleep(0.05)
        if a.swap_mid:   # request the repair while approach is driving the arm
            while "approach" not in rt.ctx.running:
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.05)
        if a.naive:
            await rt.naive_swap("approach", os.path.join(NODES, f"approach_{a.swap_to}.py"), log=swap_log)
        else:
            await rt.swap("approach", os.path.join(NODES, f"approach_{a.swap_to}.py"),
                          trial_k=a.trial_k, log=swap_log)
        if a.after_swap is not None:
            t_done = swap_log.get("t_done", time.monotonic())
            while sum(1 for e in rt.episodes if e["start"] > t_done) < a.after_swap and not task.done():
                await asyncio.sleep(0.05)
            rt.stop = True
    await task

asyncio.run(main())
sent = rt.bridge.sent_log
for k in [k for k in swap_log if k.startswith("t_")]:
    swap_log[k] -= t0
out = {"swap": swap_log, "episodes": [{"ok": e["ok"], "start": e["start"] - t0, "end": e["end"] - t0, "v": e["approach_version"]} for e in rt.episodes],
       "tree_tick_ms_max": max(rt.tick_times) * 1000 if rt.tick_times else None,
       "inbox_rejected": rt.ctx.inbox.rejected,
       "py_max_gap_ms": max((b - a for a, b in zip(rt.bridge.write_times, rt.bridge.write_times[1:])), default=0) * 1000,
       "vla_times": (__import__("rtvla.real_vla", fromlist=["x"]).times if a.stall == "smolvla" else []),
       "tree_tick_ms_p99": sorted(rt.tick_times)[int(len(rt.tick_times) * 0.99)] * 1000 if rt.tick_times else None,
       "errors": sum(1 for e in rt.ctx.events if e[1] == "error"),
       "halts": len(rt.ctx.halt_log), "watchdog_fired": len(rt.ctx.watchdog_fired),
       "final_state": {k: rt.ctx.robot.get()[k] for k in ("halt_floor", "halt_ack", "rejected_bad", "rejected_halted")}}
json.dump(out, open(a.out, "w"))
