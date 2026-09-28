"""Figure: one agent-repair session. Top: episodes (red failed, green succeeded)
and the agent's work; bottom: gap between Rust commands, which stays at 33 ms.
usage: fig_agent.py <bug> <run>
"""
import csv
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

matplotlib.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42, "font.family": "Liberation Sans",
                            "font.size": 6.5, "axes.linewidth": 0.6})
ROOT = os.path.join(os.path.dirname(__file__), "..")
bug, run = sys.argv[1], sys.argv[2]
d = json.load(open(os.path.join(ROOT, "results_v2", "e9_transcripts", f"{bug}_{run}.json")))
rows = list(csv.DictReader(open(f"/tmp/e9_{bug}_{run}.csv")))
a0 = d["attempts"][0]
# align Python time to Rust ticks with the (time, tick) pair taken at the first agent call
T0, K0 = a0["t_llm_start"], a0["tick_llm_start"]


def tk(t):          # python monotonic -> seconds on Rust's clock
    return K0 * 0.033 + (t - T0)


t = [int(r["write_us"]) / 1e6 for r in rows[1:]]
gap = [(int(b["write_us"]) - int(a["write_us"])) / 1000 for a, b in zip(rows, rows[1:])]
t_end = tk(d["episode_times"][-1][1]) + 1
fig, (a1, a2) = plt.subplots(2, 1, sharex=True, figsize=(3.3, 1.45),
                             gridspec_kw=dict(height_ratios=[1.1, 1], hspace=0.15))
for s, e, ok, v in d["episode_times"]:
    a1.barh(0, tk(e) - tk(s) - 0.15, left=tk(s), height=0.55, color="#2E8B57" if ok else "#C0392B", lw=0)
for a in d["attempts"]:
    a1.axvspan(tk(a["t_llm_start"]), tk(a["t_llm_end"]), ymin=0.72, ymax=0.95, color="#7F8C8D", lw=0)
    a1.text((tk(a["t_llm_start"]) + tk(a["t_llm_end"])) / 2, 0.635, "agent writes fix", fontsize=5.5,
            color="white", ha="center", va="center")
    if a.get("t_live"):
        a1.plot([tk(a["t_live"])] * 2, [-0.45, 0.45], color="k", lw=0.9)
    lab = {"kept": "fix live, then kept", "rolled_back": "fix live, rolled back",
           "FAILED": "load failed"}.get(a["result"], a["result"])
    if a.get("t_live"):
        a1.text(tk(a["t_live"]) + 0.6, -0.5, lab, fontsize=5.5, color="0.2", va="top", ha="left")
a1.set_ylim(-0.95, 0.95)
a1.set_yticks([])
a1.set_ylabel("episodes", fontsize=6)
a2.plot(t, gap, color="#1F4E79", lw=0.8)
a2.axhline(33, ls=":", lw=0.6, c="0.5")
a2.set_ylim(0, 100)
a2.set_yticks([0, 33, 100])
a2.set_ylabel("command\ngap (ms)", fontsize=6)
a2.set_xlabel("time (s)", fontsize=6.5)
a2.set_xlim(0, t_end)
for a in (a1, a2):
    a.spines[["top", "right"]].set_visible(False)
    a.tick_params(labelsize=6, width=0.6, length=2.5)
fig.align_ylabels((a1, a2))
fig.savefig(os.path.join(ROOT, "paper", "fig_agent.pdf"), bbox_inches="tight", pad_inches=0.02)
print("attempts", [(a["result"], a["llm_s"]) for a in d["attempts"]], "max gap", max(gap))
