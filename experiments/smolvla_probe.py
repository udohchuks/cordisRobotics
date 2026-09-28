"""Load the real SmolVLA (lerobot/smolvla_base) on CPU and time one chunk of inference."""
import glob
import os
import sys
import time

import torch

threads = int(sys.argv[1]) if len(sys.argv) > 1 else 1
n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
torch.set_num_threads(threads)
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy  # noqa: E402
from lerobot.policies.factory import make_pre_post_processors  # noqa: E402

path = glob.glob(os.path.expanduser("~/.cache/huggingface/hub/models--lerobot--smolvla_base/snapshots/*"))[0]
t0 = time.time()
policy = SmolVLAPolicy.from_pretrained(path).eval()
policy.config.device = "cpu"
pre, post = make_pre_post_processors(policy.config, pretrained_path=path,
                                     preprocessor_overrides={"device_processor": {"device": "cpu"}},
                                     postprocessor_overrides={"device_processor": {"device": "cpu"}})
print("load s", round(time.time() - t0, 1), "params M", sum(p.numel() for p in policy.parameters()) / 1e6)


def batch():
    b = {"observation.state": torch.zeros(1, 6), "task": ["pick up the cube and put it in the bowl"]}
    for k in ("camera1", "camera2", "camera3"):
        b[f"observation.images.{k}"] = torch.rand(1, 3, 256, 256)
    return b


times = []
for i in range(n):
    t = time.time()
    with torch.inference_mode():
        obs = pre(batch())
        act = policy.predict_action_chunk(obs)
    times.append(time.time() - t)
    print(f"chunk {i}: {times[-1]:.2f} s, shape {tuple(act.shape)}", flush=True)
print("threads", threads, "median s", sorted(times)[len(times) // 2])
