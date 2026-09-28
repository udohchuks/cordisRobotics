"""Route 1: the real runtime (tree, plugins, swaps, bridge) driving the MuJoCo plant."""
import asyncio, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "sim", "mujoco")); sys.path.insert(0, os.path.join(ROOT, "py"))
os.environ.setdefault("RTVLA_HOME", "[0.20, 0.0, 0.085]")
os.environ.setdefault("RTVLA_VLA_DESCENT_STEPS", "20")
from mjrun import start  # noqa: E402
import ik  # noqa: E402
from rtvla import runtime as R  # noqa: E402
from rtvla.mjadapter import MjAdapter  # noqa: E402

# settings for the SO-101 scene (the toy values assume a point robot)
R.SETTINGS["approach"].update(handoff_height=0.05, tol=0.008, retarget=0.005, speed=0.15)
R.SETTINGS["carry"].update(carry_height=0.085, tol=0.01, speed=0.15)
R.SETTINGS["place"].update(release_height=0.075, tol=0.008, speed=0.1)
R.SETTINGS["retreat"].update(tol=0.015, speed=0.2)
R.SETTINGS["recover"].update(tol=0.015, speed=0.15)
R.CUBE_HOME[:] = [0.22, 0.07, 0.0125]
R.SETTINGS["vla_grasp"].update(closed_ticks=14)
HOME = json.loads(os.environ["RTVLA_HOME"])


def launch(duration, tag, approach=None, seed=0):
    os.environ["RTVLA_SEED"] = str(seed)
    q_home, _ = ik.ik(HOME, [0, 0, 0, 1.2, 0])
    shm, plant, rust, pl_out, rs_log = start(list(q_home) + [1.0], duration, tag)
    rt = R.Runtime(approach_path=approach, seed=seed)
    ad = MjAdapter(rt.ctx)
    return rt, ad, (shm, plant, rust, pl_out, rs_log)


def finish(rt, procs):
    shm, plant, rust, pl_out, rs_log = procs
    rt.bridge.stop_flag = True; time.sleep(0.1)
    rt.bridge.quit_rust(); rust.wait(); plant.wait(timeout=30)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    ap = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "py", "nodes", "approach_v2.py")
    rt, ad, procs = launch(40 * n + 20, "rt", approach=ap)
    t0 = time.monotonic()
    asyncio.run(rt.run(n_episodes=n))
    finish(rt, procs)
    for e in rt.episodes:
        print(json.dumps({"ok": e["ok"], "dur": round(e["end"] - e["start"], 2), "v": e["approach_version"]}))
    print("ok", sum(e["ok"] for e in rt.episodes), "/", n, "ik_ms p50", sorted(ad.ik_ms)[len(ad.ik_ms)//2] if ad.ik_ms else None)
    ev = [(round(t - t0, 2), k, n_) for (t, k, n_, *r) in rt.ctx.events]
    json.dump(ev, open("/tmp/rt_events.json", "w"))
