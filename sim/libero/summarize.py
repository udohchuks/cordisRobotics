"""Numbers and a timeline figure for one agent run.  usage: summarize.py <run_dir>"""
import csv
import json
import os
import sys
from collections import Counter

import numpy as np

run = sys.argv[1]
meta = json.load(open(os.path.join(run, "meta.json")))
t0 = meta["t_start"]
swaps = [json.loads(l) for l in open(os.path.join(run, "swaps.jsonl"))]
evs = [json.loads(l) for l in open(os.path.join(run, "events.jsonl"))]
calls = [json.loads(l) for l in open(os.path.join(run, "agent_calls.jsonl"))]
summ = json.load(open(os.path.join(run, "summary.json"))) if os.path.exists(os.path.join(run, "summary.json")) else {}

batches = [s for s in swaps if s["ev"] == "batch"]
load_fail = [s for s in batches if s.get("load_error")]
trials = [s for s in swaps if s["ev"] == "trial_done"]
res = Counter(s["result"] for s in trials)
early = Counter(s.get("reason") for s in trials if s.get("reason"))
rt = [e for e in evs if e.get("ev") == "rt"]
safety = [e for e in rt if e["kind"] == "safety_halt"]
errors = [e for e in rt if e["kind"] == "error"]
vla = summ.get("vla_calls", [])
vres = Counter(v.get("result") for v in vla)

# Rust timing
ticks = list(csv.DictReader(open(os.path.join(run, "ticks.csv")))) if os.path.exists(os.path.join(run, "ticks.csv")) else []
late = np.array([int(r["late_us"]) for r in ticks]) / 1000.0 if ticks else np.array([0.0])
period_ms = meta["tick_ms"]
pl = np.load(os.path.join(run, "plant.npz")) if os.path.exists(os.path.join(run, "plant.npz")) else None

goal_ev = [e for e in evs if e.get("ev") == "goal_reached"]
first_goal_times = {}
for s in trials:
    for k, v in (s.get("goals") or {}).items():
        if v and k not in first_goal_times:
            first_goal_times[k] = round(s["wall"] - t0)

out = {
    "duration_min": round((max(e.get("wall", t0) for e in evs) - t0) / 60, 1),
    "agent_calls": len(calls),
    "agent_latency_s": [round(float(np.median([c["latency"] for c in calls])), 1), round(float(max(c["latency"] for c in calls)), 1)] if calls else None,
    "reasoning_chars_total": sum(len(c.get("reasoning", "")) for c in calls),
    "batches_sent": len(batches),
    "batches_rejected_at_load": len(load_fail),
    "trials": dict(res),
    "early_rejects": dict(early),
    "safety_halts": len(safety),
    "plugin_errors": len(errors),
    "vla_calls": len(vla), "vla_outcomes": dict(vres),
    "vla_infer_s_median": round(float(np.median(summ.get("vla_times", [0]) or [0])), 2),
    "goal_facts_first_true_s": first_goal_times,
    "goal_reached": bool(goal_ev),
    "rust_ticks": len(ticks),
    "rust_late_ticks(>1 period)": int((late > period_ms).sum()),
    "rust_lateness_ms_p99_max": [round(float(np.percentile(late, 99)), 2), round(float(late.max()), 2)],
    "plant_steps": int(len(pl["step"])) if pl is not None else None,
    "plant_skipped_ticks": int(pl["skipped"].sum()) if pl is not None else None,
    "runtime_restarts": 0,
}
json.dump(out, open(os.path.join(run, "numbers.json"), "w"), indent=1)
print(json.dumps(out, indent=1))

# ------------------------------------------------------------ timeline figure
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(10, 2.6))
T = lambda w: (w - t0) / 60
for c in calls:
    ax.plot([T(c["wall"] - c["latency"]), T(c["wall"])], [3, 3], color="#7b4fa0", lw=6, solid_capstyle="butt")
live = {s["n"]: s for s in swaps if s["ev"] == "live"}
for s in trials:
    l = live.get(s["n"])
    if not l:
        continue
    col = "#2e8b57" if s["result"] == "kept" else ("#d9534f" if s.get("reason") else "#e8a33d")
    ax.plot([T(l["wall"]), T(s["wall"])], [2, 2], color=col, lw=6, solid_capstyle="butt")
for s in load_fail:
    ax.plot([T(s["wall"])], [2], marker="x", color="#d9534f", ms=8)
for e in safety:
    ax.plot([T(e["wall"])], [2.35], marker="v", color="#d9534f", ms=7)
for k, sec in first_goal_times.items():
    ax.axvline(sec / 60, color="#2e8b57", ls=":", lw=1)
    ax.text(sec / 60, 1.25, k.replace("put the ", "").replace("turn on the ", ""), rotation=0, fontsize=7, color="#2e8b57")
ax.set_yticks([2, 3]); ax.set_yticklabels(["program batch\n(trial)", "agent\nthinking"])
ax.set_ylim(1.0, 3.5); ax.set_xlabel("time (min)")
ax.set_title("Agent-written program versions: green kept, orange rolled back (no progress), red rolled back (misbehaved), x rejected at load", fontsize=8)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
fig.tight_layout()
fig.savefig(os.path.join(run, "timeline.png"), dpi=160)
print("wrote", os.path.join(run, "timeline.png"))
