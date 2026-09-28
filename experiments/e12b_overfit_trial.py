"""E12b: does the 3-episode trial keep the overfit |y| repair of the flipped-sign bug?"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, RESULTS, ROOT, Shm  # noqa: E402

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    for r in range(n):
        log, out = f"/tmp/e12b_{r}.csv", f"/tmp/e12b_{r}.json"
        rust = start_rust(200, log)
        subprocess.run([sys.executable, os.path.join(ROOT, "experiments", "run_runtime.py"), "--approach", "bug_sign_y",
                        "--seconds", "180", "--swap_after", "2", "--swap_to", "overfit_abs_y", "--trial_k", "3",
                        "--after_swap", "0", "--seed", str(500 + r), "--out", out],
                       env=dict(os.environ, RTVLA_EP_TIMEOUT="15"), cwd=ROOT)
        Shm().write_command(quit=1)
        rust.wait()
        sw = json.load(open(out))["swap"]
        rec = {"run": r, "result": sw.get("result"), "trial": sw.get("trial")}
        with open(os.path.join(RESULTS, "e12b_overfit_trial.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)
