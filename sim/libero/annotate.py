"""Make a watchable video of a run: the plant's camera video with a caption bar
showing what the program is doing (skill, VLA instruction, batch/trial events,
safety halts) at each step.  usage: annotate.py <run_dir>"""
import json
import os
import sys

import imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

run = sys.argv[1]
pl = np.load(os.path.join(run, "plant.npz"))
walls = pl["wall"]
meta = json.load(open(os.path.join(run, "meta.json")))
evs = [json.loads(l) for l in open(os.path.join(run, "events.jsonl"))]
swaps = [json.loads(l) for l in open(os.path.join(run, "swaps.jsonl"))]
vla_instr = {}
for f in sorted(x for x in os.listdir(os.path.join(run, "plugins")) if x.endswith(".py")):
    src = open(os.path.join(run, "plugins", f)).read()
    import re
    for m in re.finditer(r"class (\w+)\(VLASkill\):.*?INSTRUCTION\s*=\s*['\"](.*?)['\"]", src, re.S):
        vla_instr[m.group(1)] = m.group(2)

# timeline of (wall, text) for the "doing" line and a list of banner events
doing, banners = [], []
for e in evs:
    if e.get("ev") != "rt":
        continue
    k, n = e["kind"], e["node"]
    if k == "start":
        doing.append((e["wall"], f"{n} v{e['version']}"))
    elif k in ("success", "failure", "halt"):
        doing.append((e["wall"], f"{n}: {k}"))
    elif k == "safety_halt":
        banners.append((e["wall"], "SAFETY HALT (hot stove) - Rust dropped the skill's commands", (200, 40, 40)))
    elif k == "error":
        banners.append((e["wall"], f"ERROR in {n}", (200, 40, 40)))
for s in swaps:
    if s["ev"] == "live":
        banners.append((s["wall"], f"new batch {s['n']} live (no restart)", (40, 110, 200)))
    elif s["ev"] == "trial_done":
        col = (40, 150, 60) if s["result"] == "kept" else (200, 120, 20)
        banners.append((s["wall"], f"batch {s['n']} {s['result'].replace('_', ' ')}", col))
    elif s["ev"] == "batch" and s.get("load_error"):
        banners.append((s["wall"], f"batch {s['n']} rejected at load", (200, 120, 20)))
agent = [json.loads(l) for l in open(os.path.join(run, "agent_calls.jsonl"))]
for a in agent:
    banners.append((a["wall"], f"agent reply {a['call']} ({a['latency']:.0f} s)", (110, 60, 160)))
doing.sort(); banners.sort()
t0 = meta["t_start"]

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
except OSError:
    font = ImageFont.load_default()

rd = imageio.get_reader(os.path.join(run, "video.mp4"))
wr = imageio.get_writer(os.path.join(run, "video_annotated.mp4"), fps=20, codec="libx264", quality=6, macro_block_size=8)
di = bi = 0
cur = ""
for i, fr in enumerate(rd):
    if i >= len(walls):
        break
    w = walls[i]
    while di < len(doing) and doing[di][0] <= w:
        cur = doing[di][1]; di += 1
    while bi < len(banners) and banners[bi][0] < w - 6:
        bi += 1
    act = [b for b in banners[bi:bi + 4] if b[0] <= w and b[0] > w - 6]
    img = Image.new("RGB", (fr.shape[1], fr.shape[0] + 64), (20, 20, 20))
    img.paste(Image.fromarray(fr), (0, 64))
    d = ImageDraw.Draw(img)
    d.text((6, 4), f"t = {w - t0:6.0f} s (wall)   step {i + 1}", fill=(230, 230, 230), font=font)
    d.text((6, 22), f"doing: {cur}", fill=(255, 230, 120), font=font)
    if act:
        b = act[-1]
        d.rectangle([0, 42, fr.shape[1], 62], fill=b[2])
        d.text((6, 44), b[1], fill=(255, 255, 255), font=font)
    wr.append_data(np.asarray(img))
wr.close()
print("wrote", os.path.join(run, "video_annotated.mp4"))
