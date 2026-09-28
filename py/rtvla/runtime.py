"""The Python runtime: fixed services + Cordis core + bridge + tree runner.

The tree runs at 10 Hz on one asyncio loop. Slow work (the fake VLA) runs
in worker threads. The bridge runs in its own thread. Episodes of
pick-and-place repeat; swaps are applied only at the node's idle point.
"""
import asyncio
import math
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
NODES = os.path.join(HERE, "..", "nodes")
sys.path.insert(0, NODES)

from .bridge import Bridge  # noqa: E402
from .cordis import Cordis, ACTIVE  # noqa: E402
from .services import Ctx, state_hash  # noqa: E402
from .tree import pick_place_tree, RUNNING  # noqa: E402

SETTINGS = {
    "approach": {"handoff_height": 0.05, "tol": 0.004, "retarget": 0.005, "speed": 0.2},
    "carry": {"carry_height": 0.12, "tol": 0.005, "speed": 0.2},
    "place": {"release_height": 0.01, "tol": 0.004, "speed": 0.15},
    "retreat": {"tol": 0.01, "speed": 0.25},
    "recover": {"tol": 0.01, "speed": 0.2},
    "cube_near_seen": {"moved_threshold": 0.03},
    "vla_grasp": {"closed_ticks": 5},
}
NODE_IDS = {"approach": 1, "carry": 2, "place": 3, "retreat": 4, "recover": 5, "vla_grasp": 6}
CUBE_HOME = [0.10, 0.05, 0.02]
EPISODE_TIMEOUT = float(os.environ.get("RTVLA_EP_TIMEOUT", "40"))


class Runtime:
    def __init__(self, approach_path=None, vla=None, seed=0):
        self.ctx = ctx = Ctx(SETTINGS)
        ctx.events, ctx.running, ctx.driving_now = [], set(), False
        ctx.vla = vla or {"stall": "sleep", "delay": 0.3, "gil_n": 20}
        ctx.vla_inflight = 0
        ctx.D = 2
        ctx.workers = ThreadPoolExecutor(max_workers=2)
        self.cordis = Cordis(ctx)
        self.bridge = Bridge(ctx, node_ids=NODE_IDS)
        self.rng = random.Random(seed)
        self.fibers = {}
        self.fibers["basics"] = self.cordis.load(os.path.join(NODES, "basics.py"))
        self.fibers["approach"] = self.cordis.load(approach_path or os.path.join(NODES, "approach_v1.py"))
        assert all(f.state == ACTIVE for f in self.fibers.values()), self.fibers
        self.tree = pick_place_tree()
        self.episodes = []          # dicts: start, end, ok, approach_version
        self.stop = False
        self.tick_times = []        # tree tick durations (s)
        self.hooks = []             # callables run each tree tick (experiments)
        self.early_reject = os.environ.get("RTVLA_EARLY_REJECT", "1") == "1"
        self.undo_log = os.environ.get("RTVLA_UNDO_LOG", "1") == "1"   # 0 = DSU baseline
        import json as _json
        self.positions = _json.loads(os.environ.get("RTVLA_CUBE_POSITIONS", "[]"))

    # ------------------------------------------------------------ snapshot
    def snapshot(self):
        st = self.ctx.robot.get()
        return {"robot": st, "world": {"cube": st["cube"]}, "own": self.ctx.ownership.snapshot()}

    # ------------------------------------------------------------ idle point
    def idle(self, name):
        """Node not running, none of its chunks playing/queued, no VLA call in flight."""
        if name in self.ctx.running or self.ctx.vla_inflight:
            return False
        st = self.ctx.robot.get()
        for cid in (st["chunk_playing"], st["chunk_queued"]):
            rec = self.ctx.sent.get(cid) if cid else None
            if rec and rec["node"] == name:
                i = st["tick"] - rec["start"]
                if i < len(rec["actions"]):
                    return False
        return True

    # ------------------------------------------------------------ main loop
    async def run(self, n_episodes=None, seconds=None):
        self.bridge.start()
        while self.ctx.robot.get() is None or self.bridge.next_id is None:
            await asyncio.sleep(0.01)
        t_end = time.monotonic() + seconds if seconds else None
        while not self.stop:
            if n_episodes is not None and len(self.episodes) >= n_episodes:
                break
            if t_end and time.monotonic() > t_end:
                break
            await self.episode()
        self.bridge.stop_flag = True

    async def episode(self):
        ctx = self.ctx
        if self.positions:        # held-out evaluation: fixed list of cube positions
            px, py_ = self.positions[len(self.episodes) % len(self.positions)]
            cube = [px, py_, CUBE_HOME[2]]
        else:
            cube = [CUBE_HOME[0] + self.rng.uniform(-0.01, 0.01),
                    CUBE_HOME[1] + self.rng.uniform(-0.01, 0.01), CUBE_HOME[2]]
        self.bridge.request_reset(cube)
        await asyncio.sleep(0.15)
        ctx.blackboard.set("succ0", ctx.robot.get()["successes"])
        ep = {"start": time.monotonic(), "approach_version": ctx.registry.lookup("approach")[0]}
        status = RUNNING
        next_t = time.monotonic()
        while status == RUNNING and not self.stop:
            t0 = time.monotonic()
            ctx.driving_now = False
            status = self.tree.tick(ctx, self.snapshot())
            if not ctx.driving_now and ctx.ownership.owner != 0:
                ctx.ownership.release(ctx.ownership.token)
                ctx.inbox.put_owner_none()
            for h in list(self.hooks):
                h(self)
            self.tick_times.append(time.monotonic() - t0)
            next_t += 0.1
            await asyncio.sleep(max(0.0, next_t - time.monotonic()))
            if time.monotonic() - ep["start"] > EPISODE_TIMEOUT:
                self.tree.halt()
                status = "timeout"
        ep["end"] = time.monotonic()
        ep["ok"] = status == "success"
        self.episodes.append(ep)
        if ctx.ownership.owner != 0:
            ctx.ownership.release(ctx.ownership.token)
            ctx.inbox.put_owner_none()

    def fingerprint(self):
        """What must be identical after a rolled-back repair."""
        import threading
        try:
            n_tasks = len(asyncio.all_tasks())
        except RuntimeError:
            n_tasks = -1
        return {"registry_live": {k: self.ctx.registry.lookup(k)[0] for k in self.ctx.registry.live},
                "registry_size": self.ctx.registry.size(),
                "fibers": sorted(self.cordis.fibers),
                "plugin_modules": sorted(m for m in sys.modules if m.startswith("plugin_") and not m.startswith("plugin_naive_")),
                "naive_modules": sorted(m for m in sys.modules if m.startswith("plugin_naive_")),
                "threads": threading.active_count(), "tasks": n_tasks,
                "node_dir_modules": sorted(k for k, m in list(sys.modules.items())
                                           if getattr(m, "__file__", None) and os.path.dirname(os.path.abspath(m.__file__)) == os.path.abspath(NODES)),
                "shared_module_objects": state_hash(sorted((f"{k}.{a}", id(v)) for k, m in list(sys.modules.items())
                                                            if not k.startswith("plugin_") and getattr(m, "__file__", None)
                                                            and os.path.dirname(os.path.abspath(m.__file__)) == os.path.abspath(NODES)
                                                            for a, v in vars(m).items() if not a.startswith("__"))
                                                     + sorted((f"{c}.{a}", id(v)) for k, m in list(sys.modules.items())
                                                              if not k.startswith("plugin_") and getattr(m, "__file__", None)
                                                              and os.path.dirname(os.path.abspath(m.__file__)) == os.path.abspath(NODES)
                                                              for c, cls in vars(m).items() if isinstance(cls, type)
                                                              for a, v in vars(cls).items() if not a.startswith("__"))),
                "state": state_hash(self.ctx.settings.values)}

    # ------------------------------------------------------------ live repair
    async def swap(self, name, path, trial_k=3, log=None):
        """Load the new version beside the old, go live at the idle point,
        keep it only if the next `trial_k` episodes succeed; else roll back."""
        log = log if log is not None else {}
        ctx = self.ctx
        log["t_ready"] = time.monotonic()
        log["tick_ready"] = ctx.robot.get()["tick"]
        self._running_at_ready = set(ctx.running)
        log["fingerprint_before"] = self.fingerprint()
        old = self.fibers[name]
        before_reg = dict(ctx.registry.live)
        new = self.cordis.load(path) if self.undo_log else self.cordis.load_no_undo(path)
        log["load_state"] = new.state
        if new.state != ACTIVE:
            log["error"] = new.error
            log["registry_unchanged"] = dict(ctx.registry.live) == before_reg
            log["fingerprint_after"] = self.fingerprint()
            log["t_done"] = time.monotonic()
            return log
        new_uid = ctx.registry.newest(name)
        while not self.idle(name):
            await asyncio.sleep(0.01)
        log["t_idle"] = time.monotonic()
        log["hash_before"] = state_hash(ctx.blackboard.d, ctx.settings.values, ctx.ownership.snapshot())
        old_uid = ctx.registry.live[name]
        ctx.registry.set_live(name, new_uid)
        log["hash_after"] = state_hash(ctx.blackboard.d, ctx.settings.values, ctx.ownership.snapshot())
        log["t_live"] = time.monotonic()
        log["tick_live"] = ctx.robot.get()["tick"]
        log["running_at_ready"] = sorted(self._running_at_ready) if hasattr(self, "_running_at_ready") else None
        # the trial is the next k episodes that START after the switch; an
        # episode already in progress is not counted either way
        t_live = log["t_live"]

        def trial_eps():
            return [e for e in self.episodes if e["start"] >= t_live]

        # early reject: runtime signals that the new version misbehaved
        new_runs = set()
        rust0 = ctx.rust_rejected_by_node.get(name, 0)
        inbox0 = ctx.inbox.by_node.get(name, 0)
        wd0 = len(ctx.watchdog_fired)

        def early_reason():
            for ev in ctx.events:
                if ev[0] >= t_live and ev[1] == "start" and ev[2] == name:
                    new_runs.add(ev[4])
            if any(ev[1] == "error" and ev[2] == name and len(ev) > 5 and ev[5] in new_runs for ev in ctx.events):
                return "plugin_error"
            if any(w[0] == name and w[1] in new_runs for w in ctx.watchdog_fired[wd0:]):
                return "watchdog"
            if ctx.rust_rejected_by_node.get(name, 0) > rust0:
                return "rust_rejected_chunk"
            if any(ev[1] == "safety_halt" and ev[2] == name and ev[4] in new_runs for ev in ctx.events):
                return "safety_halt"
            if ctx.inbox.by_node.get(name, 0) > inbox0:
                return "wrong_token"
            return None
        log["early_reject"] = None
        while len(trial_eps()) < trial_k:
            await asyncio.sleep(0.05)
            if self.early_reject and early_reason():
                log["early_reject"] = early_reason()
                break
            if any(not e["ok"] for e in trial_eps()):
                break
        trial = trial_eps()[:trial_k]
        log["trial"] = [e["ok"] for e in trial]
        if log["early_reject"] is None and len(trial) == trial_k and all(e["ok"] for e in trial):
            self.cordis.unload(old)
            self.fibers[name] = new
            log["result"] = "kept"
        else:
            if log["early_reject"]:
                # stop the misbehaving run now (its chunks are revoked in Rust) and
                # switch back in the same step, so the tree cannot restart it
                self.tree.halt()
            else:
                while not self.idle(name):
                    await asyncio.sleep(0.01)
            ctx.registry.set_live(name, old_uid)
            if self.undo_log:
                self.cordis.unload(new)
            log["result"] = "rolled_back"
        log["registry_after"] = dict(ctx.registry.live)
        log["fingerprint_after"] = self.fingerprint()
        log["t_done"] = time.monotonic()
        return log


    # ------------------------------------------------------------ baseline
    async def naive_swap(self, name, path, log=None):
        """Baseline 'hot reload' as usually done: import the new file and run
        its setup, make it live at once, keep no undo log, no trial, no rollback."""
        import importlib.util
        log = log if log is not None else {}
        ctx = self.ctx
        log["t_ready"] = time.monotonic()
        log["tick_ready"] = ctx.robot.get()["tick"]
        log["fingerprint_before"] = self.fingerprint()
        self._naive_n = getattr(self, "_naive_n", 0) + 1
        modname = f"plugin_naive_{self._naive_n}"
        try:
            spec = importlib.util.spec_from_file_location(modname, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[modname] = mod
            spec.loader.exec_module(mod)
            for _ in mod.apply(ctx, {}):       # effects happen; undos are dropped
                pass
            ctx.registry.set_live(name, ctx.registry.newest(name))
            log["result"] = "live"
        except Exception as e:
            log["result"] = "error"
            log["error"] = repr(e)
        log["t_live"] = log["t_done"] = time.monotonic()
        log["fingerprint_after"] = self.fingerprint()
        return log


def dist(a, b):
    return math.dist(a, b)
