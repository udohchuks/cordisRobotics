"""Fixed library for agent-written plugins (never swapped).

Plugins import from here: the scene view, three skill base classes
(VLASkill, MoveSkill, Check) and the behavior-tree building blocks.
Skills never touch shared memory; they hand chunks to the runtime's inbox,
which only accepts chunks from the node that currently owns the arm.
"""
import json
import math
import os
import time

from rtvla.nodebase import NodeBase
from rtvla.tree import (RUNNING, SUCCESS, FAILURE, Leaf, Sequence, Fallback,  # noqa: F401
                        Retry, Timeout, ReactiveSequence)

SCENE_JSON = os.environ.get("RTVLA_SCENE_JSON", "/dev/shm/rtvla_scene.json")
POS_SCALE = 0.05     # LIBERO: a position command of 1.0 moves the goal 5 cm
ROT_SCALE = 0.5      # LIBERO: a rotation command of 1.0 turns the goal 0.5 rad
HOME_ORI = None      # axis-angle of the gripper at the start of the run (pointing down); set by the runtime


def _aa2mat(aa):
    import numpy as np
    aa = np.asarray(aa, float); th = np.linalg.norm(aa)
    if th < 1e-9:
        return np.eye(3)
    k = aa / th; K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K


def _mat2aa(R):
    import numpy as np
    c = max(-1.0, min(1.0, (np.trace(R) - 1) / 2)); th = np.arccos(c)
    if th < 1e-6:
        return np.zeros(3)
    if abs(th - np.pi) < 1e-3:
        w, v = np.linalg.eigh((R + np.eye(3)) / 2)
        return v[:, -1] * th
    return np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) * th / (2 * np.sin(th))


def rot_error(cur_aa, target_aa):
    """World-frame rotation (axis-angle) that turns the current orientation into the target."""
    return _mat2aa(_aa2mat(target_aa) @ _aa2mat(cur_aa).T)


class Scene:
    """What the robot perceives: object positions, symbolic facts, gripper."""

    def __init__(self, d):
        self.d = d
        self.objects = d.get("objects", {})
        self.facts = [tuple(f) for f in d.get("facts", [])]
        e = d.get("eef", [0.0] * 7)
        self.eef = e[:3]
        self.gripper_width = e[6]
        self.step = d.get("step", 0)

    def pos(self, name):
        return list(self.objects[name])

    def holds(self, pred, a, b=None):
        return ((pred, a, b) if b is not None else (pred, a)) in self.facts


def read_scene(path=SCENE_JSON):
    for _ in range(5):
        try:
            with open(path) as f:
                return Scene(json.load(f))
        except (OSError, ValueError):
            time.sleep(0.002)
    raise RuntimeError("scene unavailable")


class Skill(NodeBase):
    """Common part: the scene, a step budget, and a chunk sender."""
    DRIVES = True
    MAX_STEPS = 200

    def start(self, snap):
        super().start(snap)
        self.steps0 = self.ctx.robot.get()["tick"]
        self.chunk = None

    def scene(self):
        return read_scene()

    def steps_used(self):
        return self.ctx.robot.get()["tick"] - self.steps0

    def pending(self):
        """True while my last chunk is queued or still has steps to play."""
        if self.chunk is None:
            return False
        st = self.ctx.robot.get()
        return st["tick"] < self.chunk["start"] + len(self.chunk["actions"])

    def send(self, actions):
        st = self.ctx.robot.get()
        self.chunk = {"token": self.token, "node": self.name, "version": self.version, "run": self.run,
                      "owner": self.OWNER, "start": st["tick"] + 1, "built_on": st["chunk_playing"],
                      "actions": [list(map(float, a)) for a in actions]}
        self.ctx.inbox.put(self.chunk)


class VLASkill(Skill):
    """Runs the learned policy on INSTRUCTION until done(scene) is true.
    Subclass: set INSTRUCTION (short English), MAX_STEPS, and define done(scene).
    FAILURE if the step budget runs out first."""
    OWNER = 2
    INSTRUCTION = ""
    MAX_STEPS = 300

    def done(self, scene):
        return False

    def start(self, snap):
        super().start(snap)
        self.fut = None
        self.acts_sent = 0      # policy actions played so far (the budget counts these, not ticks)
        self.ctx.vla_calls.append({"t": time.monotonic(), "node": self.name, "version": self.version,
                                   "run": self.run, "instruction": self.INSTRUCTION, "result": None})
        self.rec = self.ctx.vla_calls[-1]

    def tick(self, snap):
        sc = self.scene()
        if self.done(sc) and not self.pending():
            self.rec["result"] = "done"; self.rec["steps"] = self.acts_sent
            return SUCCESS
        if self.acts_sent >= self.MAX_STEPS and self.fut is None and not self.pending():
            self.rec["result"] = "budget_exhausted"; self.rec["steps"] = self.acts_sent
            return FAILURE
        if self.fut is None and not self.pending():
            obs, tick, _ = self.ctx.obs_reader.read()
            if self.chunk is not None and tick is not None and tick < self.chunk["start"] + len(self.chunk["actions"]) - 1:
                return RUNNING     # the plant has not applied my last action yet: wait for a fresh frame
            self.fut = self.ctx.workers.submit(self.ctx.vla.infer, obs, self.INSTRUCTION)
            self.ctx.vla_futs.append(self.fut)     # the idle point waits for these
        if self.fut is not None and self.fut.done():
            fut, self.fut = self.fut, None
            acts, dt = fut.result()
            self.ctx.vla_times.append(dt)
            if self.ctx.ownership.check(self.token):
                self.send(acts)
                self.acts_sent += len(acts)
        return RUNNING

    def halt(self):
        self.fut = None   # a reply still in flight is dropped (its token is revoked)


class MoveSkill(Skill):
    """Moves the gripper in a straight line to target(scene) -> ([x, y, z], gripper),
    gripper -1 = open, +1 = closed. Keeps the gripper's orientation.
    SUCCESS within TOL metres; FAILURE if MAX_STEPS run out.
    ORIENT = "keep" keeps the gripper's current orientation; "down" also turns it back
    to the orientation it had at the start of the run (pointing straight down)."""
    OWNER = 1
    TOL = 0.02
    MAX_STEPS = 80
    ORIENT = "keep"

    def target(self, scene):
        raise NotImplementedError

    def tick(self, snap):
        sc = self.scene()
        xyz, grip = self.target(sc)
        st = self.ctx.robot.get()
        eef = st["pose"][:3]               # live from Rust each tick
        d = [xyz[i] - eef[i] for i in range(3)]
        ori_ok = True
        if self.ORIENT == "down" and HOME_ORI is not None:
            import numpy as np
            ori_ok = float(np.linalg.norm(rot_error(st["pose"][3:6], HOME_ORI))) < 0.1
        if math.dist(xyz, eef) < self.TOL and ori_ok:
            self.near = getattr(self, "near", 0) + 1
            if self.near >= 2:
                return SUCCESS
        else:
            self.near = 0
        self.last = (list(xyz), list(eef))
        if self.steps_used() > self.MAX_STEPS:
            self.ctx.move_log.append({"t": time.monotonic(), "node": self.name, "version": self.version,
                                      "target": [round(v, 3) for v in xyz], "reached": [round(v, 3) for v in eef]})
            return FAILURE
        if not self.pending() or self.chunk["start"] + len(self.chunk["actions"]) - st["tick"] <= 1:
            rot = [0.0, 0.0, 0.0]
            if self.ORIENT == "down" and HOME_ORI is not None:
                rot = [max(-1.0, min(1.0, float(r) / ROT_SCALE)) for r in rot_error(st["pose"][3:6], HOME_ORI)]
            a = [max(-1.0, min(1.0, di / POS_SCALE)) for di in d] + rot + [float(grip)]
            self.send([a, a])
        return RUNNING


class Gripper(Skill):
    """Opens (-1) or closes (+1) the gripper in place: set GRIP."""
    OWNER = 1
    GRIP = -1.0
    STEPS = 6

    def tick(self, snap):
        if self.chunk is None:
            self.send([[0, 0, 0, 0, 0, 0, self.GRIP]] * self.STEPS)
        return RUNNING if self.pending() else SUCCESS


class Check(NodeBase):
    """A condition: define ok(scene); SUCCESS if true else FAILURE."""

    def ok(self, scene):
        return True

    def tick(self, snap):
        return SUCCESS if self.ok(read_scene()) else FAILURE
