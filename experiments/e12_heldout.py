"""E12: do accepted repairs hold up on cube positions the trial never saw?

Each repair file is run as the live approach for 12 episodes on a fixed grid
of cube positions spread over the workspace (the trial episodes use the home
position +-1 cm). Repairs: every distinct kept agent repair from E9, the
hand-written fix, and one plausible overfit repair.
usage: e12_heldout.py
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, RESULTS, ROOT, Shm  # noqa: E402

PY = sys.executable
RUNNER = os.path.join(ROOT, "experiments", "run_runtime.py")
NODES = os.path.join(ROOT, "py", "nodes")
GRID = [[x, y] for x in (0.04, 0.10, 0.16) for y in (-0.06, 0.0, 0.05, 0.11)]


def norm_code(src):
    src = re.sub(r'""".*?"""', "", src, flags=re.S)
    src = re.sub(r"#.*", "", src)
    return hashlib.sha1(re.sub(r"\s+", "", src).encode()).hexdigest()[:10]


def repairs():
    out = {"handwritten_v2": os.path.join(NODES, "approach_v2.py"),
           "overfit_abs_y": os.path.join(NODES, "approach_overfit_abs_y.py")}
    seen = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "results_v2", "e9_transcripts", "*.json"))):
        d = json.load(open(f))
        for a in d["attempts"]:
            if a["result"] != "kept":
                continue
            h = norm_code(a["code"])
            seen.setdefault(h, []).append(f"{d['bug']}_{d['run']}")
            if len(seen[h]) == 1:
                p = f"/tmp/e12_agent_{h}.py"
                open(p, "w").write(a["code"])
                out[f"agent_{h}"] = p
    return out, seen


if __name__ == "__main__":
    reps, seen = repairs()
    print("distinct agent repairs:", {h: len(v) for h, v in seen.items()}, flush=True)
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for name, path in reps.items():
        if only and name != only:
            continue
        log, outp = f"/tmp/e12_{name}.csv", f"/tmp/e12_{name}.json"
        rust = start_rust(400, log)
        # run_runtime takes an approach name; point it at the file through a temporary copy
        tmp = os.path.join(NODES, "approach__e12tmp.py")
        open(tmp, "w").write(open(path).read())
        env = dict(os.environ, RTVLA_CUBE_POSITIONS=json.dumps(GRID), RTVLA_EP_TIMEOUT="15")
        subprocess.run([PY, RUNNER, "--approach", "_e12tmp", "--episodes", str(len(GRID)), "--seconds", "380",
                        "--out", outp], env=env, cwd=ROOT)
        Shm().write_command(quit=1)
        rust.wait()
        eps = json.load(open(outp))["episodes"]
        oks = [e["ok"] for e in eps]
        rec = {"repair": name, "sessions": seen.get(name.replace("agent_", ""), []),
               "ok": sum(oks), "n": len(oks),
               "failed_positions": [GRID[i] for i, ok in enumerate(oks) if not ok]}
        with open(os.path.join(RESULTS, "e12_heldout.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)
    if os.path.exists(os.path.join(NODES, "approach__e12tmp.py")):
        os.remove(os.path.join(NODES, "approach__e12tmp.py"))
