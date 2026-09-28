"""Helpers for Route 1 runs: start plant + Rust, read the plant slot."""
import json, os, struct, subprocess, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "py")); sys.path.insert(0, HERE)
from rtvla.shm import Shm  # noqa: E402
LIVE_MJ = os.path.join(ROOT, "rust", "target", "release", "live_mj")
ENV = dict(os.environ, MUJOCO_GL="osmesa", PYOPENGL_PLATFORM="osmesa")


def start(q0, duration, tag, plant_args=(), rt=True):
    shm = Shm(create=True)
    pl_out = f"/tmp/mj_{tag}_plant.npz"; rs_log = f"/tmp/mj_{tag}_ticks.csv"
    pc = ["taskset", "-c", "1", sys.executable, os.path.join(HERE, "plant.py"), "--q0=" + ",".join(map(str, q0)),
          "--out", pl_out, "--max_s", str(duration + 10)] + list(plant_args)
    plant = subprocess.Popen(pc, env=ENV, stderr=subprocess.PIPE, text=True)
    while struct.unpack_from("<Q", shm.mv, shm.L["plant"]["p_seq"]["offset"])[0] == 0:
        if plant.poll() is not None:
            raise RuntimeError(plant.stderr.read())
        time.sleep(0.005)
    rc = [LIVE_MJ, "--layout", os.path.join(ROOT, "layout.json"), "--duration", str(duration), "--log", rs_log]
    if rt:
        rc = ["chrt", "-f", "50", "taskset", "-c", "0"] + rc
    rust = subprocess.Popen(rc, stderr=subprocess.DEVNULL)
    time.sleep(0.2)
    if rust.poll() is not None:
        rust = subprocess.Popen(["taskset", "-c", "0"] + rc[4:] if rt else rc, stderr=subprocess.DEVNULL)
    return shm, plant, rust, pl_out, rs_log


def plant_read(shm):
    P = shm.L["plant"]
    for _ in range(5):
        s1 = struct.unpack_from("<Q", shm.mv, P["p_seq"]["offset"])[0]
        if s1 % 2:
            continue
        r = {"step": struct.unpack_from("<Q", shm.mv, P["p_step"]["offset"])[0],
             "dist": struct.unpack_from("<d", shm.mv, P["p_dist"]["offset"])[0],
             "force": struct.unpack_from("<d", shm.mv, P["p_force"]["offset"])[0],
             "q": struct.unpack_from("<6d", shm.mv, P["p_qpos"]["offset"]),
             "tip": struct.unpack_from("<3d", shm.mv, P["p_tip"]["offset"])}
        if struct.unpack_from("<Q", shm.mv, P["p_seq"]["offset"])[0] == s1:
            return r
    return None


def load_plant(path):
    z = np.load(path)
    cols = list(z["cols"]); log = z["log"]
    return {c: log[:, i] for i, c in enumerate(cols)}, z
