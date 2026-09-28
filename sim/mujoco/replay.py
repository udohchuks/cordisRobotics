"""Render a plant log afterwards (replay), so timing runs are not disturbed."""
import os, sys
import numpy as np, mujoco, imageio
from PIL import Image, ImageDraw
HERE = os.path.dirname(os.path.abspath(__file__))


def frames(npz, cam="front", every=20, w=480, h=360, label="", mark_step=None, t_from=0.0, t_to=None):
    z = np.load(npz); cols = list(z["cols"]); L = z["log"]; C = {c: i for i, c in enumerate(cols)}
    m = mujoco.MjModel.from_xml_path(os.path.join(HERE, "scene.xml")); d = mujoco.MjData(m)
    ca = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "cube")]
    ba = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "bowl")]
    r = mujoco.Renderer(m, h, w); out = []
    for i in range(0, len(L), every):
        t = L[i, C["t"]]
        if t < t_from or (t_to and t > t_to): continue
        d.qpos[:6] = L[i, C["q0"]:C["q0"] + 6]
        d.qpos[ba:ba + 3] = L[i, C["bx"]:C["bx"] + 3]
        d.qpos[ca:ca + 7] = L[i, C["cx"]:C["cx"] + 7]
        mujoco.mj_forward(m, d); r.update_scene(d, camera=cam)
        im = Image.fromarray(r.render()); dr = ImageDraw.Draw(im)
        f = L[i, C["fbowl"]]
        txt = f"{label}  t={t:.2f}s  bowl force={f:.1f}N"
        if mark_step is not None and i >= mark_step: txt += "  HALT ISSUED"
        dr.rectangle([0, 0, w, 18], fill=(0, 0, 0)); dr.text((4, 3), txt, fill=(255, 255, 255))
        out.append(np.array(im))
    return out
