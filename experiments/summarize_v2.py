"""Collect the final-code results (results_v2 = machine A, results_pc_v2 = machine B)."""
import json
import os
import statistics as st
import sys
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(__file__), "..")


def jl(p):
    p = os.path.join(ROOT, p)
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def med(x):
    return st.median(x) if x else None


out = {}
for m, R in (("A", "results_v2"), ("B", "results_pc_v2")):
    o = out[m] = {}
    g = defaultdict(list)
    for d in jl(f"{R}/t1.jsonl"):
        if d.get("who", "ours") == "ours":
            g[d["cond"]].append(d)
    o["t1"] = {c: {"runs": len(v), "ticks": sum(x["ticks"] for x in v), "late": sum(x["missed"] for x in v),
                   "max_gap_ms": max(x["max_gap_ms"] for x in v),
                   "py_silent_ms": max((x.get("py_max_gap_ms") or 0) for x in v),
                   "episodes_ok": [x.get("episodes_ok") for x in v]} for c, v in g.items()}
    if g:
        o["t1_total"] = {"ticks": sum(x["ticks"] for v in g.values() for x in v),
                         "late": sum(x["missed"] for v in g.values() for x in v),
                         "max_gap_ms": max(x["max_gap_ms"] for v in g.values() for x in v)}
    g = defaultdict(list)
    for d in jl(f"{R}/t2.jsonl"):
        g[d["kind"]].append(d)
    o["t2"] = {k: {"n": len(v), "late": sum(x["missed"] for x in v), "max_gap_ms": max(x["max_gap_ms"] for x in v),
                   "fix_live_ms_median": med([x["ms_to_first_fixed_chunk"] for x in v if x["ms_to_first_fixed_chunk"] is not None]),
                   "results": {r: [x["result"] for x in v].count(r) for r in set(x["result"] for x in v)},
                   "identical": sum(1 for x in v if x.get("identical_after")),
                   "state_preserved": sum(1 for x in v if x.get("state_preserved")),
                   "after_ok": f'{sum(1 for x in v for e in x["episodes_after"] if e[1])}/{sum(len(x["episodes_after"]) for x in v)}'}
               for k, v in g.items()}
    t4 = jl(f"{R}/t4.jsonl")
    if t4:
        w = [x["ms_waiting_for_idle"] for x in t4]
        o["t4"] = {"n": len(t4), "wait_ms": [min(w), med(w), max(w)], "kept": [x["result"] for x in t4].count("kept"),
                   "state_unchanged": sum(x["state_unchanged"] for x in t4), "late": sum(x["missed"] for x in t4),
                   "max_hand_step_mm": max(x["max_hand_step_mm"] for x in t4), "mismatch": sum(x["mismatch_flags"] for x in t4),
                   "after_ok": f'{sum(1 for x in t4 for e in x["episodes_after"] if e[1])}/{sum(len(x["episodes_after"]) for x in t4)}'}
    o["t6h"] = jl(f"{R}/t6h.jsonl")
    p = os.path.join(ROOT, R, "t3.json")
    if os.path.exists(p):
        o["t3"] = json.load(open(p))
    ro = jl(f"{R}/rust_only.jsonl")
    if ro:
        o["rust_only"] = ro[-1]

A = out["A"]
g = defaultdict(list)
for d in jl("results_v2/e7.jsonl"):
    g[d["cls"]].append(d)
A["e7"] = {c: {"n": len(v), "results": {r: [x["result"] for x in v].count(r) for r in set(x["result"] for x in v)},
               "identical": sum(x["identical_after"] for x in v), "late": sum(x["late"] for x in v),
               "max_gap_ms": max(x["max_gap_ms"] for x in v), "ticks": sum(x["ticks"] for x in v),
               "max_step_mm": max(x["max_step_mm"] for x in v), "pose_finite": all(x["pose_finite"] for x in v),
               "in_ws": all(x["in_workspace"] for x in v), "dead_token_steps": sum(x["dead_token_steps"] for x in v),
               "watchdog": sum(x["watchdog_fired"] for x in v), "rejected_bad": sum(x["rejected_bad"] for x in v),
               "inbox_rejected": sum(x["inbox_rejected"] for x in v),
               "after_ok": f'{sum(sum(x["after_ok"]) for x in v)}/{sum(len(x["after_ok"]) for x in v)}',
               "fp_diff_example": next((x["fp_diff"] for x in v if not x["identical_after"]), None)} for c, v in g.items()}
g = defaultdict(list)
for d in jl("results_v2/e7_naive.jsonl"):
    g[d["cls"]].append(d)
A["e7_naive"] = {c: {"n": len(v), "results": {r: [x["result"] for x in v].count(r) for r in set(x["result"] for x in v)},
                     "identical": sum(x["identical_after"] for x in v), "late": sum(x["late"] for x in v),
                     "dead_token_steps": sum(x["dead_token_steps"] for x in v),
                     "after_ok": f'{sum(sum(x["after_ok"]) for x in v)}/{sum(len(x["after_ok"]) for x in v)}',
                     "fp_diff_example": next((x["fp_diff"] for x in v if not x["identical_after"]), None)} for c, v in g.items()}
e8 = jl("results_v2/e8_restart_vla.jsonl")
if e8:
    A["e8"] = {k: {"n": len([x for x in e8 if x["kind"] == k]),
                   "fix_live_ms": sorted(x["ms_to_first_fixed_chunk"] for x in e8 if x["kind"] == k and x["ms_to_first_fixed_chunk"] is not None),
                   "late": sum(x["missed"] for x in e8 if x["kind"] == k),
                   "max_gap_ms": max(x["max_gap_ms"] for x in e8 if x["kind"] == k),
                   "results": [x["result"] for x in e8 if x["kind"] == k]} for k in ("swap", "restart")}
e9 = jl("results_v2/e9.jsonl")
if e9:
    g = defaultdict(list)
    for d in e9:
        g[d["bug"]].append(d)
    A["e9"] = {b: {"n": len(v), "fixed": sum(x["fixed"] for x in v),
                   "attempts": [len(x["attempts"]) for x in v],
                   "attempt_results": [[a["result"] for a in x["attempts"]] for x in v],
                   "llm_s": [a["llm_s"] for x in v for a in x["attempts"]],
                   "s_report_to_fix": [x["s_report_to_fix"] for x in v],
                   "late": sum(x["late"] for x in v), "ticks": sum(x["ticks"] for x in v),
                   "max_gap_ms": max(x["max_gap_ms"] for x in v),
                   "after_ok": f'{sum(sum(x["after_ok"]) for x in v)}/{sum(len(x["after_ok"]) for x in v)}'} for b, v in g.items()}
json.dump(out, open(os.path.join(ROOT, "results_v2", "summary_v2.json"), "w"), indent=1)
if len(sys.argv) > 1:
    print(json.dumps(out[sys.argv[1]].get(sys.argv[2]) if len(sys.argv) > 2 else out[sys.argv[1]], indent=1))
