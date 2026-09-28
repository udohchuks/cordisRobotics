"""Figure: during a GIL-holding call (~1.3 s), Python goes silent but Rust keeps commanding.

Top: time since Rust last saw a Python heartbeat. Bottom: gap between Rust commands.
Data: Rust's own tick log from T1, condition gil_1s, run 0.
"""
import csv

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager
import matplotlib.pyplot as plt

matplotlib.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42, "font.family": "Liberation Sans",
                            "font.size": 6.5, "axes.linewidth": 0.6})

rows = list(csv.DictReader(open("/tmp/t1_gil_1s_0.csv")))
t = [int(r["write_us"]) / 1e6 for r in rows[1:]]
gap = [(int(b["write_us"]) - int(a["write_us"])) / 1000 for a, b in zip(rows, rows[1:])]
stale = [int(r["hb_stale"]) * 0.033 for r in rows[1:]]

# the longest silence that ends (Python resumed), not the tail after the runtime exits
ends = [k for k in range(1, len(stale)) if stale[k] == 0 and stale[k - 1] > 0]
i = max(ends, key=lambda k: stale[k - 1]) - 1
start = i
while start > 0 and stale[start - 1] > 0:
    start -= 1
lo, hi = max(0, start - 15), min(len(t), i + 45)
x0 = t[lo]
x = [v - x0 for v in t[lo:hi]]

fig, (a1, a2) = plt.subplots(2, 1, sharex=True, figsize=(3.3, 1.35),
                             gridspec_kw=dict(height_ratios=[1.25, 1], hspace=0.18))
for a in (a1, a2):
    a.axvspan(t[start] - x0, t[i] - x0, color="0.92", lw=0)
    a.spines[["top", "right"]].set_visible(False)
    a.tick_params(labelsize=6, width=0.6, length=2.5)
a1.plot(x, stale[lo:hi], color="#C0392B", lw=1.2)
a1.set_ylim(0, 2.0)
a1.set_yticks([0, 1.0, 2.0])
a1.set_ylabel("since last\nheartbeat (s)", fontsize=6)
a1.text((t[start] + t[i]) / 2 - x0, 1.8, "Python frozen", ha="center", va="top", fontsize=6, color="0.35")
a2.plot(x, gap[lo:hi], color="#1F4E79", lw=1.2)
a2.axhline(33, ls=":", lw=0.6, c="0.5")
a2.set_ylim(0, 100)
a2.set_yticks([0, 33, 100])
a2.set_ylabel("command\ngap (ms)", fontsize=6)
a2.set_xlabel("time (s)", fontsize=6.5)
fig.align_ylabels((a1, a2))
fig.savefig("paper/fig_gil.pdf", bbox_inches="tight", pad_inches=0.02)
print("silence s", round(stale[i], 2), "max gap in window ms", round(max(gap[lo:hi]), 1))
