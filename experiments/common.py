import csv
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "py"))
LIVE = os.environ.get("RTVLA_LIVE", os.path.join(ROOT, "rust", "target", "release", "live"))
RESULTS = os.environ.get("RTVLA_RESULTS", os.path.join(ROOT, "results"))
os.makedirs(RESULTS, exist_ok=True)

from rtvla.shm import Shm  # noqa: E402


def start_rust(duration, log, rt=True, create=True):
    if create:
        Shm(create=True)
    cmd = [LIVE, "--layout", os.path.join(ROOT, "layout.json"), "--duration", str(duration), "--log", log,
           "--shm", os.environ.get("RTVLA_SHM", "/dev/shm/rtvla.shm")]
    if rt:  # pin to core 0 at real-time priority when allowed
        cmd = ["chrt", "-f", "50", "taskset", "-c", "0"] + cmd
    p = subprocess.Popen(cmd, stderr=subprocess.DEVNULL if rt else None)
    time.sleep(0.3)
    if p.poll() is not None and rt:
        return start_rust(duration, log, rt=False, create=create)
    return p


def pin_python():
    try:
        os.sched_setaffinity(0, {1})
    except Exception:
        pass


def read_ticks(log):
    with open(log) as f:
        return list(csv.DictReader(f))


def tick_metrics(rows, period_us=33000):
    late = [int(r["late_us"]) for r in rows]
    w = [int(r["write_us"]) for r in rows]
    gaps = [b - a for a, b in zip(w, w[1:])]
    missed = sum(1 for x in late if x > period_us)
    holds = sum(1 for r in rows if r["reason"] in ("2", "3", "4", "6"))
    late_sorted = sorted(late)
    return {"ticks": len(rows), "missed": missed,
            "late_p50_ms": late_sorted[len(late) // 2] / 1000,
            "late_p99_ms": late_sorted[int(len(late) * 0.99)] / 1000,
            "late_max_ms": max(late) / 1000, "max_gap_ms": max(gaps) / 1000,
            "hold_ticks": holds,
            "gaps_over_1_tick": sum(1 for g in gaps if g > 2 * period_us)}
