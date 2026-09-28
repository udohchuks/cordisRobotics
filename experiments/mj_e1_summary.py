import json, glob, os, collections
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
D = "results_mj/e1"
E = [json.load(open(f)) for f in glob.glob(D + "/*.json")]
E = [e for e in E if e["d_halt"] < 0.1]  # 12 cm > start distance (11.4 cm): halt fired before motion
g = collections.defaultdict(list)
for e in E:
    g[(e["cond"], e["w"], e["d_halt"])].append(e)
rows = []
for (c, w, d), es in sorted(g.items()):
    f = lambda k: [x.get(k) for x in es if x.get(k) is not None]
    mean = lambda k: float(np.mean(f(k))) if f(k) else None
    rows.append(dict(cond=c, w=w, d_cm=d * 100, n=len(es), contact=sum(x["contact"] for x in es),
                     peak_N=mean("peak_force"), impulse_Ns=mean("impulse"), bowl_mm=mean("bowl_disp_mm"),
                     min_clear_mm=mean("min_dist_mm"), travel_mm=mean("travel_after_due_mm"),
                     stop_ms=mean("stop_ms_after_due"), ack_ticks=mean("ack_ticks_after_issue"),
                     brake_ticks=mean("brake_ticks_after_due"), hold_ticks=mean("first_hold_ticks_after_due"),
                     tip_mps=mean("tip_speed_at_due"), late=sum(f("late_ticks")), rtf_min=min(f("plant_rtf"))))
json.dump(rows, open("results_mj/e1_summary.json", "w"), indent=1)
for r in rows:
    print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()})
ws = sorted({r["w"] for r in rows}); col = {"rust": "#1b7837", "pyonly": "#d6604d", "stall": "#8073ac"}
fig, ax = plt.subplots(2, len(ws), figsize=(4 * len(ws), 6), sharex=True)
ax = np.atleast_2d(ax)
for j, w in enumerate(ws):
    nh = [r for r in rows if r["cond"] == "nohalt" and r["w"] == w]
    for c in ("rust", "pyonly", "stall"):
        rr = sorted([r for r in rows if r["cond"] == c and r["w"] == w], key=lambda r: r["d_cm"])
        ax[0, j].plot([r["d_cm"] for r in rr], [r["peak_N"] for r in rr], "o-", color=col[c], label=c)
        ax[1, j].plot([r["d_cm"] for r in rr], [r["min_clear_mm"] for r in rr], "o-", color=col[c])
    if nh:
        ax[0, j].axhline(nh[0]["peak_N"], color="k", ls="--", lw=1, label="no halt")
    ax[1, j].axhline(0, color="k", lw=0.8)
    tip = np.mean([r["tip_mps"] for r in rows if r["w"] == w and r["tip_mps"]])
    ax[0, j].set_title(f"pan {w} rad/s (tip ~{tip:.2f} m/s)")
    ax[1, j].set_xlabel("halt distance (cm)")
ax[0, 0].set_ylabel("peak bowl force (N)"); ax[1, 0].set_ylabel("closest approach (mm)")
ax[0, 0].legend(frameon=False, fontsize=8)
for a in ax.flat:
    a.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig("results_mj/e1_halt.png", dpi=130)
