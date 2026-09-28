"""Re-run the T1 baselines like Rust: 3 runs x 60 s, pinned to core 0 with SCHED_FIFO 50."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import t1_liveness as t
from common import RESULTS
try:
    os.sched_setaffinity(0, {0})
    os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(50))
    rt = True
except Exception as e:
    rt = str(e)
res = {"rt": rt}
for cond in ["normal_0.3s", "vla_1s", "vla_2s", "gil_1s", "plugin_throws"]:
    res[cond] = {"sync": [t.baseline_sync(cond, 60) for _ in range(3)],
                 "threaded": [t.baseline_threaded(cond, 60) for _ in range(3)]}
    print(cond, json.dumps({b: [round(x["max_gap_ms"]) for x in v] for b, v in res[cond].items()}), flush=True)
    json.dump(res, open(os.path.join(RESULTS, "t1_baselines_fair.json"), "w"), indent=1)
