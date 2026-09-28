"""E4: repair requested in the middle of a skill (the idle-point rule).

Like T2's swap, but the fix becomes ready 0.2 s after approach v1 has
started driving the arm. The swap must wait for approach's idle point
(not running, none of its chunks queued or playing, no VLA call in flight).
We measure the wait, missed ticks, the largest per-tick hand displacement
around the swap (a jump would show up here), and success afterwards.
"""
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, read_ticks, RESULTS, ROOT, Shm  # noqa: E402

PY = sys.executable
RUNNER = os.path.join(ROOT, "experiments", "run_runtime.py")


def one(r, epoch):
    log, out = f"/tmp/t4_{epoch}_{r}.csv", f"/tmp/t4_{epoch}_{r}.json"
    rust = start_rust(90, log)
    subprocess.run([PY, RUNNER, "--approach", "v1", "--episodes", "6", "--seconds", "85",
                    "--swap_after", "2", "--swap_mid", "1", "--swap_to", "v2", "--trial_k", "3", "--out", out])
    Shm().write_command(quit=1)
    rust.wait()
    o = json.load(open(out))
    sw = o["swap"]
    rows = read_ticks(log)
    by_tick = {int(x["tick"]): x for x in rows}
    k0, k1 = sw["tick_ready"], sw["tick_live"]
    win = [by_tick[k] for k in range(k0 - 30, k1 + 60) if k in by_tick]
    steps = [math.dist([float(a["x"]), float(a["y"]), float(a["z"])], [float(b["x"]), float(b["y"]), float(b["z"])])
             for a, b in zip(win, win[1:])]
    w = [int(x["write_us"]) for x in rows if int(x["tick"]) >= k0]
    after = [e for e in o["episodes"] if e["start"] > sw["t_ready"]]
    return {"approach_running_at_ready": "approach" in (sw.get("running_at_ready") or []),
            "ms_waiting_for_idle": round((sw["t_idle"] - sw["t_ready"]) * 1000),
            "result": sw["result"], "state_unchanged": sw["hash_before"] == sw["hash_after"],
            "missed": sum(1 for x in rows if int(x["tick"]) >= k0 and int(x["late_us"]) > 33000),
            "max_gap_ms": max(b - a for a, b in zip(w, w[1:])) / 1000,
            "max_hand_step_mm": round(max(steps) * 1000, 2),
            "speed_cap_step_mm": round(0.25 * 0.033 * 1000, 2),
            "mismatch_flags": sum(int(x["mismatch"]) for x in win),
            "episodes_after": [(e["v"], e["ok"]) for e in after]}


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    res = {"runs": []}
    for r in range(runs):
        m = one(r, 1)
        res["runs"].append(m)
        print(r, json.dumps(m), flush=True)
        json.dump(res, open(os.path.join(RESULTS, "t4_midswap.json"), "w"), indent=1)
