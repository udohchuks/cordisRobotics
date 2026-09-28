"""E8: swap vs restart when the runtime holds the real SmolVLA weights.

Same protocol as T2 (swap / restart), but the Python process loads the real
SmolVLA (450M parameters) at start, as a deployed runtime would. A restart
must load it again; a live swap never touches it. Grasps still use the
stand-in chunk so episodes can succeed on CPU.
usage: e8_restart_vla.py <runs>
"""
import json
import os
import sys

os.environ["RTVLA_LOAD_VLA"] = "1"
os.environ.setdefault("RTVLA_RUST_S", "600")
sys.path.insert(0, os.path.dirname(__file__))
import t2_repair as t  # noqa: E402
from common import RESULTS  # noqa: E402

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    for r in range(n):
        for kind in ("swap", "restart"):
            m = t.run_swap("swap", 100 + r) if kind == "swap" else t.run_restart(100 + r)
            m["kind"] = kind
            with open(os.path.join(RESULTS, "e8_restart_vla.jsonl"), "a") as f:
                f.write(json.dumps(m) + "\n")
            print(json.dumps(m), flush=True)
