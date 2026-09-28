"""T1: the arm never waits.

Ours: Rust loop + Python runtime running pick-and-place episodes while we
stall Python on purpose. We read Rust's own tick log.
Baselines: a single synchronous Python loop, and a threaded 33 ms Python
loop, under the same stalls; we read the times they send commands.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, read_ticks, tick_metrics, RESULTS, ROOT  # noqa: E402

PY = sys.executable
RUNNER = os.path.join(ROOT, "experiments", "run_runtime.py")

CONDITIONS = {
    "normal_0.3s": dict(approach="v2", delay=0.3, stall="sleep"),
    "vla_1s": dict(approach="v2", delay=1.0, stall="sleep"),
    "vla_2s": dict(approach="v2", delay=2.0, stall="sleep"),
    "gil_1s": dict(approach="v2", delay=1.0, stall="gil"),
    "plugin_throws": dict(approach="v2_throws", delay=0.3, stall="sleep"),
    "python_killed": dict(approach="v2", delay=0.3, stall="sleep", kill_at=0.5),
}


def ours(cond, seconds, run):
    c = CONDITIONS[cond]
    log = f"/tmp/t1_{cond}_{run}.csv"
    out = f"/tmp/t1_{cond}_{run}.json"
    rust = start_rust(seconds + 3, log)
    args = [PY, RUNNER, "--approach", c["approach"], "--delay", str(c["delay"]),
            "--stall", c["stall"], "--seconds", str(seconds), "--out", out]
    py = subprocess.Popen(args)
    if "kill_at" in c:
        time.sleep(seconds * c["kill_at"])
        py.kill()
    py.wait()
    rust.wait()
    m = tick_metrics(read_ticks(log))
    if os.path.exists(out) and "kill_at" not in c:
        m.update(json.load(open(out)))
        m["episodes_ok"] = sum(e["ok"] for e in m.pop("episodes"))
    return m


# ------------------------------------------------------------------ baselines
def fake_vla(stall, delay):
    if stall == "gil":
        re.match(r"(a+)+$", "a" * 25 + "b")
    else:
        time.sleep(delay)


def baseline_sync(cond, seconds):
    """One loop: play 50 steps, then call the VLA inline, repeat."""
    c = CONDITIONS[cond]
    sends = []
    t_end = time.monotonic() + seconds
    nxt = time.monotonic()
    step = 50
    while time.monotonic() < t_end:
        if step >= 50:
            if cond == "plugin_throws":
                break                       # an uncaught error ends the loop
            fake_vla(c["stall"], c["delay"])
            step = 0
        sends.append(time.monotonic())
        step += 1
        nxt += 0.033
        time.sleep(max(0, nxt - time.monotonic()))
        if time.monotonic() - nxt > 0.033:
            nxt = time.monotonic()
    return gaps(sends, seconds)


def baseline_threaded(cond, seconds):
    """A 33 ms control thread; VLA calls run in a worker thread."""
    c = CONDITIONS[cond]
    sends = []
    stop = [False]

    def control():
        nxt = time.monotonic()
        while not stop[0]:
            sends.append(time.monotonic())
            nxt += 0.033
            time.sleep(max(0, nxt - time.monotonic()))

    def worker():
        while not stop[0]:
            fake_vla(c["stall"], c["delay"])
            time.sleep(0.5)

    th = [threading.Thread(target=control), threading.Thread(target=worker)]
    for t in th:
        t.start()
    time.sleep(seconds)
    stop[0] = True
    for t in th:
        t.join()
    return gaps(sends, seconds)


def gaps(sends, seconds):
    g = [b - a for a, b in zip(sends, sends[1:])] or [seconds]
    expected = int(seconds / 0.033)
    return {"sends": len(sends), "expected": expected,
            "missed": sum(1 for x in g if x > 0.066) + max(0, expected - len(sends) - 5) * 0,
            "max_gap_ms": max(g) * 1000,
            "gaps_over_1_tick": sum(1 for x in g if x > 0.066)}


if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    conds = sys.argv[3].split(",") if len(sys.argv) > 3 else list(CONDITIONS)
    res = {}
    for cond in conds:
        res[cond] = {"ours": [ours(cond, seconds, r) for r in range(runs)]}
        if cond != "python_killed":
            res[cond]["sync"] = baseline_sync(cond, min(seconds, 30))
            res[cond]["threaded"] = baseline_threaded(cond, min(seconds, 30))
        print(cond, json.dumps(res[cond]))
        json.dump(res, open(os.path.join(RESULTS, "t1.json"), "w"), indent=1)
