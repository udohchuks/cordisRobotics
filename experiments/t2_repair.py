"""T2: live repair (Cordis swap) vs restart, plus bad repairs that must roll back.

Every run starts from approach v1 (planted 3 cm aim bug). After 2 episodes
the repair is 'ready'. Downtimes are read from Rust's tick log.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, read_ticks, RESULTS, ROOT, Shm  # noqa: E402

PY = sys.executable
RUNNER = os.path.join(ROOT, "experiments", "run_runtime.py")
TICK_MS = 33


def window_metrics(rows, tick_ready, v2_node=102):
    rows = [r for r in rows if int(r["tick"]) >= tick_ready]
    w = [int(r["write_us"]) for r in rows]
    gaps = [b - a for a, b in zip(w, w[1:])]
    first_v2 = next((int(r["tick"]) for r in rows if r["node"] == str(v2_node) and r["step"] != "-1"), None)
    s0 = int(rows[0]["successes"])
    first_succ = next((int(r["tick"]) for r in rows if int(r["successes"]) > s0), None)
    return {"missed": sum(1 for r in rows if int(r["late_us"]) > TICK_MS * 1000),
            "gaps_over_1_tick": sum(1 for g in gaps if g > 2 * TICK_MS * 1000),
            "max_gap_ms": max(gaps) / 1000,
            "ms_to_first_fixed_chunk": None if first_v2 is None else (first_v2 - tick_ready) * TICK_MS,
            "ms_to_first_success": None if first_succ is None else (first_succ - tick_ready) * TICK_MS,
            "hold_ticks": sum(1 for r in rows if r["reason"] in ("2", "3", "4"))}


def run_swap(kind, r):
    target = {"swap": "v2", "bad_load": "v2_bad_load", "bad_trial": "v2_bad_trial"}[kind]
    log, out = f"/tmp/t2_{kind}_{r}.csv", f"/tmp/t2_{kind}_{r}.json"
    rust = start_rust(float(os.environ.get("RTVLA_RUST_S", "150")), log)
    eps = 2 + (3 if kind != "bad_load" else 2)
    subprocess.run([PY, RUNNER, "--approach", "v1", "--episodes", str(eps), "--seconds", "85",
                    "--swap_after", "2", "--swap_to", target, "--trial_k", "3", "--out", out])
    Shm().write_command(quit=1)
    rust.wait()
    o = json.load(open(out))
    sw = o["swap"]
    m = window_metrics(read_ticks(log), sw["tick_ready"])
    m["plugins_reloaded"] = 1
    m["result"] = sw.get("result", sw.get("load_state"))
    if "hash_before" in sw:
        m["state_preserved"] = sw["hash_before"] == sw["hash_after"]
        m["ms_waiting_for_idle"] = round((sw["t_idle"] - sw["t_ready"]) * 1000)
    m["identical_after"] = sw["fingerprint_before"] == sw["fingerprint_after"] if kind != "swap" else None
    after = [e for e in o["episodes"] if e["start"] > sw["t_ready"]]
    m["episodes_after"] = [(e["v"], e["ok"]) for e in after]
    return m


def run_restart(r, fix="v2"):
    log, h1, h2, out = f"/tmp/t2_restart_{r}.csv", "/tmp/t2_h1.json", "/tmp/t2_h2.json", f"/tmp/t2_restart_{r}.json"
    for h in (h1, h2):
        if os.path.exists(h):
            os.remove(h)
    rust = start_rust(float(os.environ.get("RTVLA_RUST_S", "150")), log)
    p1 = subprocess.Popen([PY, RUNNER, "--approach", "v1", "--episodes", "1000", "--seconds", "80",
                           "--hash_file", h1, "--out", "/tmp/t2_p1.json"])
    while True:
        time.sleep(0.05)
        try:
            h = json.load(open(h1))
        except Exception:
            continue
        if h["episodes"] >= 2:
            break
    shm = Shm()
    tick_ready = shm.read_state()["tick"]
    before = json.load(open(h1))
    p1.kill()                                   # restart: kill everything in Python...
    p1.wait()
    if os.path.exists(out):
        os.remove(out)
    subprocess.run([PY, RUNNER, "--approach", fix, "--episodes", "3", "--seconds", "60",
                    "--hash_file", h2, "--out", out],
                   stderr=subprocess.DEVNULL)          # ...and start again with the fix
    shm.write_command(quit=1)
    rust.wait()
    m = window_metrics(read_ticks(log), tick_ready)
    m["plugins_reloaded"] = 2          # every plugin: basics (9 nodes) + approach
    if os.path.exists(h2):
        m["result"] = "restarted"
        m["state_preserved"] = before["hash"] == json.load(open(h2))["hash"]
        m["episodes_after"] = [(e["v"], e["ok"]) for e in json.load(open(out))["episodes"]]
    else:
        m["result"] = "runtime_failed_to_start"
        m["state_preserved"] = False
        m["episodes_after"] = []
    return m


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    kinds = sys.argv[2].split(",") if len(sys.argv) > 2 else ["restart", "swap", "bad_load", "bad_trial", "restart_bad_load"]
    path = os.path.join(RESULTS, "t2.json")
    res = json.load(open(path)) if os.path.exists(path) else {}
    for kind in kinds:
        res[kind] = []
        for r in range(runs):
            if kind == "restart":
                m = run_restart(r)
            elif kind == "restart_bad_load":
                m = run_restart(r, fix="v2_bad_load")
            else:
                m = run_swap(kind, r)
            res[kind].append(m)
            print(kind, r, json.dumps(m), flush=True)
            json.dump(res, open(path, "w"), indent=1)
