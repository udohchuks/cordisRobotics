"""Route 1 demo: ONE continuous run of the real runtime on the MuJoCo plant.

Script (all through Runtime.swap, the same code as the toy-sim results):
  A  approach v1 (planted 3 cm aim bug) runs 2 episodes      -> expected to fail
  B  live repair: swap to approach v2 (fix), trial k=3        -> expected kept
  C  bad repair: approach_f_nan (sends NaN)                   -> Rust rejects, rolled back
  D  bad repair: approach_bug_bowl (heads for the bowl wall)  -> keep-out halt, rolled back
  E  2 more episodes on the kept v2                           -> task continues
The cube is repositioned by the simulator between episodes (disclosed);
episode outcomes are recorded before each reposition.
"""
import asyncio, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import mj_runtime as M  # noqa: E402  (applies the SO-101 settings)
from rtvla.keepout import KeepOut  # noqa: E402

NODES = os.path.join(ROOT, "py", "nodes")
OUT = os.path.join(ROOT, "results_mj", "demo"); os.makedirs(OUT, exist_ok=True)


async def scenario(rt, ko, marks):
    t0 = rt.t0
    def mark(name, **kw):
        marks.append(dict(t=time.monotonic() - t0, event=name, episodes=len(rt.episodes), **kw)); print(marks[-1], flush=True)
    async def wait_eps(n):
        target = len(rt.episodes) + n
        while len(rt.episodes) < target:
            await asyncio.sleep(0.05)
    mark("start", version=rt.ctx.registry.lookup("approach")[0])
    await wait_eps(2)
    for label, f, k in [("B_fix", "approach_v2.py", 3), ("C_nan", "approach_f_nan.py", 3), ("D_bowl", "approach_bug_bowl.py", 3)]:
        mark(f"{label}_arrives", file=f)
        log = await rt.swap("approach", os.path.join(NODES, f), trial_k=k)
        rel = {k2: (v - t0 if k2.startswith("t_") and isinstance(v, float) else v) for k2, v in log.items()
               if not k2.startswith("fingerprint")}
        rel["fingerprint_equal_after"] = log.get("fingerprint_before") == log.get("fingerprint_after")
        mark(f"{label}_done", result=log.get("result"), early=log.get("early_reject"), trial=log.get("trial"))
        json.dump(rel, open(os.path.join(OUT, f"swap_{label}.json"), "w"), indent=1, default=str)
        await wait_eps(1)
    await wait_eps(2)
    mark("end", version=rt.ctx.registry.lookup("approach")[0])
    rt.stop = True


async def main(rt, ko, marks):
    rt.t0 = time.monotonic()
    runner = asyncio.create_task(rt.run(seconds=400))
    while rt.ctx.robot.get() is None or rt.bridge.next_id is None:
        await asyncio.sleep(0.01)
    ko.start()
    await scenario(rt, ko, marks)
    await runner


if __name__ == "__main__":
    rt, ad, procs = M.launch(420, "demo", approach=os.path.join(NODES, "approach_v1.py"), seed=1)
    ko = KeepOut(rt.ctx, watched=("approach",), d=0.03)
    marks = []
    asyncio.run(main(rt, ko, marks))
    ko.stop_flag = True
    M.finish(rt, procs)
    shm, plant, rust, pl_out, rs_log = procs
    import shutil
    shutil.copy(pl_out, os.path.join(OUT, "plant.npz")); shutil.copy(rs_log, os.path.join(OUT, "ticks.csv"))
    t0 = rt.t0
    json.dump({"marks": marks,
               "episodes": [dict(start=e["start"] - t0, end=e["end"] - t0, ok=e["ok"], version=e["approach_version"]) for e in rt.episodes],
               "events": [(ev[0] - t0,) + tuple(str(x) for x in ev[1:5]) for ev in rt.ctx.events if ev[2] not in ("cube_near_seen", "cube_in_gripper", "perceive")],
               "keepout": [dict(f, t=f["t"] - t0) for f in ko.fired],
               "halt_log": [(s, tok, t - t0) for s, tok, t in rt.ctx.halt_log],
               "sent": [(t - t0, cid, tok, node, st, n, tk) for (t, cid, tok, node, st, n, tk) in rt.bridge.sent_log],
               "t0_monotonic": t0},
              open(os.path.join(OUT, "run.json"), "w"), indent=1, default=str)
    print("episodes:", [(round(e["end"] - t0, 1), e["ok"], e["approach_version"]) for e in rt.episodes])
