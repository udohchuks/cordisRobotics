import sys, os, json, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MUJOCO_GL", "egl")
from vla import SmolVLA
from lerobot.envs.libero import LiberoEnv, _get_suite
v = SmolVLA(threads=2)
env = LiberoEnv(task_suite=_get_suite("libero_goal"), task_id=7, task_suite_name="libero_goal", obs_type="pixels_agent_pos")
C = np.array([-0.254, 0.202])
for ep in range(2):
    env.init_state_id = ep; obs, _ = env.reset(seed=ep); inner = env._env
    se = inner.env; traj = []; on_at = None
    for k in range(30):
        acts, _ = v.infer(obs, "turn on the stove")
        for a in acts:
            raw, _, _, _ = inner.step(a)
            e = raw["robot0_eef_pos"]; traj.append((float(np.linalg.norm(e[:2] - C)), float(e[2])))
            if on_at is None and se._eval_predicate(["turnon", "flat_stove_1"]): on_at = len(traj)
        obs = env._format_raw_obs(raw)
        if on_at is not None and len(traj) > on_at + 20: break
    t = np.array(traj)
    print(json.dumps({"ep": ep, "on_at": on_at, "min_r": round(float(t[:, 0].min()), 3), "r_at_on": traj[on_at - 1] if on_at else None,
                      "min_z": round(float(t[:, 1].min()), 3)}), flush=True)
