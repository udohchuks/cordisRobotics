"""E11: how often does a k-episode trial keep a repair that fails a fraction p of the time?

Base: working approach. Repair: approach_f_flaky (3 cm off on a fraction p of
cube positions, decided per episode). One swap per run with trial k.
usage: e11_flaky.py <runs> <p1,p2,...> [k]
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, RESULTS, ROOT, Shm  # noqa: E402

PY = sys.executable
RUNNER = os.path.join(ROOT, "experiments", "run_runtime.py")

if __name__ == "__main__":
    n = int(sys.argv[1])
    ps = [float(x) for x in sys.argv[2].split(",")]
    k = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    r0 = int(os.environ.get("E11_R0", "0"))
    for r in range(r0, r0 + n):
        for p in ps:
            log, out = f"/tmp/e11_{p}_{r}.csv", f"/tmp/e11_{p}_{r}.json"
            rust = start_rust(300, log)
            env = dict(os.environ, RTVLA_FLAKY_P=str(p), RTVLA_EP_TIMEOUT="15")
            subprocess.run([PY, RUNNER, "--approach", "v2", "--seconds", "280", "--swap_after", "1",
                            "--swap_to", "f_flaky", "--trial_k", str(k), "--after_swap", "0", "--seed", str(1000 + r), "--out", out],
                           env=env, cwd=ROOT)
            Shm().write_command(quit=1)
            rust.wait()
            sw = json.load(open(out))["swap"]
            rec = {"p": p, "k": k, "run": r, "result": sw.get("result"), "trial": sw.get("trial"),
                   "seed_note": "cube positions from Runtime(seed=0) rng"}
            with open(os.path.join(RESULTS, "e11_flaky.jsonl"), "a") as f:
                f.write(json.dumps(rec) + "\n")
            print(json.dumps(rec), flush=True)
