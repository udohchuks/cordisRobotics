"""MuJoCo plant process (Route 1): SO-101 at 500 Hz real time.

Reads Rust's limited joint targets from the plant slot (seqlock), steps
MuJoCo in real time, publishes measured joint state, gripper-bowl distance
and contact force every 2 ms, and logs every physics step (npz on exit).
Outcomes are logged before any reset; one process = one trial.
"""
import argparse, json, mmap, os, struct, sys, time
import numpy as np
import mujoco

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LJ = json.load(open(os.path.join(ROOT, "layout.json")))
L = LJ["plant"]
O = {k: v["offset"] for k, v in L.items()}
OC = {k: v["offset"] for k, v in LJ["command"].items()}

ap = argparse.ArgumentParser()
ap.add_argument("--shm", default=os.environ.get("RTVLA_SHM", "/dev/shm/rtvla.shm"))
ap.add_argument("--q0", default="0,0,0,0,0,0")
ap.add_argument("--bowl", default="0.23,-0.09,0")
ap.add_argument("--cube", default="0.22,0.07,0.0125")
ap.add_argument("--cube_mass", type=float, default=0.02)
ap.add_argument("--cube_friction", type=float, default=1.0)
ap.add_argument("--out", default="/tmp/plant.npz")
ap.add_argument("--max_s", type=float, default=30)
ap.add_argument("--scene", default=os.path.join(HERE, "scene.xml"))
a = ap.parse_args()

m = mujoco.MjModel.from_xml_path(a.scene)
d = mujoco.MjData(m)
DT = m.opt.timestep
bid = lambda n: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n)
gid = lambda n: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, n)
BOWL, CUBE, BASE = bid("bowl"), bid("cube"), bid("base")
cube_g = gid("cube")
m.geom_friction[cube_g, 0] = a.cube_friction
m.body_mass[CUBE] = a.cube_mass
# robot bodies = subtree of base
robot_bodies = set(i for i in range(m.nbody) if i == BASE or (m.body_rootid[i] == BASE))
bowl_geoms = [i for i in range(m.ngeom) if m.geom_bodyid[i] == BOWL]
near_bodies = {bid("gripper"), bid("moving_jaw_so101_v1"), bid("wrist")}
tip_geoms = [i for i in range(m.ngeom) if m.geom_bodyid[i] in near_bodies and m.geom_contype[i] | m.geom_conaffinity[i]]
tip_site = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "gripperframe")
cube_qadr = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "cube")]
bowl_qadr = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "bowl")]

q0 = [float(x) for x in a.q0.split(",")]
d.qpos[:6] = q0; d.ctrl[:6] = q0
d.qpos[cube_qadr:cube_qadr + 3] = [float(x) for x in a.cube.split(",")]
d.qpos[bowl_qadr:bowl_qadr + 3] = [float(x) for x in a.bowl.split(",")]
mujoco.mj_forward(m, d)

fd = os.open(a.shm, os.O_RDWR); mm = mmap.mmap(fd, 8192); os.close(fd); mv = memoryview(mm)
u = lambda k: struct.unpack_from("<Q", mv, O[k])[0]
def read_target():
    for _ in range(3):
        s1 = u("r_seq")
        if s1 % 2: continue
        tgt = struct.unpack_from("<6d", mv, O["r_target"]); quit_ = u("r_quit"); tick = struct.unpack_from("<q", mv, O["r_tick"])[0]
        if u("r_seq") == s1: return tgt, quit_, tick
    return None
pseq = 0
n_resets = 0
def publish(step, dist, rtf, force, tip):
    global pseq
    pseq += 1 if pseq % 2 == 0 else 2
    struct.pack_into("<Q", mv, O["p_seq"], pseq)        # odd: writing
    struct.pack_into("<Q", mv, O["p_step"], step)
    struct.pack_into("<d", mv, O["p_time"], d.time)
    struct.pack_into("<6d", mv, O["p_qpos"], *d.qpos[:6])
    struct.pack_into("<6d", mv, O["p_qvel"], *d.qvel[:6])
    struct.pack_into("<d", mv, O["p_dist"], dist); struct.pack_into("<d", mv, O["p_rtf"], rtf)
    struct.pack_into("<d", mv, O["p_force"], force)
    struct.pack_into("<3d", mv, O["p_cube"], *d.qpos[cube_qadr:cube_qadr + 3])
    struct.pack_into("<3d", mv, O["p_bowl"], *d.qpos[bowl_qadr:bowl_qadr + 3])
    struct.pack_into("<3d", mv, O["p_tip"], *tip)
    w_, x_, y_, z_ = d.qpos[cube_qadr + 3:cube_qadr + 7]
    struct.pack_into("<d", mv, O["p_cube_yaw"], float(np.arctan2(2 * (w_ * z_ + x_ * y_), 1 - 2 * (y_ * y_ + z_ * z_))))
    struct.pack_into("<Q", mv, O["p_resets"], n_resets)
    pseq += 1
    struct.pack_into("<Q", mv, O["p_seq"], pseq)        # even: done

fromto = np.zeros(6); f6 = np.zeros(6)
def gripper_bowl_dist():
    best = 1.0
    for g in tip_geoms:
        for b in bowl_geoms:
            best = min(best, mujoco.mj_geomDistance(m, d, g, b, 0.2, fromto))
    return best
def contacts():
    """robot-bowl normal force, robot-table force (excluding base), cube-robot."""
    fb = ft = 0.0
    for i in range(d.ncon):
        c = d.contact[i]
        b1, b2 = m.geom_bodyid[c.geom1], m.geom_bodyid[c.geom2]
        r1, r2 = b1 in robot_bodies, b2 in robot_bodies
        mujoco.mj_contactForce(m, d, i, f6)
        if (r1 and b2 == BOWL) or (r2 and b1 == BOWL): fb += abs(f6[0])
        elif (r1 and b2 == 0 and b1 != BASE) or (r2 and b1 == 0 and b2 != BASE): ft += abs(f6[0])
    return fb, ft

# cube resets between episodes (requested by Python in the command slot:
# reset_seq changes -> put the cube at reset_cube[0:2], random yaw).
# The outcome of the previous episode is already logged before this.
n_resets = 0
rng_reset = np.random.default_rng(int(os.environ.get("RTVLA_SEED", "0")))
last_reset = struct.unpack_from("<Q", mv, OC["reset_seq"])[0]
def check_reset():
    global last_reset, n_resets
    rs = struct.unpack_from("<Q", mv, OC["reset_seq"])[0]
    if rs != last_reset:
        last_reset = rs
        x, y, _ = struct.unpack_from("<3d", mv, OC["reset_cube"])
        yaw = rng_reset.uniform(-0.5, 0.5)
        d.qpos[cube_qadr:cube_qadr + 7] = [x, y, 0.0125, np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
        d.qvel[m.jnt_dofadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "cube")]:][:6] = 0
        mujoco.mj_forward(m, d)
        n_resets += 1
log = []
ramp_from = ramp_to = d.ctrl[:6].copy(); ramp_t0 = 0.0
t0 = time.perf_counter(); t0_mono = time.monotonic(); step = 0; last_tick = -1; lag_steps = 0
dist = gripper_bowl_dist(); fb, ft = contacts()
publish(0, dist, 1.0, fb, d.site_xpos[tip_site])
while True:
    r = read_target()
    if r is not None:
        tgt, quit_, tick = r
        if quit_: break
        # a target counts only once Rust has written one (r_seq > 0). Each new
        # 30 Hz target is reached by a linear ramp over one Rust tick (33 ms)
        # instead of a step, so the servo does not move in a staircase.
        if u("r_seq") > 0 and tick != last_tick:
            ramp_from = d.ctrl[:6].copy(); ramp_to = np.array(tgt); ramp_t0 = d.time; last_tick = tick
    if last_tick >= 0:
        a_ = min(1.0, (d.time - ramp_t0) / 0.033)
        d.ctrl[:6] = ramp_from + a_ * (ramp_to - ramp_from)
    if step % 5 == 0:
        check_reset()
    mujoco.mj_step(m, d); step += 1
    dist = gripper_bowl_dist(); fb, ft = contacts()
    wall = time.perf_counter() - t0
    rtf = d.time / wall if wall > 0 else 1.0
    tip = d.site_xpos[tip_site].copy()
    publish(step, dist, rtf, fb, tip)
    log.append((d.time, wall, last_tick, *d.qpos[:6], *d.ctrl[:6], *tip, dist, fb, ft,
                *d.qpos[bowl_qadr:bowl_qadr + 3], *d.qpos[cube_qadr:cube_qadr + 7]))
    ahead = d.time - (time.perf_counter() - t0)
    if ahead > 0: time.sleep(ahead)
    elif ahead < -DT: lag_steps += 1
    if d.time > a.max_s: break
np.savez(a.out, log=np.array(log), cols=np.array("t wall tick q0 q1 q2 q3 q4 q5 c0 c1 c2 c3 c4 c5 tx ty tz dist fbowl ftable bx by bz cx cy cz cqw cqx cqy cqz".split()),
         lag_steps=lag_steps, dt=DT, t0_mono=t0_mono, t0_perf=t0, qpos_final=d.qpos.copy())
print(json.dumps({"steps": step, "sim_s": d.time, "wall_s": time.perf_counter() - t0, "lag_steps": lag_steps}), file=sys.stderr)
