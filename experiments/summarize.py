import json, os, statistics as st
R = os.path.join(os.path.dirname(__file__), "..", "results")

def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None

def t2():
    r = json.load(open(os.path.join(R, "t2.json")))
    out = {}
    for k, v in r.items():
        ok_after = [sum(1 for e in x["episodes_after"] if e[1]) for x in v]
        out[k] = {"runs": len(v),
                  "missed_total": sum(x["missed"] for x in v),
                  "gaps_over_1_tick_total": sum(x["gaps_over_1_tick"] for x in v),
                  "max_gap_ms_max": max(x["max_gap_ms"] for x in v),
                  "ms_to_fixed_chunk_median": med([x["ms_to_first_fixed_chunk"] for x in v]),
                  "ms_to_success_median": med([x["ms_to_first_success"] for x in v]),
                  "state_preserved": sum(1 for x in v if x.get("state_preserved")),
                  "identical_after": sum(1 for x in v if x.get("identical_after")),
                  "results": {res: sum(1 for x in v if x["result"] == res) for res in set(x["result"] for x in v)},
                  "episodes_after_ok_total": sum(ok_after),
                  "episodes_after_total": sum(len(x["episodes_after"]) for x in v),
                  "plugins_reloaded": v[0]["plugins_reloaded"]}
    return out

def t1():
    p = os.path.join(R, "t1.json")
    if not os.path.exists(p):
        return None
    r = json.load(open(p))
    out = {}
    for c, v in r.items():
        o = v["ours"]
        out[c] = {"ours_ticks": sum(x["ticks"] for x in o), "ours_missed": sum(x["missed"] for x in o),
                  "ours_gaps_over_1_tick": sum(x["gaps_over_1_tick"] for x in o),
                  "ours_max_gap_ms": max(x["max_gap_ms"] for x in o),
                  "ours_late_p99_ms": max(x["late_p99_ms"] for x in o),
                  "python_max_gap_ms": max((x.get("py_max_gap_ms") or 0) for x in o),
                  "ours_episodes_ok": [x.get("episodes_ok") for x in o]}
        for b in ("sync", "threaded"):
            if b in v:
                out[c][b + "_max_gap_ms"] = v[b]["max_gap_ms"]
                out[c][b + "_gaps_over_1_tick"] = v[b]["gaps_over_1_tick"]
    return out

if __name__ == "__main__":
    s = {"t2": t2(), "t1": t1(), "t3": json.load(open(os.path.join(R, "t3.json"))),
         "t2_leak": json.load(open(os.path.join(R, "t2_leak.json")))}
    json.dump(s, open(os.path.join(R, "summary.json"), "w"), indent=1)
    print(json.dumps({"t2": s["t2"], "t1": s["t1"]}, indent=1))
