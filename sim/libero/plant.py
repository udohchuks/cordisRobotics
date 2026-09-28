"""LIBERO plant process: the LIBERO-Goal kitchen, stepped once per Rust tick.

Rust (live_lib) writes one 7-D LIBERO command per tick into the plant slot.
This process waits for each new tick, steps the simulator once with that
command (one LIBERO control step), and publishes:
  - the robot state (eef pos, axis-angle, gripper width) in the plant slot;
  - camera images + the full robot state in a second shm file (for the VLA);
  - a scene-state JSON (object positions + goal predicates) for code skills.
If the plant is slower than Rust it steps with the newest command and counts
the ticks it skipped (skipped ticks are logged; a skipped hold tick is harmless).
Every step is logged; the log is written on exit.
"""
import argparse, json, mmap, os, struct, sys, time
import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LJ = json.load(open(os.path.join(ROOT, "layout.json")))
O = {k: v["offset"] for k, v in LJ["plant"].items()}

ap = argparse.ArgumentParser()
ap.add_argument("--shm", default="/dev/shm/rtvla.shm")
ap.add_argument("--img_shm", default="/dev/shm/rtvla_img.shm")
ap.add_argument("--scene_json", default="/dev/shm/rtvla_scene.json")
ap.add_argument("--cmd_json", default="/dev/shm/rtvla_plantcmd.json")
ap.add_argument("--task", type=int, default=8)
ap.add_argument("--init", type=int, default=0, help="LIBERO init-state index")
ap.add_argument("--out", default="/tmp/lib_plant.npz")
ap.add_argument("--frames", default="", help="dir to save a low-res frame every N steps")
ap.add_argument("--frame_every", type=int, default=10)
ap.add_argument("--video", default="", help="mp4 of both cameras, every step")
ap.add_argument("--no_replay", action="store_true")
a = ap.parse_args()

from lerobot.envs.libero import LiberoEnv, _get_suite  # noqa: E402
from libero.libero import benchmark, get_libero_path  # noqa: E402
from libero.libero.envs.bddl_utils import robosuite_parse_problem  # noqa: E402

REPLAY = not a.no_replay
suite = _get_suite("libero_goal")
env = LiberoEnv(task_suite=suite, task_id=a.task, task_suite_name="libero_goal",
                obs_type="pixels_agent_pos")
env.init_state_id = a.init
obs, _ = env.reset(seed=a.init)
inner = env._env
sim_env = inner.env
sim_env.ignore_done = True   # one long run: never end the episode
sim_env.horizon = 10 ** 9

# goals of all ten LIBERO-Goal tasks (same scene, same object names)
bm = benchmark.get_benchmark_dict()["libero_goal"]()
GOALS = []
for i in range(10):
    t = bm.get_task(i)
    p = robosuite_parse_problem(os.path.join(get_libero_path("bddl_files"), t.problem_folder, t.bddl_file))
    GOALS.append((t.language, p["goal_state"]))


def goal_status():
    out = {}
    for lang, gs in GOALS:
        try:
            out[lang] = bool(all(sim_env._eval_predicate(g) for g in gs))
        except Exception as e:  # noqa: BLE001
            out[lang] = None
    return out


OBJ = ["akita_black_bowl_1", "plate_1", "wine_bottle_1", "cream_cheese_1",
       "wooden_cabinet_1", "flat_stove_1", "wine_rack_1"]


MOVABLE = ["akita_black_bowl_1", "plate_1", "wine_bottle_1", "cream_cheese_1"]
DRAWERS = ["wooden_cabinet_1_top_region", "wooden_cabinet_1_middle_region", "wooden_cabinet_1_bottom_region"]


def facts():
    """True symbolic facts about the scene (what a perception module would report)."""
    out = []
    names = list(sim_env.object_states_dict.keys())
    for o in MOVABLE:
        for tg in names:
            if tg == o:
                continue
            for p in ("on", "in"):
                try:
                    if sim_env._eval_predicate([p, o, tg]):
                        out.append([p, o, tg])
                except Exception:  # noqa: BLE001
                    pass
    for r in DRAWERS:
        try:
            if sim_env._eval_predicate(["open", r]):
                out.append(["open", r])
        except Exception:  # noqa: BLE001
            pass
    try:
        if sim_env._eval_predicate(["turnon", "flat_stove_1"]):
            out.append(["turnon", "flat_stove_1"])
    except Exception:  # noqa: BLE001
        pass
    return out


def scene():
    objs = {}
    for n in OBJ:
        try:
            bid = sim_env.obj_body_id[n]
            objs[n] = [round(float(x), 4) for x in sim_env.sim.data.body_xpos[bid]]
        except Exception:  # noqa: BLE001
            pass
    return objs


# ---------------------------------------------------------------- shm
fd = os.open(a.shm, os.O_RDWR); mm = mmap.mmap(fd, 8192); os.close(fd); mv = memoryview(mm)
u = lambda k: struct.unpack_from("<Q", mv, O[k])[0]
wu = lambda k, v: struct.pack_into("<Q", mv, O[k], v)
wf = lambda k, v, i=0: struct.pack_into("<d", mv, O[k] + 8 * i, v)

H = 256
IMG_HDR = 8 * 4 + 8 * 20
IMG_SIZE = IMG_HDR + 2 * H * H * 3
with open(a.img_shm, "wb") as f:
    f.truncate(IMG_SIZE)
fdi = os.open(a.img_shm, os.O_RDWR); mi = mmap.mmap(fdi, IMG_SIZE); os.close(fdi); mvi = memoryview(mi)


def read_cmd():
    for _ in range(3):
        s1 = u("r_seq")
        if s1 % 2:
            continue
        tick = struct.unpack_from("<q", mv, O["r_tick"])[0]
        act = struct.unpack_from("<7d", mv, O["r_act"])
        quit_ = u("r_quit")
        if u("r_seq") == s1:
            return tick, np.array(act), quit_
    return None


def quat2axisangle(q):
    x, y, z, w = q
    w = max(-1.0, min(1.0, w))
    den = np.sqrt(1.0 - w * w)
    if den < 1e-9:
        return np.zeros(3)
    return np.array([x, y, z]) * 2.0 * np.arccos(w) / den


def publish(o, step, tick, rtf):
    rs = o["robot_state"]
    pos, quat = rs["eef"]["pos"], rs["eef"]["quat"]
    gq = rs["gripper"]["qpos"]
    aa = quat2axisangle(quat)
    s1 = u("p_seq"); wu("p_seq", s1 + 1)
    for i in range(3):
        wf("p_lstate", float(pos[i]), i); wf("p_lstate", float(aa[i]), 3 + i)
    wf("p_lstate", float(gq[0] - gq[1]), 6)
    wu("p_step", step); wf("p_rtf", rtf)
    wu("p_seq", s1 + 2)
    # images + full state for the VLA (seqlock at offset 0)
    si = struct.unpack_from("<Q", mvi, 0)[0]
    struct.pack_into("<Q", mvi, 0, si + 1)
    struct.pack_into("<qQ", mvi, 8, tick, step)
    st = np.concatenate([pos, quat, rs["eef"]["mat"].reshape(-1), gq, rs["gripper"]["qvel"]]).astype(np.float64)
    struct.pack_into("<20d", mvi, 32, *st.tolist())
    mvi[IMG_HDR:IMG_HDR + H * H * 3] = np.ascontiguousarray(o["pixels"]["image"]).tobytes()
    mvi[IMG_HDR + H * H * 3:IMG_SIZE] = np.ascontiguousarray(o["pixels"]["image2"]).tobytes()
    struct.pack_into("<Q", mvi, 0, si + 2)


def write_scene(step, tick):
    d = {"step": step, "tick": tick, "t_wall": time.time(), "objects": scene(),
         "goals": goal_status(), "facts": facts(),
         "eef": [round(float(x), 4) for x in struct.unpack_from("<7d", mv, O["p_lstate"])]}
    tmp = a.scene_json + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, a.scene_json)
    return d


def apply_plant_cmd():
    """Test-harness perturbations (e.g. move an object). Never used by the agent."""
    if not os.path.exists(a.cmd_json):
        return None
    try:
        c = json.load(open(a.cmd_json)); os.remove(a.cmd_json)
    except Exception:  # noqa: BLE001
        return None
    if c.get("op") == "move":
        jn = sim_env.objects_dict[c["obj"]].joints[-1]
        adr = sim_env.sim.model.get_joint_qpos_addr(jn)
        q = sim_env.sim.data.qpos
        q[adr[0]:adr[0] + 3] = c["xyz"]
        sim_env.sim.forward()
    return c


wu("r_quit", 0)  # clear a quit left by a previous Rust run
publish(obs, 0, -1, 0.0)
last = write_scene(0, -1)
log = {"step": [], "tick": [], "wall": [], "act": [], "state": [], "skipped": [], "step_ms": [], "n_steps": []}
goal_log = []
frames_dir = a.frames
if frames_dir:
    os.makedirs(frames_dir, exist_ok=True)
vw = None
if a.video:
    import imageio
    vw = imageio.get_writer(a.video, fps=20, codec="libx264", quality=6, macro_block_size=8)
print(f"plant: task {a.task} ready: {env.task}", flush=True)

last_tick = -1
step = 0
t_start = time.time()
prev_goals = last["goals"]
while True:
    r = read_cmd()
    if r is None:
        time.sleep(0.001); continue
    tick, act, quit_ = r
    if quit_:
        break
    if tick == last_tick:
        time.sleep(0.001); continue
    # replay every tick's command in order (from the ring) so no command is lost
    todo = [tick] if last_tick < 0 else list(range(last_tick + 1, tick + 1))
    skipped = max(0, len(todo) - 16)
    todo = todo[-16:]
    last_tick = tick
    c = apply_plant_cmd()
    t0 = time.time()
    for tk in todo:
        a_t = np.array(struct.unpack_from("<7d", mv, O["r_ring"] + 8 * 7 * (tk % 16))) if (tk != tick and REPLAY) else act
        if tk != tick and not REPLAY:
            continue
        raw, _, _, _ = inner.step(a_t.astype(np.float64))
    o = env._format_raw_obs(raw)
    step += len(todo)
    dt = time.time() - t0
    rtf = step * 0.05 / max(1e-6, time.time() - t_start)
    publish(o, step, tick, rtf)
    if step // 4 != (step - len(todo)) // 4 or c is not None:   # at least every 4 steps
        last = write_scene(step, tick)
        if last["goals"] != prev_goals:
            goal_log.append({"step": step, "tick": tick, "wall": time.time(), "goals": last["goals"]})
            prev_goals = last["goals"]
    if vw is not None:
        # LIBERO renders upside down; flip for viewing only
        vw.append_data(np.concatenate([o["pixels"]["image"][::-1, ::-1], o["pixels"]["image2"][::-1, ::-1]], axis=1))
    if frames_dir and step // a.frame_every != (step - len(todo)) // a.frame_every:
        np.save(os.path.join(frames_dir, f"{step:06d}.npy"), o["pixels"]["image"][::4, ::4])
    log["step"].append(step); log["tick"].append(tick); log["wall"].append(time.time())
    log["act"].append(act); log["state"].append(struct.unpack_from("<7d", mv, O["p_lstate"]))
    log["skipped"].append(skipped); log["step_ms"].append(dt * 1000); log["n_steps"].append(len(todo))

if vw is not None:
    vw.close()
np.savez(a.out, **{k: np.array(v) for k, v in log.items()})
json.dump(goal_log, open(a.out.replace(".npz", "_goals.json"), "w"))
print(f"plant: {step} steps, wrote {a.out}", flush=True)
