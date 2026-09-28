"""E5: the real SmolVLA (450M) running inference on the same CPU.

The runtime runs pick-and-place while every grasp calls the real SmolVLA on
CPU (its output is not used; the stand-in chunk is). Two set-ups:
  isolated: Rust pinned to core 0 at real-time priority; Python + PyTorch
            (1 thread) pinned to core 1.
  shared:   no pinning, normal priority for all, PyTorch with 2 threads,
            so inference competes with Rust for both cores.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, read_ticks, tick_metrics, RESULTS, ROOT  # noqa: E402

PY = sys.executable
RUNNER = os.path.join(ROOT, "experiments", "run_runtime.py")


def one(setup, r, seconds=60):
    log, out = f"/tmp/t5_{setup}_{r}.csv", f"/tmp/t5_{setup}_{r}.json"
    iso = setup == "isolated"
    rust = start_rust(seconds + 25, log, rt=iso)
    env = dict(os.environ, TORCH_THREADS="1" if iso else "2")
    if not iso:
        env["RTVLA_NOPIN"] = "1"
    subprocess.run([PY, RUNNER, "--approach", "v2", "--stall", "smolvla", "--seconds", str(seconds),
                    "--out", out], env=env, stderr=subprocess.DEVNULL)
    from common import Shm
    Shm().write_command(quit=1)
    rust.wait()
    m = tick_metrics(read_ticks(log))
    o = json.load(open(out))
    vt = sorted(o["vla_times"])
    m.update({"setup": setup, "run": r, "vla_calls": len(vt), "vla_median_s": vt[len(vt) // 2] if vt else None,
              "vla_max_s": vt[-1] if vt else None, "python_bridge_max_gap_ms": o["py_max_gap_ms"],
              "tree_tick_ms_max": o["tree_tick_ms_max"], "tree_tick_ms_p99": o["tree_tick_ms_p99"],
              "episodes": len(o["episodes"]), "episodes_ok": sum(e["ok"] for e in o["episodes"])})
    return m


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    res = []
    for setup in ("isolated", "shared"):
        for r in range(runs):
            m = one(setup, r)
            res.append(m)
            print(json.dumps(m), flush=True)
            json.dump(res, open(os.path.join(RESULTS, "t5_realvla.json"), "w"), indent=1)
