"""Offline grasp tuning: scripted descend/close/lift with the plant physics (no runtime)."""
import sys, os, numpy as np, mujoco
sys.path.insert(0, os.path.dirname(__file__)); from ik import ik
m = mujoco.MjModel.from_xml_path(os.path.join(os.path.dirname(__file__), 'scene.xml'))
ca = m.jnt_qposadr[mujoco.mj_name2id(m, 3, 'cube')]; ba = m.jnt_qposadr[mujoco.mj_name2id(m, 3, 'bowl')]
cg = mujoco.mj_name2id(m, 5, 'cube')

def run(cube_xy=(0.22, 0.07), yaw=0.0, roll_k=0.0, dz=0.0, close=-0.1, open_=1.0, mass=0.02, fric=1.0, dx=0.0, dy=0.0, render=None):
    m.body_mass[mujoco.mj_name2id(m, 1, 'cube')] = mass; m.geom_friction[cg, 0] = fric
    d = mujoco.MjData(m)
    d.qpos[ca:ca+3] = [*cube_xy, 0.0125]; d.qpos[ca+3:ca+7] = [np.cos(yaw/2), 0, 0, np.sin(yaw/2)]
    d.qpos[ba:ba+3] = [0.23, -0.09, 0]
    def tgt(z):
        q = ik((cube_xy[0]+dx, cube_xy[1]+dy, z), [0, 0, 0, 1.2, 0])[0].copy()
        q[4] += roll_k * yaw          # turn the wrist to the cube's yaw
        return q
    q = tgt(0.08); d.qpos[:5] = q; d.qpos[5] = open_; d.ctrl[:5] = q; d.ctrl[5] = open_
    mujoco.mj_forward(m, d)
    frames = []
    def go(qa, g, T):
        q0 = d.ctrl[:5].copy(); g0 = d.ctrl[5]
        n = int(T / m.opt.timestep)
        for k in range(n):
            a = (k + 1) / n
            d.ctrl[:5] = q0 + a * (qa - q0); d.ctrl[5] = g0 + a * (g - g0)
            mujoco.mj_step(m, d)
            if render is not None and k % 20 == 0: frames.append(d.qpos.copy())
    z_grasp = 0.0125 + dz
    go(tgt(0.08), open_, 0.3); go(tgt(z_grasp), open_, 0.8); go(tgt(z_grasp), close, 0.5)
    go(tgt(z_grasp), close, 0.3); go(tgt(0.12), close, 1.0); go(tgt(0.12), close, 0.5)
    return d.qpos[ca+2], frames

if __name__ == '__main__':
    for dz in [-0.005, 0.0, 0.005]:
        for close in [-0.17, 0.0, 0.2]:
            z, _ = run(dz=dz, close=close)
            print(f'dz={dz:+.3f} close={close:+.2f} cube z after lift={z:.3f}', 'LIFTED' if z > 0.08 else '')
