"""T2 leak check: load and unload approach 100 times beside the live v1.
Registry entries, loaded plugins, plugin modules, threads and Python memory
must come back to where they started."""
import gc
import json
import os
import sys
import threading
import tracemalloc

sys.path.insert(0, os.path.dirname(__file__))
from common import RESULTS  # noqa: E402
from rtvla.cordis import Cordis  # noqa: E402
from rtvla.runtime import SETTINGS, NODES  # noqa: E402
from rtvla.services import Ctx  # noqa: E402

N = 100
ctx = Ctx(SETTINGS)
co = Cordis(ctx)
co.load(os.path.join(NODES, "basics.py"))
co.load(os.path.join(NODES, "approach_v1.py"))


def snap():
    gc.collect()
    return {"registry_size": ctx.registry.size(), "live": dict(ctx.registry.live),
            "fibers": len(co.fibers), "plugin_modules": sum(1 for m in sys.modules if m.startswith("plugin_")),
            "threads": threading.active_count(), "py_bytes": tracemalloc.get_traced_memory()[0]}


tracemalloc.start()
# warm-up cycle so first-import caches are not counted as a leak
f = co.load(os.path.join(NODES, "approach_v2.py"))
co.unload(f)
before = snap()
mid = None
for i in range(N):
    f = co.load(os.path.join(NODES, "approach_v2.py"))
    assert f.state == "ACTIVE"
    if i == N // 2:
        mid = snap()
    co.unload(f)
bad = 0
for i in range(N):                       # also 100 failed loads (crash mid-load)
    f = co.load(os.path.join(NODES, "approach_v2_bad_load.py"))
    bad += f.state == "FAILED"
after = snap()
res = {"cycles": N, "failed_load_cycles": N, "failed_loads_marked_failed": bad,
       "before": before, "during_one_load": mid, "after": after,
       "bytes_per_cycle": (after["py_bytes"] - before["py_bytes"]) / (2 * N),
       "structures_back_to_start": {k: before[k] == after[k] for k in before if k != "py_bytes"}}
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(RESULTS, "t2_leak.json"), "w"), indent=1)
