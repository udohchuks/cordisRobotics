"""MuJoCo mode adapter: the skills keep planning in Cartesian space.

Outgoing: each chunk step [x, y, z, rx, ry, rz, grip] is turned into
[5 arm joints, gripper joint, 0] by IK (warm-started, gripper pointing
down, wrist turned to the cube's yaw) when the chunk is put in the inbox,
so the bridge thread only copies numbers. Non-finite steps stay non-finite
so Rust still rejects them.

Incoming: Rust's state (measured joints) is turned back into what the
skills read: gripper pose (FK), commanded pose, cube_attached (jaw closed
on the cube: commanded closed, jaw stopped short, cube at the fingertips),
successes (cube came to rest inside the bowl) and releases (gripper opened
while holding).
"""
import math
import os
import struct
import sys
import threading

import numpy as np
import mujoco

MJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "sim", "mujoco")
sys.path.insert(0, MJ)
import ik as _ik  # noqa: E402

OPEN, CLOSED = 1.0, 0.0          # gripper joint angle (rad)
STOPPED_SHORT = 0.05             # empty close ends at 0.00 rad; holding the cube ends at 0.09-0.14


class _Kin:
    """Private model/data per thread (IK in the tree thread, FK in the bridge)."""
    def __init__(self):
        self.m = mujoco.MjModel.from_xml_path(os.path.join(MJ, "scene.xml"))
        self.d = mujoco.MjData(self.m)
        self.site = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_SITE, "gripperframe")

    def fk(self, q):
        self.d.qpos[:6] = list(q[:6])
        mujoco.mj_kinematics(self.m, self.d)
        return self.d.site_xpos[self.site].copy()


def _wrap_yaw(y):
    # a cube looks the same every 90 degrees: use the equivalent yaw nearest 0
    return (y + math.pi / 4) % (math.pi / 2) - math.pi / 4


class MjAdapter:
    def __init__(self, ctx):
        self.ctx = ctx
        self.kin_fk = _Kin()
        self.q_warm = np.array([0, 0, 0, 1.2, 0.0])
        self.yaw = 0.0
        self.succ = 0
        self.rel = 0
        self.in_bowl = False
        self.prev_closed_holding = False
        self.lock = threading.Lock()
        self.ik_ms = []
        # outgoing hook
        put = ctx.inbox.put

        def put_joint(chunk):
            if "_joint" not in chunk:
                chunk["_joint"] = self.to_joint(chunk["actions"])
            return put(chunk)
        ctx.inbox.put = put_joint
        # incoming hook
        upd = ctx.robot.update

        def update(s):
            upd(self.from_rust(s))
        ctx.robot.update = update

    # ------------------------------------------------------------ outgoing
    def to_joint(self, acts):
        import time
        t0 = time.perf_counter()
        with self.lock:
            q = self.q_warm.copy()
            yaw = self.yaw
        out, cache = [], {}
        for a in acts:
            if not all(math.isfinite(v) for v in a):
                out.append([float("nan")] * 6 + [0.0])
                continue
            key = (round(a[0], 5), round(a[1], 5), round(a[2], 5))
            if key not in cache:
                q_start = np.array(q, float); q_start[4] = 0.0   # yaw is added once, below
                q_free, _ = _ik.ik(key, q_start, iters=60)
                # turn the wrist to the cube's yaw, then re-solve the other
                # joints so the fingertips stay on the target point
                qq, err = _ik.ik(key, q_free, iters=60, roll=q_free[4] + yaw)
                cache[key] = qq
            q = cache[key]
            j = list(q)
            g = a[6]
            out.append(j + [CLOSED if g >= 0.5 else OPEN, 0.0])   # gripper is open/closed
        with self.lock:
            self.q_warm = np.array(q)
        self.ik_ms.append((time.perf_counter() - t0) * 1000)
        return out

    # ------------------------------------------------------------ incoming
    def _plant_extra(self):
        shm = self.ctx.bridge.shm
        P = shm.L["plant"]
        yaw = struct.unpack_from("<d", shm.mv, P["p_cube_yaw"]["offset"])[0]
        return yaw

    def from_rust(self, s):
        s = dict(s)
        qm = s["pose"][:6]
        qc = s["last_cmd"][:6]
        tip = self.kin_fk.fk(qm)
        tip_c = self.kin_fk.fk(qc)
        g_m = (OPEN - qm[5]) / (OPEN - CLOSED)
        g_c = (OPEN - qc[5]) / (OPEN - CLOSED)
        cube = s["cube"]
        bowl = s["bowl"]
        cmd_closed = g_c >= 0.5
        attached = cmd_closed and qm[5] > CLOSED + STOPPED_SHORT and math.dist(tip, cube) < 0.03
        if not attached:
            try:
                y = _wrap_yaw(self._plant_extra())
                with self.lock:
                    self.yaw = y
            except Exception:
                pass
        # release = gripper commanded open after holding the cube
        if self.prev_closed_holding and not cmd_closed:
            self.rel += 1
        self.prev_closed_holding = attached or (self.prev_closed_holding and cmd_closed)
        inside = (abs(cube[0] - bowl[0]) < 0.045 and abs(cube[1] - bowl[1]) < 0.045 and cube[2] < 0.035)
        if inside and not attached and not self.in_bowl:
            self.succ += 1
        self.in_bowl = inside and not attached
        s["joints"] = qm
        s["pose"] = list(tip) + [0.0, 0.0, 0.0, g_m]
        s["last_cmd"] = list(tip_c) + [0.0, 0.0, 0.0, g_c]
        s["cube_attached"] = int(attached)
        s["successes"] = self.succ
        s["releases"] = self.rel
        return s
