"""Numbers for the paper table, all from the single demo run's logs."""
import csv, json, math, os
import numpy as np
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results_mj", "demo")
run = json.load(open(os.path.join(D, "run.json")))
rows = list(csv.DictReader(open(os.path.join(D, "ticks.csv"))))
z = np.load(os.path.join(D, "plant.npz")); L = z["log"]; C = list(z["cols"]); col = lambda n: L[:, C.index(n)]
t0 = run["t0_monotonic"]
mono = np.array([int(r["mono_us"]) for r in rows]) / 1e6 - t0       # Rust tick times on the run clock
tick = np.array([int(r["tick"]) for r in rows])
plant_t = col("wall") + float(z["t0_perf"]) - t0                     # perf_counter == CLOCK_MONOTONIC on Linux
sw = {k: json.load(open(os.path.join(D, f"swap_{k}.json"))) for k in ("B_fix", "C_nan", "D_bowl")}
out = {}
# --- timing
late = [int(r["late_us"]) for r in rows]
out["ticks"] = len(rows); out["late_ticks"] = sum(1 for x in late if x > 33000)
out["late_p99_ms"] = sorted(late)[int(0.99 * len(late))] / 1000
out["plant_rtf"] = float(col("t")[-1] / col("wall")[-1]); out["plant_lag_steps"] = int(z["lag_steps"])
# --- episodes (the last one was cut by the end of the run)
eps = run["episodes"][:-1]
out["episodes"] = [(round(e["start"], 1), e["version"], e["ok"]) for e in eps]
# --- B: live fix
b = sw["B_fix"]
out["B"] = dict(result=b["result"], trial=b["trial"], arrival_to_live_ms=(b["t_live"] - b["t_ready"]) * 1000,
                load_to_idle_ms=(b["t_idle"] - b["t_ready"]) * 1000, idle_to_live_ms=(b["t_live"] - b["t_idle"]) * 1000)
# --- C: NaN repair, bad steps that reached the arm
c = sw["C_nan"]
sent = run["sent"]   # (t, chunk id, token, node, start, n, tick)
c_ids = {s[1] for s in sent if c["t_live"] <= s[0] <= c["t_done"] and s[3] == "approach"}
played_bad = sum(1 for r in rows if int(r["chunk"]) in c_ids and int(r["step"]) >= 0)
rej = max(int(r["rej_bad"]) for r in rows)
out["C"] = dict(result=c["result"], reason=c["early_reject"], arrival_to_rolled_back_ms=(c["t_done"] - c["t_ready"]) * 1000,
                chunks_sent_by_bad_version=len(c_ids), chunks_rejected_by_rust=rej, bad_steps_played=played_bad,
                nan_in_plant_ctrl=bool(np.isnan(L[:, C.index("c0"):C.index("c0") + 6]).any()),
                fingerprint_equal=c["fingerprint_equal_after"])
# --- D: keep-out halt
d = sw["D_bowl"]; ko = run["keepout"][0]
hs = ko["halt_seq"]; t_issue = ko["t"]
k_ack = next(i for i, r in enumerate(rows) if int(r["halt_ack"]) >= hs and mono[i] >= t_issue - 0.001)
d_ids = {s[1] for s in sent if d["t_live"] <= s[0] <= ko["t"] + 0.5 and s[2] == ko["token"]}
played_after_ack = sum(1 for i, r in enumerate(rows) if i >= k_ack and int(r["chunk"]) in d_ids and int(r["step"]) >= 0)
c_arm = L[:, C.index("c0"):C.index("c0") + 5]
v_cmd = np.linalg.norm(np.gradient(c_arm, 0.002, axis=0), axis=1)
q_arm = L[:, C.index("q0"):C.index("q0") + 5]; v_meas = np.linalg.norm(np.gradient(q_arm, 0.002, axis=0), axis=1)
i_issue = int(np.searchsorted(plant_t, t_issue))
# the next run (rolled-back v2) takes over at the first Rust tick that plays a
# chunk with a newer token; the stop is measured only up to that point
k_res = next(i for i, r in enumerate(rows) if mono[i] > t_issue and int(r["token"]) > ko["token"] and int(r["step"]) >= 0)
i_res = int(np.searchsorted(plant_t, mono[k_res]))
stop = next((i for i in range(i_issue, i_res) if v_meas[i] < 0.02), None)
out_resume_ms = (mono[k_res] - t_issue) * 1000
v_min_before_resume = float(v_meas[i_issue:i_res].min())
tip = np.stack([col("tx"), col("ty"), col("tz")], 1)
win = slice(i_issue, i_issue + 1500)
out["D"] = dict(result=d["result"], reason=d["early_reject"], dist_at_trigger_mm=ko["dist"] * 1000,
                ack_ticks_after_issue=int(tick[k_ack] - tick[np.searchsorted(mono, t_issue)]),
                ack_ms_after_issue=(mono[k_ack] - t_issue) * 1000,
                halted_steps_played_after_ack=played_after_ack,
                tip_speed_at_issue_mps=float(np.linalg.norm(tip[i_issue] - tip[i_issue - 10]) / 0.02),
                stop_ms_after_issue=(stop - i_issue) * 2.0 if stop else None,
                travel_after_issue_mm=float(np.linalg.norm(np.diff(tip[i_issue:stop + 1], axis=0), axis=1).sum() * 1000) if stop else None,
                next_run_first_step_ms=out_resume_ms, min_joint_speed_before_next_run=v_min_before_resume,
                min_clearance_mm=float(col("dist")[win].min() * 1000), bowl_peak_force_N=float(col("fbowl").max()),
                arrival_to_rolled_back_ms=(d["t_done"] - d["t_ready"]) * 1000, fingerprint_equal=d["fingerprint_equal_after"])
out["keepout_fires_total"] = len(run["keepout"])
out["min_gripper_bowl_dist_whole_run_mm"] = float(col("dist").min() * 1000)
json.dump(out, open(os.path.join(D, "table.json"), "w"), indent=1)
print(json.dumps(out, indent=1))
