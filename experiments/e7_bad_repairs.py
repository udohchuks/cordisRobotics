"""E7: faulty repairs, as a stand-in for unreliable agent-written code.

Each trial: the robot runs a working approach (v2) for one episode, then a
faulty repair of approach is loaded and tried (Cordis swap, trial k=3), and
three more episodes run after the swap ends. Rust's tick log is the judge.
  load_raise  registers, then raises during load -> the undo removes the registration
  syntax      does not parse                    -> load must fail, nothing left behind
  tick_raise  raises right after sending a chunk -> its chunk must stop; rollback
  hang        endless loop after sending a chunk -> watchdog; chunk must stop; rollback
  nan         sends NaN actions                  -> Rust rejects the chunk; rollback
  forged      uses a token it does not own       -> never reaches the arm; rollback
  far         aims 1 m away                      -> speed and workspace limits hold; rollback
  slow        blocks the loop 0.3 s every tick   -> arm keeps its rate
  halt_raises correct motion, halt() crashes     -> halt still takes effect (cube moved mid-approach)
  leak        wrong aim + thread with no undo    -> rollback; the leak is detected, not undone
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
CLASSES = ["load_raise", "syntax", "tick_raise", "hang", "hang_swallow", "nan", "forged", "far", "slow", "halt_raises", "leak", "patch_shared"]
VCAP_MM = 0.25 * 0.033 * 1000


def one(cls, r, naive=False):
    log, out = f"/tmp/e7_{cls}_{r}.csv", f"/tmp/e7_{cls}_{r}.json"
    if os.path.exists(out):
        os.remove(out)
    rust = start_rust(170, log)
    env = dict(os.environ, RTVLA_EP_TIMEOUT="15")
    args = [PY, RUNNER, "--approach", "v2", "--seconds", "160", "--swap_after", "1",
            "--swap_to", f"f_{cls}", "--trial_k", "3", "--after_swap", "3", "--out", out]
    if cls == "halt_raises":
        args += ["--move_cube_mid", "1"]
    if naive:
        args += ["--naive", "1"]
    subprocess.run(args, env=env)
    Shm().write_command(quit=1)
    rust.wait()
    o = json.load(open(out))
    sw = o["swap"]
    rows = read_ticks(log)
    w = [int(x["write_us"]) for x in rows]
    pts = [(float(x["x"]), float(x["y"]), float(x["z"])) for x in rows]
    finite = all(all(math.isfinite(v) for v in p) for p in pts)
    steps = [math.dist(a, b) for a, b in zip(pts, pts[1:])] if finite else [float("nan")]
    in_ws = all(-0.35 <= p[0] <= 0.35 and -0.35 <= p[1] <= 0.35 and 0.0 <= p[2] <= 0.40 for p in pts)
    dead = sum(1 for x in rows if x["step"] != "-1" and int(x["token"]) != 0
               and int(x["token"]) <= int(x["halt_floor"]))
    after = [e for e in o["episodes"] if e["start"] > sw.get("t_done", 1e9)][:3]
    return {"cls": cls, "run": r, "mode": "naive" if naive else ("dsu" if os.environ.get("RTVLA_UNDO_LOG") == "0" else "ours"),
            "load_state": sw.get("load_state"), "result": sw.get("result", sw.get("load_state")),
            "trial": sw.get("trial"),
            "identical_after": sw["fingerprint_before"] == sw["fingerprint_after"],
            "fp_diff": {k: (sw["fingerprint_before"][k], sw["fingerprint_after"][k])
                        for k in sw["fingerprint_before"] if sw["fingerprint_before"][k] != sw["fingerprint_after"][k]},
            "ticks": len(rows), "late": sum(1 for x in rows if int(x["late_us"]) > 33000),
            "max_gap_ms": max(b - a for a, b in zip(w, w[1:])) / 1000,
            "pose_finite": finite, "in_workspace": in_ws,
            "max_step_mm": round(max(steps) * 1000, 3), "cap_mm": round(VCAP_MM, 3),
            "dead_token_steps": dead, "halted_hold_ticks": sum(1 for x in rows if x["reason"] == "6"), "halts": o["halts"], "watchdog_fired": o["watchdog_fired"],
            "errors": o["errors"], "inbox_rejected": o["inbox_rejected"], **o["final_state"],
            "tree_tick_ms_max": o["tree_tick_ms_max"], "py_max_gap_ms": o["py_max_gap_ms"],
            "after_ok": [e["ok"] for e in after],
            "early_reject": sw.get("early_reject"),
            "ms_ready_to_done": round((sw["t_done"] - sw["t_ready"]) * 1000) if "t_done" in sw else None}


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    classes = sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[2] != "all" else CLASSES
    naive = len(sys.argv) > 3 and sys.argv[3] == "naive"
    dsu = len(sys.argv) > 3 and sys.argv[3] == "dsu"
    if dsu:
        os.environ["RTVLA_UNDO_LOG"] = "0"
    path = os.path.join(RESULTS, "e7_naive.jsonl" if naive else "e7_dsu.jsonl" if dsu else "e7.jsonl")
    for r in range(n):
        for c in classes:
            m = one(c, r, naive)
            with open(path, "a") as f:
                f.write(json.dumps(m) + "\n")
            print(json.dumps(m), flush=True)
