"""The real SmolVLA (lerobot/smolvla_base) on CPU, used only for its inference
time and CPU load; its 6-joint output does not drive the toy Cartesian sim."""
import glob
import os
import threading
import time

_policy = _pre = None
_lock = threading.Lock()
times = []


def load(threads=1):
    global _policy, _pre
    import torch
    torch.set_num_threads(threads)
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
    from lerobot.policies.factory import make_pre_post_processors
    path = glob.glob(os.path.expanduser("~/.cache/huggingface/hub/models--lerobot--smolvla_base/snapshots/*"))[0]
    _policy = SmolVLAPolicy.from_pretrained(path).eval()
    _policy.config.device = "cpu"
    _pre, _ = make_pre_post_processors(_policy.config, pretrained_path=path,
                                       preprocessor_overrides={"device_processor": {"device": "cpu"}},
                                       postprocessor_overrides={"device_processor": {"device": "cpu"}})
    infer()  # warm-up


def infer():
    import torch
    b = {"observation.state": torch.zeros(1, 6), "task": ["pick up the cube and put it in the bowl"]}
    for k in ("camera1", "camera2", "camera3"):
        b[f"observation.images.{k}"] = torch.rand(1, 3, 256, 256)
    t = time.time()
    with _lock, torch.inference_mode():
        _policy.predict_action_chunk(_pre(b))
    times.append(time.time() - t)
    return times[-1]
