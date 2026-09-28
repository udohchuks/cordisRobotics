"""E8b: swap vs restart when SmolVLA lives in its own persistent process.

A VLA server process loads the real SmolVLA weights once and stays up. The
code runtime talks to it over a Unix socket. A restart now kills and
restarts only the code process, which must reconnect but not reload the
model. Same T2 protocol otherwise. usage: e8b_restart_vla_server.py <runs>
"""
import json
import os
import subprocess
import sys
import time

ADDR = "/tmp/vla.sock"
os.environ["RTVLA_VLA_SERVER"] = ADDR
os.environ.pop("RTVLA_LOAD_VLA", None)
sys.path.insert(0, os.path.dirname(__file__))
import t2_repair as t  # noqa: E402
from common import RESULTS, ROOT  # noqa: E402

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    srv = subprocess.Popen([sys.executable, "-m", "rtvla.vla_server", ADDR], cwd=os.path.join(ROOT, "py"),
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                           env=dict(os.environ, TORCH_THREADS="1"))
    # keep the server off Rust's core
    try:
        os.sched_setaffinity(srv.pid, {1})
    except Exception:
        pass
    load_line = ""
    while True:
        line = srv.stdout.readline()
        if "loaded" in line:
            load_line = line.strip()
        if "ready" in line:
            break
    print(load_line, flush=True)
    for r in range(n):
        for kind in ("swap", "restart"):
            m = t.run_swap("swap", 200 + r) if kind == "swap" else t.run_restart(200 + r)
            m["kind"] = kind
            m["server"] = load_line
            with open(os.path.join(RESULTS, "e8b_restart_vla_server.jsonl"), "a") as f:
                f.write(json.dumps(m) + "\n")
            print(json.dumps(m), flush=True)
    srv.kill()
