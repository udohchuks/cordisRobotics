"""The real VLA: SmolVLA fine-tuned on LIBERO (HuggingFaceVLA/smolvla_libero), on CPU.

`SmolVLA.infer(obs, instruction)` runs one inference and returns the next
`n` LIBERO commands (n x 7), exactly as lerobot-eval does: same observation
preprocessing, same env/policy processors, same select_action queue
(n_action_steps = 10, the setting that reproduces the paper's LIBERO numbers).
`read_obs(img_shm)` reads the newest camera frames + robot state that the
plant published (seqlock), in LiberoEnv's observation format.
"""
import mmap
import os
import struct
import time

import numpy as np

H = 256
IMG_HDR = 8 * 4 + 8 * 20
IMG_SIZE = IMG_HDR + 2 * H * H * 3


class ObsReader:
    def __init__(self, path="/dev/shm/rtvla_img.shm"):
        fd = os.open(path, os.O_RDONLY)
        self.m = mmap.mmap(fd, IMG_SIZE, prot=mmap.PROT_READ)
        os.close(fd)

    def read(self):
        for _ in range(50):
            s1 = struct.unpack_from("<Q", self.m, 0)[0]
            if s1 % 2 or s1 == 0:
                time.sleep(0.002); continue
            tick, step = struct.unpack_from("<qQ", self.m, 8)
            st = np.array(struct.unpack_from("<20d", self.m, 32))
            img = np.frombuffer(self.m, np.uint8, H * H * 3, IMG_HDR).reshape(H, H, 3).copy()
            img2 = np.frombuffer(self.m, np.uint8, H * H * 3, IMG_HDR + H * H * 3).reshape(H, H, 3).copy()
            if struct.unpack_from("<Q", self.m, 0)[0] == s1:
                obs = {"pixels": {"image": img, "image2": img2},
                       "robot_state": {"eef": {"pos": st[0:3], "quat": st[3:7], "mat": st[7:16].reshape(3, 3)},
                                       "gripper": {"qpos": st[16:18], "qvel": st[18:20]}}}
                return obs, tick, step
        return None, None, None


class SmolVLA:
    def __init__(self, n_action_steps=10, threads=1, repo="HuggingFaceVLA/smolvla_libero"):
        import torch
        torch.set_num_threads(threads)
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.envs.configs import LiberoEnv as LiberoEnvCfg
        from lerobot.envs.factory import make_env_pre_post_processors
        from lerobot.policies.factory import make_policy, make_pre_post_processors
        self.torch = torch
        cfg = PreTrainedConfig.from_pretrained(repo)
        cfg.pretrained_path = repo
        cfg.device = "cpu"
        cfg.n_action_steps = n_action_steps
        env_cfg = LiberoEnvCfg(task="libero_goal")
        self.policy = make_policy(cfg=cfg, env_cfg=env_cfg)
        self.policy.eval()
        self.pre, self.post = make_pre_post_processors(
            policy_cfg=cfg, pretrained_path=repo,
            preprocessor_overrides={"device_processor": {"device": "cpu"}})
        self.env_pre, self.env_post = make_env_pre_post_processors(env_cfg=env_cfg, policy_cfg=cfg)
        self.n = n_action_steps

    @staticmethod
    def _batch(obs):
        def b(x):
            if isinstance(x, dict):
                return {k: b(v) for k, v in x.items()}
            return np.asarray(x)[None]
        return b(obs)

    def infer(self, obs, instruction):
        """One inference -> the next n commands (n x 7) and the time it took."""
        from lerobot.envs.utils import preprocess_observation
        from lerobot.utils.constants import ACTION
        torch = self.torch
        t0 = time.time()
        self.policy.reset()
        acts = []
        with torch.inference_mode():
            for _ in range(self.n):          # 1st call infers a chunk; the rest pop its queue
                o = preprocess_observation(self._batch(obs))
                o["task"] = [instruction]
                o = self.env_pre(o)
                o = self.pre(o)
                a = self.policy.select_action(o)
                a = self.post(a)
                a = self.env_post({ACTION: a})[ACTION]
                acts.append(a.to("cpu").numpy()[0])
        return np.array(acts, dtype=np.float64), time.time() - t0
