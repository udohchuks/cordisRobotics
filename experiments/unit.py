"""Run one short unit of an experiment and append its result to RESULTS/<name>.jsonl.
Used on machines where a single command may run for at most ~3 minutes.
  unit.py t2 <kind> <run>      kind: restart swap bad_load bad_trial restart_bad_load
  unit.py t4 <run>
  unit.py t1 <cond> <run>      also: t1 <cond> base   (baselines, 30 s each)
  unit.py rust_only <secs>
  unit.py t3 <n>   |  unit.py t6 <n>
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from common import RESULTS  # noqa: E402

def out(name, rec):
    rec["t"] = time.time()
    with open(os.path.join(RESULTS, name + ".jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))

a = sys.argv[1:]
os.makedirs(RESULTS, exist_ok=True)
if a[0] == "t2":
    import t2_repair as t
    kind, r = a[1], int(a[2])
    m = t.run_restart(r) if kind == "restart" else t.run_restart(r, fix="v2_bad_load") if kind == "restart_bad_load" else t.run_swap(kind, r)
    out("t2", {"kind": kind, "run": r, **m})
elif a[0] == "t4":
    import t4_midswap as t
    out("t4", {"run": int(a[1]), **t.one(int(a[1]), 1)})
elif a[0] == "t1":
    import t1_liveness as t
    cond = a[1]
    if a[2] == "base":
        out("t1", {"cond": cond, "who": "sync", **t.baseline_sync(cond, 30)})
        out("t1", {"cond": cond, "who": "threaded", **t.baseline_threaded(cond, 30)})
    else:
        out("t1", {"cond": cond, "who": "ours", "run": int(a[2]), **t.ours(cond, 60, int(a[2]))})
elif a[0] == "rust_only":
    from common import start_rust, read_ticks, tick_metrics
    p = start_rust(float(a[1]), "/tmp/rust_only.csv"); p.wait()
    out("rust_only", tick_metrics(read_ticks("/tmp/rust_only.csv")))
elif a[0] == "t6h":
    import t6_halt as t
    t.N = int(a[1])
    for case in a[2].split(","):
        summ, detail = t.run(case)
        out("t6h", summ)
elif a[0] in ("t3", "t6"):
    import subprocess
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), {"t3": "t3_faults.py", "t6": "t6_epoch.py"}[a[0]]), a[1]])
