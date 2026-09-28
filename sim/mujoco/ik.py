"""Damped least-squares IK for the SO-101 gripper site (position + keep the
gripper pointing down). Pure kinematics on a private MjData copy."""
import os
import numpy as np
import mujoco

HERE = os.path.dirname(os.path.abspath(__file__))
_m = mujoco.MjModel.from_xml_path(os.path.join(HERE, "scene.xml"))
_d = mujoco.MjData(_m)
_site = mujoco.mj_name2id(_m, mujoco.mjtObj.mjOBJ_SITE, "gripperframe")
QMIN = _m.jnt_range[:5, 0].copy(); QMAX = _m.jnt_range[:5, 1].copy()


def fk(q):
    _d.qpos[:6] = list(q[:5]) + [q[5] if len(q) > 5 else 0.0]
    mujoco.mj_kinematics(_m, _d)
    mujoco.mj_comPos(_m, _d)
    return _d.site_xpos[_site].copy(), _d.site_xmat[_site].reshape(3, 3).copy()


def ik(target, q_init, down=True, iters=200, tol=1e-4, w_rot=0.05, roll=None):
    """roll=None: all 5 joints free. roll=r: wrist_roll held at r, the other
    four solve the position (and pointing down)."""
    q = np.array(q_init[:5], float)
    if roll is not None:
        q[4] = roll
    jp = np.zeros((3, _m.nv)); jr = np.zeros((3, _m.nv))
    for _ in range(iters):
        p, R = fk(list(q) + [0])
        e = np.asarray(target) - p
        rows = [e]; J = [None]
        mujoco.mj_jacSite(_m, _d, jp, jr, _site)
        Js = [jp[:, :5]]
        if down:
            # the site's x axis should point down (-z world) for a top grasp
            ax = R[:, 0]; er = np.cross(ax, [0, 0, -1.0])
            rows.append(w_rot * er); Js.append(w_rot * jr[:, :5])
        E = np.concatenate(rows); JJ = np.vstack(Js)
        if np.linalg.norm(e) < tol and (not down or np.linalg.norm(rows[1]) < 5e-3):
            break
        if roll is not None:
            JJ = JJ.copy(); JJ[:, 4] = 0.0
        dq = JJ.T @ np.linalg.solve(JJ @ JJ.T + 1e-4 * np.eye(len(E)), E)
        q = np.clip(q + np.clip(dq, -0.2, 0.2), QMIN, QMAX)
    p, _ = fk(list(q) + [0])
    return q, float(np.linalg.norm(np.asarray(target) - p))
