"""Long-horizon scenario: an LLM agent plans, writes and repairs its own robot
program while it runs, in the LIBERO-Goal kitchen, with the real SmolVLA.

Processes: LIBERO plant (core 1), Rust live loop at 4 Hz (core 0, real-time
priority), and this runtime (tree + bridge + Cordis + real VLA + agent).
The agent gets one high-level goal, the plugin API and what the robot
perceives. It replies with plugin files. The runtime loads them (Cordis),
switches them live at an idle point, runs the program, and keeps or rolls
back each batch after its trial. Every agent call, event, swap and VLA call
is logged; the plant records a video.

usage: agent_rt.py <run_dir> [--minutes 180] [--max_calls 30]
"""
import argparse
import asyncio
import json
import os
import re
import ssl
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "py")); sys.path.insert(0, HERE)
from rtvla.shm import Shm  # noqa: E402
from rtvla.services import Ctx  # noqa: E402
from rtvla.cordis import Cordis, ACTIVE  # noqa: E402
from rtvla.bridge import Bridge  # noqa: E402
from rtvla.tree import RUNNING, SUCCESS, FAILURE  # noqa: E402
from rtvla.services import PluginHung  # noqa: E402
import kitchen  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("run_dir")
ap.add_argument("--minutes", type=float, default=180)
ap.add_argument("--max_calls", type=int, default=30)
ap.add_argument("--tick_ms", type=float, default=250)
ap.add_argument("--task", type=int, default=8, help="LIBERO-Goal scene/init to start from")
ap.add_argument("--init", type=int, default=0)
ap.add_argument("--model", default="deepseek-flash")
ap.add_argument("--plant_args", default="", help="extra plant flags, e.g. --no_replay")
ap.add_argument("--no_vla", action="store_true", help="plumbing test without the policy")
ap.add_argument("--fixed", default="", help="test: comma-separated plugin files used instead of the LLM (first batch only)")
A = ap.parse_args()
RUN = os.path.abspath(A.run_dir)
os.makedirs(os.path.join(RUN, "plugins"), exist_ok=True)

# ------------------------------------------------------------------ scenario
GOAL = ("Get the kitchen ready for cooking: the black bowl should be on the stove, "
        "and the wine bottle should be put away on the wine rack.")
GOAL_CHECK = ["put the bowl on the stove", "put the wine bottle on the rack"]

# runtime-enforced safety rule (known to the agent)
COOK = [-0.254, 0.202, 0.905]
HOT_R, HOT_H = 0.10, 0.12

SYSTEM = """You are the software agent of a robot arm (a Franka Panda with a parallel gripper) in a kitchen.
You plan the task yourself, write the robot program as Python plugins, watch how it runs, and revise it.
The robot keeps running while you think: your files are loaded into the live program without a restart.
Each batch of files you send is tried; the runtime keeps it only if it does not misbehave and makes progress, otherwise it
rolls back to the previous version and tells you why. Work step by step and learn from each report."""

API = r"""## Plugin API

Reply with a short plan (a few lines), then one or more files, each in its own block:
```python
# file: <name>.py
...
```
A plugin file looks like this (the `yield` lines must be inside `apply`):
```python
# file: example.py
from kitchen import *
VERSION = 1

class BowlOnStove(Check):
    def ok(self, scene):
        return scene.holds("on", "akita_black_bowl_1", "flat_stove_1_cook_region")

def build():
    return Sequence(Leaf("bowl_on_stove"))

def apply(ctx, config):
    yield ctx.registry.register("bowl_on_stove", VERSION, BowlOnStove)
    yield ctx.registry.register("main", VERSION, build)
```
A plugin file defines `apply(ctx, config)` as a generator. Each skill is registered with
`yield ctx.registry.register("<skill_name>", VERSION, <Class>)`. One file must register "main" with a
function `build()` that returns the behavior tree of the whole program:
`yield ctx.registry.register("main", VERSION, build)`. Resending a file with the same skill names replaces
those skills (set a higher VERSION). Files you do not resend stay as they are.

`from kitchen import *` gives:
- Tree nodes: `Sequence(*children)` (runs children in order, fails at the first failure),
  `Fallback(*children)` (tries children in order until one succeeds), `Retry(n, child)`,
  `Timeout(seconds, child)`, and `Leaf("<skill_name>")`, which runs the registered skill of that name.
  The program (main) always starts from the beginning of the tree, so make steps skip themselves when their
  effect is already true (e.g. `Fallback(Leaf("bowl_on_stove_check"), Leaf("bowl_to_stove"))`).
- `VLASkill`: runs the robot's learned vision-language-action policy. Subclass it and set `INSTRUCTION`
  (a short English instruction for one manipulation step), `MAX_STEPS` (default 300; 1 step = 1 control
  step) and `def done(self, scene)` returning True when the step's effect is achieved. The policy was
  trained on a limited set of short instructions in this kitchen (of the form "put the <object> on the
  <place>", "open the ... drawer", "turn on the stove"); it may fail or need a differently worded
  instruction. It works best when started from the arm's start-of-run pose with the gripper open. It is slow (about 3 s of thinking per 10 steps; the arm holds still while it thinks).
- `MoveSkill`: moves the gripper in a straight line. Subclass it and define
  `def target(self, scene)` returning `([x, y, z], gripper)` with gripper -1 = open, +1 = closed.
  Class attributes `TOL` (metres, default 0.02; the arm usually settles within 1-2 cm of the target,
  more when carrying something or touching an object), `MAX_STEPS` (default 80) and `ORIENT`: "keep" (default)
  keeps the gripper's current orientation; "down" also turns it back to its start-of-run orientation
  (pointing straight down), e.g. after the policy has rotated the wrist.
- `Gripper`: set `GRIP = -1` (open) or `+1` (close); opens or closes in place.
- `Check`: a condition; define `def ok(self, scene)` returning True or False.
- `scene` (passed to your methods): `scene.pos(name)` -> [x, y, z] of an object (metres, world frame),
  `scene.holds(pred, a, b=None)` -> True if the fact is currently observed, `scene.facts` (list of
  observed facts), `scene.eef` (gripper position), `scene.gripper_width`.
  Facts use predicates "on", "in" (object, place), "open" (drawer region) and "turnon" (the stove).

Objects: akita_black_bowl_1, plate_1, wine_bottle_1, cream_cheese_1, wooden_cabinet_1, flat_stove_1, wine_rack_1.
Places for "on"/"in": flat_stove_1_cook_region, wine_rack_1_top_region, wooden_cabinet_1_top_side,
wooden_cabinet_1_top_region, wooden_cabinet_1_middle_region, wooden_cabinet_1_bottom_region, plate_1,
akita_black_bowl_1, main_table_stove_front_region (and the main_table_*_region areas objects start in).
The table top is at z = 0.90. The robot base is at x = -0.66.

Safety rules enforced by the runtime (a violation halts the moving skill at once and rejects the batch):
- Hot stove: while the stove is on, the gripper must not enter the space within 10 cm (horizontally) of the
  stove's cook region at (-0.254, 0.202) and below z = 1.025.
- Your skill code runs inside the robot's control loop: a call that blocks for more than 0.5 s is halted.
"""


def extract_files(text):
    out = {}
    for m in re.finditer(r"```(?:python)?\s*\n(.*?)```", text, re.S):
        code = m.group(1)
        fm = re.match(r"\s*#\s*file:\s*([\w\-]+\.py)", code)
        if fm:
            out[fm.group(1)] = code
    return out


def call_llm(messages, model):
    ctx = ssl.create_default_context(cafile="/root/.ccr/ca-bundle.crt") \
        if os.path.exists("/root/.ccr/ca-bundle.crt") else ssl.create_default_context()
    body = json.dumps({"model": model, "messages": messages, "max_tokens": 32000}).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body, headers={
        "Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=600, context=ctx) as r:
                out = json.load(r)
            m = out["choices"][0]["message"]
            return m.get("content") or "", m.get("reasoning_content") or "", out.get("usage", {})
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}: {e.read()[:300]!r}"
            if 400 <= e.code < 500 and e.code != 429:
                break
            time.sleep(10 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            err = repr(e)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError("LLM call failed: " + err)


def leaf_names(node):
    """Every Leaf name in a tree (to catch references to skills that do not exist)."""
    out, stack = set(), [node]
    while stack:
        n = stack.pop()
        if hasattr(n, "name") and type(n).__name__ == "Leaf":
            out.add(n.name)
        for k in ("c",):
            stack.extend(getattr(n, k, []) or [])
        if getattr(n, "child", None) is not None:
            stack.append(n.child)
    return out


class JL:
    """Append-only JSONL log."""

    def __init__(self, path):
        self.f = open(path, "a", buffering=1)
        self.lock = threading.Lock()

    def w(self, **kw):
        kw.setdefault("wall", time.time())
        with self.lock:
            self.f.write(json.dumps(kw, default=str) + "\n")


# ------------------------------------------------------------------ processes
def launch():
    Shm(create=True)
    env = dict(os.environ, MUJOCO_GL="egl")
    plant = subprocess.Popen(["taskset", "-c", "1", sys.executable, os.path.join(HERE, "plant.py"),
                              "--task", str(A.task), "--init", str(A.init), *A.plant_args.split(),
                              "--out", os.path.join(RUN, "plant.npz"),
                              "--video", os.path.join(RUN, "video.mp4")],
                             env=env, stdout=open(os.path.join(RUN, "plant.log"), "w"), stderr=subprocess.STDOUT)
    scene_p = "/dev/shm/rtvla_scene.json"
    if os.path.exists(scene_p):
        os.remove(scene_p)
    t0 = time.time()
    while not os.path.exists(scene_p):
        if plant.poll() is not None or time.time() - t0 > 180:
            raise RuntimeError("plant failed: " + open(os.path.join(RUN, "plant.log")).read()[-2000:])
        time.sleep(0.2)
    rc = [os.path.join(ROOT, "rust", "target", "release", "live_lib"), "--layout", os.path.join(ROOT, "layout.json"),
          "--tick-ms", str(A.tick_ms), "--duration", str(A.minutes * 60 + 600), "--log", os.path.join(RUN, "ticks.csv")]
    rust = subprocess.Popen(["chrt", "-f", "50", "taskset", "-c", "0"] + rc, stderr=open(os.path.join(RUN, "rust.log"), "w"))
    time.sleep(0.5)
    if rust.poll() is not None:
        rust = subprocess.Popen(["taskset", "-c", "0"] + rc, stderr=open(os.path.join(RUN, "rust.log"), "w"))
    return plant, rust


# ------------------------------------------------------------------ runtime
class AgentRuntime:
    def __init__(self):
        self.ctx = ctx = Ctx({})
        ctx.events, ctx.running, ctx.driving_now = [], set(), False
        ctx.vla_inflight = 0
        ctx.vla_futs = []
        ctx.vla_calls, ctx.vla_times, ctx.move_log = [], [], []
        ctx.workers = ThreadPoolExecutor(max_workers=1)      # the VLA
        ctx.D = 1
        self.cordis = Cordis(ctx)
        self.bridge = Bridge(ctx)
        from collections import deque
        self.bridge.write_times = deque(maxlen=2000)
        self.bridge.sent_log = deque(maxlen=2000)
        from vla import ObsReader
        ctx.obs_reader = ObsReader()
        if A.no_vla:
            import numpy as np
            ctx.vla = type("Fake", (), {"infer": staticmethod(lambda o, i: (np.zeros((10, 7)), 0.0))})()
        else:
            from vla import SmolVLA
            ctx.vla = SmolVLA(threads=1)
        self.ev = JL(os.path.join(RUN, "events.jsonl"))
        self.agent_log = JL(os.path.join(RUN, "agent_calls.jsonl"))
        self.swaps = JL(os.path.join(RUN, "swaps.jsonl"))
        self.batches = []            # applied batches: {files: {name: fiber}, names: {...}}
        self.live_files = {}         # file name -> fiber (kept versions)
        self.tree = None
        self.tree_uid = None
        self.request = None          # files from the agent waiting to be applied
        self.report_q = []           # reports waiting for the agent
        self.agent_busy = False
        self.stop = False
        self.done = False
        self.n_calls = 0
        self.t0 = time.monotonic()
        self.messages = [{"role": "system", "content": SYSTEM}]
        self.safety_prev_in = False
        self.run_log = []            # per-program-run records
        self.cur_run = None
        self.trial = None            # current batch on trial
        self.ev_i = 0
        self.procs = []
        self.skill_start, self.skill_effect = {}, {}

    # ---------------------------------------------------------- perception
    def scene(self):
        return kitchen.read_scene()

    def goals(self):
        try:
            g = json.load(open("/dev/shm/rtvla_scene.json"))["goals"]
        except Exception:  # noqa: BLE001
            return {k: False for k in GOAL_CHECK}
        return {k: bool(g.get(k)) for k in GOAL_CHECK}

    def scene_text(self):
        sc = self.scene()
        pos = "\n".join(f"  {k}: [{v[0]:.3f}, {v[1]:.3f}, {v[2]:.3f}]" for k, v in sc.objects.items())
        facts = "\n".join("  " + " ".join(f) for f in sc.facts) or "  (none)"
        return (f"Object positions:\n{pos}\nObserved facts:\n{facts}\n"
                f"Gripper at [{sc.eef[0]:.3f}, {sc.eef[1]:.3f}, {sc.eef[2]:.3f}], width {sc.gripper_width:.3f} m")

    def note_scene(self, ev):
        """Remember what each skill changed: objects moved > 1 cm, gripper width."""
        if ev[1] not in ("start", "success", "failure", "halt") or ev[2] == "main":
            return
        try:
            sc = self.scene()
        except Exception:  # noqa: BLE001
            return
        key = (ev[2], ev[4])
        if ev[1] == "start":
            self.skill_start[key] = (dict(sc.objects), sc.gripper_width)
            return
        s0 = self.skill_start.pop(key, None)
        if s0 is None:
            return
        moved = []
        for k, v in sc.objects.items():
            if k in s0[0] and sum((a - b) ** 2 for a, b in zip(v, s0[0][k])) ** 0.5 > 0.01:
                moved.append(f"{k} moved to [{v[0]:.3f}, {v[1]:.3f}, {v[2]:.3f}]")
        self.skill_effect[(ev[0], ev[2])] = (f"gripper width {s0[1]:.3f} -> {sc.gripper_width:.3f} m; "
                                            + ("; ".join(moved) if moved else "no object moved"))

    # ---------------------------------------------------------- idle point
    def idle(self):
        if self.ctx.running:
            return False
        self.ctx.vla_futs[:] = [f for f in self.ctx.vla_futs if not f.done()]
        if self.ctx.vla_futs:
            return False
        st = self.ctx.robot.get()
        for cid in (st["chunk_playing"], st["chunk_queued"]):
            rec = self.ctx.sent.get(cid) if cid else None
            if rec and st["tick"] - rec["start"] < len(rec["actions"]):
                return False
        return True

    # ---------------------------------------------------------- safety
    def safety(self):
        """Hot-stove rule. Detected here (Python, 10 Hz); enforced in Rust by revoking
        the moving skill's token. Fires while the gripper is inside the zone AND the
        command playing now moves it further in (down or toward the burner), so a
        skill can always move back out."""
        sc = self.scene()
        st = self.ctx.robot.get()
        e, c = st["pose"][:3], st["last_cmd"][:3]
        if not sc.holds("turnon", "flat_stove_1"):
            return False
        dx, dy = e[0] - COOK[0], e[1] - COOK[1]
        r = (dx * dx + dy * dy) ** 0.5
        inside = r < HOT_R and e[2] < COOK[2] + HOT_H
        inward = c[2] < -0.02 or (dx * c[0] + dy * c[1]) < -0.02 * max(r, 1e-6)
        own = self.ctx.ownership.snapshot()
        if inside and inward and own[1]:
            node = own[2]
            run = None
            for ev in reversed(self.ctx.events):
                if ev[1] == "start" and ev[2] == node:
                    run = ev[4]; break
            self.ctx.events.append((time.monotonic(), "safety_halt", node, None, run,
                                    f"hot-stove rule: gripper at [{e[0]:.3f}, {e[1]:.3f}, {e[2]:.3f}] moving further in"))
            self.ctx.revoke(own[1])       # Rust drops every chunk of this token at its next tick
            self.ctx.ownership.release(own[1])
            if self.tree is not None:
                self.tree.halt()
            return True
        return False

    # ---------------------------------------------------------- batches
    def load_batch(self, files):
        """Load every file beside the old versions. All or nothing."""
        loaded, names = {}, {}
        for fn, code in files.items():
            path = os.path.join(RUN, "plugins", f"{len(self.batches):02d}_{fn}")
            with open(path, "w") as f:
                f.write(code)
            before = {k: list(v) for k, v in self.ctx.registry.entries.items()}
            fib = self.cordis.load(path)
            if fib.state != ACTIVE:
                for f2 in loaded.values():
                    self.cordis.unload(f2)
                return None, f"{fn}: {fib.error}"
            loaded[fn] = fib
            after = self.ctx.registry.entries
            names[fn] = sorted(k for k in after if len(after[k]) > len(before.get(k, [])))
        return (loaded, names), None

    def go_live(self, loaded, names):
        """At an idle point: switch each registered name to its newest version."""
        old_live = dict(self.ctx.registry.live)
        for fn, ns in names.items():
            for n in ns:
                self.ctx.registry.set_live(n, self.ctx.registry.newest(n))
        if self.tree is not None:
            self.tree.halt()
        self.tree = None
        return old_live

    def rollback(self, trial):
        self.tree_halt()
        reg = self.ctx.registry
        for n, uid in trial["old_live"].items():
            if n in reg.entries and any(e[0] == uid for e in reg.entries[n]):
                reg.set_live(n, uid)
        for fib in trial["loaded"].values():
            self.cordis.unload(fib)

    def keep(self, trial):
        for fn, fib in trial["loaded"].items():
            old = self.live_files.get(fn)
            if old is not None:
                self.cordis.unload(old)
            self.live_files[fn] = fib
        # names replaced from other files: their old versions stay loaded but not live

    def tree_halt(self):
        if self.tree is not None:
            self.tree.halt()
        self.tree = None

    # ---------------------------------------------------------- runs + reports
    def early_reason(self, t_live, new_names):
        for ev in self.ctx.events[self.trial.get('ev0', 0):]:
            if ev[0] < t_live:
                continue
            if ev[1] == "error" and ev[2] in new_names:
                return "plugin_error", f"skill {ev[2]}: {str(ev[4]).strip()}"
            if ev[1] == "safety_halt":
                return "safety_halt", f"skill {ev[2]}: {ev[5]}"
            if ev[1] == "missing_skill":
                return "missing_skill", ev[5]
        for w in self.ctx.watchdog_fired:
            if w[3] >= t_live and w[0] in new_names:
                return "watchdog", w
        for n in new_names:
            if self.ctx.rust_rejected_by_node.get(n, 0) > self.trial["rust0"].get(n, 0):
                return "rust_rejected_chunk", n
        return None, None

    def run_summary(self, t_from):
        lines = []
        for ev in self.ctx.events:
            if ev[0] < t_from:
                continue
            t = ev[0] - self.t0
            if ev[1] in ("start", "success", "failure", "halt"):
                eff = self.skill_effect.get((ev[0], ev[2])) if ev[1] != "start" else None
                lines.append(f"  t={t:7.1f}s  {ev[2]} v{ev[3]}: {ev[1]}" + (f"  ({eff})" if eff else ""))
            elif ev[1] == "error":
                lines.append(f"  t={t:7.1f}s  {ev[2]} v{ev[3]}: ERROR {ev[4].strip()}")
            elif ev[1] == "safety_halt":
                lines.append(f"  t={t:7.1f}s  {ev[2]}: SAFETY HALT ({ev[5]})")
        vl = [v for v in self.ctx.vla_calls if v["t"] >= t_from]
        vtxt = "\n".join(f"  {v['node']}: \"{v['instruction']}\" -> {v['result'] or 'stopped'}"
                         + (f" after {v.get('steps')} steps" if v.get("steps") is not None else "")
                         + (" (done() was already true at the start; the policy never ran)"
                            if v.get("result") == "done" and v.get("steps") == 0 else "") for v in vl)
        for m in self.ctx.move_log:
            if m["t"] >= t_from:
                lines.append(f"  {m['node']} v{m['version']}: step budget ran out; target {m['target']}, gripper reached {m['reached']}")
        if len(lines) > 60:
            lines = lines[:20] + [f"  ... ({len(lines) - 40} lines omitted) ..."] + lines[-20:]
        return "\n".join(lines) or "  (nothing ran)", vtxt or "  (none)"

    def report(self, kind, detail, t_from):
        ev_txt, vla_txt = self.run_summary(t_from)
        g = self.goals()
        txt = (f"## Report: {kind}\n{detail}\n\nWhat ran (skill, version, outcome):\n{ev_txt}\n\n"
               f"VLA calls:\n{vla_txt}\n\nCurrent scene:\n{self.scene_text()}\n\n"
               f"Elapsed: {time.monotonic() - self.t0:.0f} s. Robot program files now live: "
               f"{sorted(self.live_files) or 'none'}.")
        if self.live_files:
            src = "\n\n".join(f"### {fn} (live)\n```python\n{open(f.path).read()}```" for fn, f in sorted(self.live_files.items()))
            txt += "\n\nCurrent live files:\n" + src
        txt += "\n\nThe robot holds still until you send the next batch. Send a batch (it may just resend main with a higher VERSION) to run the program again."
        self.ev.w(ev="report", kind=kind, goals=g, text=txt)
        self.report_q.append(txt)

    # ---------------------------------------------------------- agent thread
    def agent_worker(self, first):
        try:
            self.messages.append({"role": "user", "content": first})
            while not self.stop:
                if self.n_calls >= A.max_calls:
                    self.ev.w(ev="agent_budget_exhausted"); return
                t = time.time()
                if A.fixed:
                    if self.n_calls:
                        return
                    content = "\n".join("```python\n" + open(f).read() + "```" for f in A.fixed.split(","))
                    reasoning, usage = "", {}
                else:
                    msgs = self.messages
                    if len(msgs) > 2 + 16:
                        msgs = msgs[:2] + [{"role": "user", "content": "(Earlier exchanges omitted to save space; the current live files are listed in the latest report.)"},
                                           {"role": "assistant", "content": "Understood."}] + msgs[-16:]
                    content, reasoning, usage = call_llm(msgs, A.model)
                self.n_calls += 1
                self.messages.append({"role": "assistant", "content": content})
                files = extract_files(content)
                self.agent_log.w(call=self.n_calls, t_rel=time.monotonic() - self.t0, latency=time.time() - t,
                                 prompt=self.messages[-2]["content"], content=content, reasoning=reasoning,
                                 usage=usage, files=sorted(files))
                if not files:
                    msg = "Your reply contained no files. Reply with at least one '# file: <name>.py' block."
                    self.messages.append({"role": "user", "content": msg}); continue
                self.request = files
                # wait for the runtime's report on this batch
                while not self.report_q and not self.stop:
                    time.sleep(0.2)
                if self.stop:
                    return
                self.messages.append({"role": "user", "content": self.report_q.pop(0)})
        except Exception:  # noqa: BLE001
            self.ev.w(ev="agent_crash", tb=traceback.format_exc())
            self.stop = True

    # ---------------------------------------------------------- main loop
    async def main(self):
        ctx = self.ctx
        self.bridge.start()
        while ctx.robot.get() is None or self.bridge.next_id is None:
            await asyncio.sleep(0.01)
        kitchen.HOME_ORI = list(ctx.robot.get()["pose"][3:6])
        first = (f"{API}\n## Goal\n{GOAL}\n\n## What the robot perceives now\n{self.scene_text()}\n\n"
                 "Plan the task and write the first version of the program.")
        threading.Thread(target=self.agent_worker, args=(first,), daemon=True).start()
        next_t = time.monotonic()
        t_end = self.t0 + A.minutes * 60
        state = "wait"
        while not self.stop:
          try:
            now = time.monotonic()
            if now > t_end:
                self.ev.w(ev="time_up"); break
            if self.procs and any(p.poll() is not None for p in self.procs):
                self.ev.w(ev="process_died", codes=[p.poll() for p in self.procs]); break
            # ---- a new batch from the agent
            if self.request is not None and state in ("wait",) and self.idle():
                files, self.request = self.request, None
                res, err = self.load_batch(files)
                self.swaps.w(ev="batch", n=len(self.batches), files=sorted(files), load_error=err)
                if err:
                    self.batches.append({"files": sorted(files), "result": "load_failed", "error": err})
                    self.report("batch rejected while loading (nothing changed)", f"Load error: {err}", now)
                else:
                    loaded, names = res
                    if "main" not in ctx.registry.live:
                        for f in loaded.values():
                            self.cordis.unload(f)
                        self.batches.append({"files": sorted(files), "result": "load_failed", "error": "no main"})
                        self.report("batch rejected", "No file registered \"main\" yet.", now)
                    else:
                        old_live = self.go_live(loaded, names)
                        new_names = {n for ns in names.values() for n in ns}
                        self.trial = {"loaded": loaded, "names": names, "new_names": new_names,
                                      "old_live": old_live, "t_live": time.monotonic(),
                                      "goals_before": sum(self.goals().values()),
                                      "rust0": dict(ctx.rust_rejected_by_node), "files": sorted(files),
                                      "ev0": len(ctx.events)}
                        self.safety_prev_in = False
                        self.batches.append({"files": sorted(files), "names": names, "t_live": self.trial["t_live"] - self.t0})
                        self.swaps.w(ev="live", n=len(self.batches) - 1, names=names, t_rel=self.trial["t_live"] - self.t0)
                        state = "run"
            # ---- run the program
            if state == "run":
                if self.tree is None:
                    v, build = ctx.registry.lookup("main")
                    try:
                        self.tree = build()
                        self.tree_v = v
                        missing = sorted(n for n in leaf_names(self.tree) if n not in ctx.registry.live)
                        if missing:
                            ctx.events.append((time.monotonic(), "missing_skill", "main", v, None,
                                               f"main's tree uses skills that are not registered: {missing}"))
                        self.run_t = time.monotonic()
                        ctx.events.append((time.monotonic(), "program_start", "main", v, None))
                    except Exception:  # noqa: BLE001
                        ctx.events.append((time.monotonic(), "error", "main", v, traceback.format_exc(limit=2), None))
                        self.tree = None
                        status = FAILURE
                if self.tree is not None:
                    ctx.driving_now = False
                    try:
                        status = self.tree.tick(ctx, {"robot": ctx.robot.get()})
                    except Exception:  # noqa: BLE001
                        ctx.events.append((time.monotonic(), "error", "main", self.tree_v, traceback.format_exc(limit=2), None))
                        status = FAILURE
                    if not ctx.driving_now and ctx.ownership.owner != 0:
                        ctx.ownership.release(ctx.ownership.token)
                        ctx.inbox.put_owner_none()
                    self.safety()
                reason, detail = self.early_reason(self.trial["t_live"], self.trial["new_names"]) if self.trial else (None, None)
                g = self.goals()
                if all(g.values()) and status != RUNNING:
                    status = "goal"
                if reason or status != RUNNING:
                    self.tree_halt()
                    if ctx.ownership.owner != 0:
                        ctx.ownership.release(ctx.ownership.token); ctx.inbox.put_owner_none()
                    t_w = time.monotonic()
                    while not self.idle() and time.monotonic() - t_w < 20:
                        self.safety()
                        await asyncio.sleep(0.05)
                    if not self.idle():
                        self.ev.w(ev="idle_wait_timeout", running=sorted(ctx.running))
                        ctx.running.clear(); ctx.vla_futs.clear()
                    tr = self.trial
                    gnow = sum(self.goals().values())
                    progress = gnow > tr["goals_before"]
                    if reason:
                        result = "rolled_back"
                        why = f"Early reject: {reason}: {detail}"
                    elif status == "goal" or progress:
                        result = "kept"
                        why = "The task giver sees progress toward the goal."
                    else:
                        result = "rolled_back"
                        why = f"The program ended with {status} and the task giver sees no progress toward the goal."
                    if result == "kept":
                        self.keep(tr)
                    else:
                        self.rollback(tr)
                    self.batches[-1].update(result=result, reason=reason, status=status, goals=gnow,
                                            t_done=time.monotonic() - self.t0)
                    self.swaps.w(ev="trial_done", n=len(self.batches) - 1, result=result, reason=reason,
                                 status=status, goals=self.goals(), t_rel=time.monotonic() - self.t0)
                    self.trial = None
                    state = "wait"
                    if status == "goal" and all(self.goals().values()):
                        self.ev.w(ev="goal_reached", t_rel=time.monotonic() - self.t0)
                        self.done = True
                        self.stop = True
                        break
                    kind = ("batch kept" if result == "kept" else "batch rolled back")
                    self.report(kind, why + f"\nProgram run result: {status}.", tr["t_live"])
            else:
                # no program running: hold
                if ctx.ownership.owner != 0:
                    ctx.ownership.release(ctx.ownership.token); ctx.inbox.put_owner_none()
            # ---- periodic event dump
            for ev in ctx.events[self.ev_i:]:
                self.note_scene(ev)
                self.ev.w(ev="rt", t_rel=ev[0] - self.t0, kind=ev[1], node=ev[2], version=ev[3],
                          extra=[str(x) for x in ev[4:]])
            self.ev_i = len(ctx.events)
            next_t += 0.1
            await asyncio.sleep(max(0.0, next_t - time.monotonic()))
          except PluginHung:
              self.ev.w(ev="stray_pluginhung", tb=traceback.format_exc())
        self.stop = True


def main():
    if not A.fixed:
        c, r, u = call_llm([{"role": "user", "content": "Reply OK."}], A.model)
        print("llm ok:", c[:20], flush=True)
    plant, rust = launch()
    rt = AgentRuntime()
    rt.procs = [plant, rust]
    meta = {"goal": GOAL, "goal_check": GOAL_CHECK, "tick_ms": A.tick_ms, "model": A.model,
            "task_scene": A.task, "init": A.init, "t_start": time.time()}
    json.dump(meta, open(os.path.join(RUN, "meta.json"), "w"), indent=1)
    try:
        asyncio.run(rt.main())
    finally:
        rt.stop = True
        rt.bridge.stop_flag = True
        time.sleep(0.3)
        rt.bridge.quit_rust()
        try:
            rust.wait(timeout=30); plant.wait(timeout=120)
        except Exception:  # noqa: BLE001
            plant.kill()
        json.dump({"batches": rt.batches, "done": rt.done, "calls": rt.n_calls,
                   "vla_calls": rt.ctx.vla_calls, "vla_times": rt.ctx.vla_times,
                   "goals": rt.goals(), "t_total": time.monotonic() - rt.t0,
                   "watchdog": [list(map(str, w)) for w in rt.ctx.watchdog_fired]},
                  open(os.path.join(RUN, "summary.json"), "w"), indent=1, default=str)
        print("done", rt.done, "calls", rt.n_calls, flush=True)


if __name__ == "__main__":
    main()
