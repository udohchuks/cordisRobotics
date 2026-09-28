"""Paper figure: frames from the single demo run over its event timeline."""
import json, os, sys
import numpy as np, mujoco
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."); D = os.path.join(ROOT, "results_mj", "demo")
run = json.load(open(os.path.join(D, "run.json"))); tab = json.load(open(os.path.join(D, "table.json")))
z = np.load(os.path.join(D, "plant.npz")); L = z["log"]; C = list(z["cols"])
t0 = run["t0_monotonic"]; pt = L[:, C.index("wall")] + float(z["t0_perf"]) - t0
m = mujoco.MjModel.from_xml_path(os.path.join(ROOT, "sim", "mujoco", "scene.xml")); d = mujoco.MjData(m)
ca = m.jnt_qposadr[mujoco.mj_name2id(m, 3, "cube")]; ba = m.jnt_qposadr[mujoco.mj_name2id(m, 3, "bowl")]
r = mujoco.Renderer(m, 300, 360); cam = mujoco.MjvCamera(); cam.lookat[:] = [0.2, -0.01, 0.04]; cam.distance = 0.55; cam.azimuth = 150; cam.elevation = -28
def frame(t):
    i = int(np.searchsorted(pt, t))
    d.qpos[:6] = L[i, C.index("q0"):C.index("q0") + 6]; d.qpos[ba:ba + 3] = L[i, C.index("bx"):C.index("bx") + 3]
    d.qpos[ca:ca + 7] = L[i, C.index("cx"):C.index("cx") + 7]; mujoco.mj_forward(m, d); r.update_scene(d, camera=cam); return r.render()
ko = run["keepout"][0]
marks = {mk["event"]: mk["t"] for mk in run["marks"]}
eps = run["episodes"][:-1]
shots = [(eps[0]["start"] + 2.6, "(a) v1: grasp misses\n(planted 3 cm aim bug)"),
         (eps[2]["start"] + 2.4, "(b) fix v2 live:\ngrasp"),
         (eps[2]["start"] + 4.9, "(c) cube placed\nin bowl"),
         (ko["t"] + 0.03, f"(d) bad repair halted\n{ko['dist']*1000:.0f} mm from bowl"),
         (eps[8]["start"] + 3.8, "(e) task continues\non v2, no reset")]
fig = plt.figure(figsize=(7.0, 2.9))
gs = fig.add_gridspec(2, 5, height_ratios=[1.2, 1.0], hspace=0.12, wspace=0.04)
for j, (t, lab) in enumerate(shots):
    ax = fig.add_subplot(gs[0, j]); ax.imshow(frame(t)); ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(lab, fontsize=6.3, pad=2)
    for s in ax.spines.values(): s.set_linewidth(0.5); s.set_color("#999")
ax = fig.add_subplot(gs[1, :])
INK, MUTED = "#222", "#777"
for e in eps:
    col = "#2f6fb0" if e["ok"] else "#ffffff"
    ax.add_patch(Rectangle((e["start"], 0.62), e["end"] - e["start"] - 0.25, 0.3, facecolor=col, edgecolor="#2f6fb0", lw=0.8,
                           hatch=None if e["ok"] else "////"))
    lab = f"v{e['version']}" if e["version"] != 3 else "v3→v2"
    ax.text(e["start"] + (e["end"] - e["start"]) / 2, 0.77, lab, ha="center", va="center", fontsize=5.5,
            color="white" if e["ok"] else INK)
dist = L[:, C.index("dist")] * 100
ax.plot(pt, 0.05 + np.clip(dist, 0, 12) / 12 * 0.45, color=MUTED, lw=0.8)
ax.axhline(0.05 + 3 / 12 * 0.45, color=MUTED, lw=0.6, ls=":")
ax.text(60.6, 0.05 + 3 / 12 * 0.45 - 0.04, "3 cm keep-out", fontsize=5.5, va="center", color=MUTED)
ax.text(60.6, 0.40, "gripper-bowl\ndistance", fontsize=5.5, va="center", color=MUTED)
ev = [(marks["B_fix_arrives"], "fix arrives\n(live in 3 ms)"), (marks["B_fix_done"], "kept after\n3/3 trial"),
      (marks["C_nan_arrives"], "NaN repair:\nRust rejects,\nrolled back\nin 0.2 s"),
      (marks["D_bowl_arrives"], "bowl-bound repair:\nhalt + rollback 0.4 s")]
for i, (t, lab) in enumerate(ev):
    ax.axvline(t, color=INK, lw=0.6, ymin=0.0, ymax=(0.98 + (0.0 if i % 2 == 0 else 0.3)) / 1.75)
    ax.text(t + 0.3, 0.98 + (0.0 if i % 2 == 0 else 0.3), lab, fontsize=5.5, va="bottom", color=INK)
ax.set_xlim(0, 60); ax.set_ylim(0, 1.75); ax.set_yticks([])
ax.set_xlabel("time in one continuous run (s)", fontsize=6.5); ax.tick_params(labelsize=6)
for s in ("top", "right", "left"): ax.spines[s].set_visible(False)
ax.text(0.2, 0.95, "episodes (filled = success,\nhatched = failure)", fontsize=5.5, color=INK, va="bottom")
fig.savefig(os.path.join(ROOT, "paper", "fig_mujoco_demo.pdf"), bbox_inches="tight", pad_inches=0.02)
fig.savefig(os.path.join(D, "fig_mujoco_demo.png"), bbox_inches="tight", pad_inches=0.02, dpi=220)
