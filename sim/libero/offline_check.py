"""Check lib/vla.py reproduces lerobot-eval: plain LIBERO loop, no runtime."""
import sys, time, json, numpy as np, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("MUJOCO_GL", "egl")
from vla import SmolVLA
from lerobot.envs.libero import LiberoEnv, _get_suite
task = int(sys.argv[1]); eps = int(sys.argv[2])
v = SmolVLA(threads=int(os.environ.get("TH", "1")))
suite = _get_suite("libero_goal")
env = LiberoEnv(task_suite=suite, task_id=task, task_suite_name="libero_goal", obs_type="pixels_agent_pos")
for ep in range(eps):
    env.init_state_id = ep
    obs, _ = env.reset(seed=ep)
    inner = env._env; ok = False; ts = []
    instr = env.task_description
    for k in range(30):
        acts, dt = v.infer(obs, instr); ts.append(dt)
        for a in acts:
            raw, _, _, _ = inner.step(a)
            if inner.check_success(): ok = True; break
        obs = env._format_raw_obs(raw)
        if ok: break
    print(json.dumps({"task": task, "ep": ep, "ok": ok, "steps": (k + 1) * 10, "infer_s": round(float(np.median(ts)), 2)}), flush=True)
