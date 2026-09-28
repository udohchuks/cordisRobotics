"""Plugin: the basic nodes of the pick-and-place tree (all but approach)."""
import math
import time

from rtvla.nodebase import NodeBase, plan_path, pose, RUNNING, SUCCESS, FAILURE

VERSION = 1
import json as _json, os as _os
HOME = _json.loads(_os.environ.get("RTVLA_HOME", "[0.0, 0.0, 0.15]"))


# ---------------------------------------------------------------- conditions
class Perceive(NodeBase):
    """Camera stub: reads the sim's cube position into the blackboard."""
    def tick(self, snap):
        self.ctx.blackboard.set("cube_seen", list(snap["world"]["cube"]))
        return SUCCESS


class CubeNearSeen(NodeBase):
    def tick(self, snap):
        seen = self.ctx.blackboard.get("cube_seen")
        now = snap["world"]["cube"]
        if math.dist(seen[:2], now[:2]) > self.s["moved_threshold"]:
            return FAILURE
        return SUCCESS


class CubeInGripper(NodeBase):
    """Sim ground truth in the toy sim (real arm: gripper stopped short)."""
    def tick(self, snap):
        return SUCCESS if snap["robot"]["cube_attached"] else FAILURE


class CubeInBowl(NodeBase):
    def tick(self, snap):
        return SUCCESS if snap["robot"]["successes"] > self.ctx.blackboard.get("succ0", 0) else FAILURE


# ---------------------------------------------------------------- code motion
class MoveTo(NodeBase):
    """Shared logic for code nodes that drive to waypoints."""
    DRIVES = True
    OWNER = 1

    def waypoints(self, snap):
        raise NotImplementedError

    def grip(self, snap):
        return snap["robot"]["last_cmd"][6]  # copy the gripper forward

    def start(self, snap):
        super().start(snap)
        self.chunk = None
        self.near = 0

    def send(self, snap, wps):
        self.chunk = plan_path(self.ctx, snap, wps, self.grip(snap), self.s.get("speed", 0.2),
                               D=self.ctx.D, token=self.token, node=self.name,
                               version=self.version, run=self.run, owner=self.OWNER)
        self.ctx.inbox.put(self.chunk)

    def tick(self, snap):
        wps = self.waypoints(snap)
        goal = wps[-1]
        if self.chunk is None or math.dist(goal, self.chunk["target"]) > self.s.get("retarget", 0.005):
            self.send(snap, wps)
        if math.dist(pose(snap), goal) < self.s.get("tol", 0.005):
            self.near += 1
            if self.near >= 2:
                return SUCCESS
        else:
            self.near = 0
        return RUNNING


class Carry(MoveTo):
    def waypoints(self, snap):
        p = pose(snap) if self.chunk is None else self.chunk["_first"]
        bowl = snap["robot"]["bowl"]
        h = self.s["carry_height"]
        return [[p[0], p[1], h], [bowl[0], bowl[1], h]]

    def send(self, snap, wps):
        super().send(snap, wps)
        self.chunk["_first"] = pose(snap)


class Retreat(MoveTo):
    def waypoints(self, snap):
        return [HOME]


class Recover(MoveTo):
    def grip(self, snap):
        return 0.0

    def waypoints(self, snap):
        p = pose(snap) if self.chunk is None else self.chunk["_first"]
        return [[p[0], p[1], p[2] + 0.05]]

    def send(self, snap, wps):
        super().send(snap, wps)
        self.chunk["_first"] = pose(snap)


class Place(MoveTo):
    """Lower over the bowl; the gripper may open only above the bowl."""
    def start(self, snap):
        super().start(snap)
        self.phase = "lower"
        self.rel0 = snap["robot"]["releases"]

    def waypoints(self, snap):
        bowl = snap["robot"]["bowl"]
        return [[bowl[0], bowl[1], bowl[2] + self.s["release_height"]]]

    def grip(self, snap):
        return 1.0 if self.phase == "lower" else 0.0

    def tick(self, snap):
        if self.phase == "lower":
            st = super().tick(snap)
            if st == SUCCESS:
                bowl = snap["robot"]["bowl"]
                if math.dist(pose(snap)[:2], bowl[:2]) > 0.01:
                    return FAILURE               # guard: never open elsewhere
                self.phase = "open"
                self.send(snap, self.waypoints(snap))
            return RUNNING
        if snap["robot"]["releases"] > self.rel0:
            return SUCCESS
        return RUNNING


# ---------------------------------------------------------------- VLA grasp
_vla_conn = {}


def fake_vla(p, stall, seconds, gil_n, prefix, local=False):
    """Stand-in for a remote SmolVLA call: descend 5 cm, close, hold."""
    import os  # noqa: F811
    addr = os.environ.get("RTVLA_VLA_SERVER")
    if addr and not local and stall == "sleep":
        # the VLA lives in its own persistent process (see rtvla/vla_server.py)
        import threading
        from multiprocessing.connection import Client
        if "c" not in _vla_conn:
            _vla_conn["c"], _vla_conn["lock"] = Client(addr, family="AF_UNIX"), threading.Lock()
        with _vla_conn["lock"]:
            _vla_conn["c"].send((list(p), seconds, prefix))
            return _vla_conn["c"].recv()
    if stall == "smolvla":
        from rtvla import real_vla
        real_vla.infer()                         # real model inference on CPU
    elif stall == "gil":
        import re
        re.match(r"(a+)+$", "a" * gil_n + "b")   # holds the GIL
    else:
        time.sleep(seconds)                      # releases the GIL
    # RTC-style prefix: the steps covering the expected delay stay where the
    # arm already is (the committed part), then the motion starts.
    acts = [[p[0], p[1], p[2], 0, 0, 0, 0.0]] * prefix
    nd = int(os.environ.get("RTVLA_VLA_DESCENT_STEPS", "15"))
    for k in range(1, nd + 1):
        acts.append([p[0], p[1], p[2] - 0.05 * k / nd, 0, 0, 0, 0.0])
    bottom = acts[-1][:6]
    acts += [bottom + [0.0]] * 2
    acts += [bottom + [1.0]] * 12
    return acts[:50]


class VlaGrasp(NodeBase):
    DRIVES = True
    OWNER = 2

    def start(self, snap):
        super().start(snap)
        st = snap["robot"]
        self.b = st["tick"]
        self.built_on = st["chunk_queued"] or st["chunk_playing"]
        self.first_closed = None
        self.delivered = False
        v = self.ctx.vla
        self.ctx.vla_inflight += 1
        prefix = int(v.get("expected_delay", v["delay"]) / 0.033) + 4
        self.fut = self.ctx.workers.submit(fake_vla, pose(snap), v["stall"], v["delay"], v["gil_n"], prefix)
        self.fut.add_done_callback(lambda f: self._done())

    def _done(self):
        self.ctx.vla_inflight -= 1

    def tick(self, snap):
        st = snap["robot"]
        if not self.delivered and self.fut.done():
            self.delivered = True
            acts = self.fut.result()
            ch = {"token": self.token, "node": self.name, "version": self.version, "run": self.run,
                  "owner": 2, "start": self.b, "built_on": self.built_on, "actions": acts,
                  "target": acts[-1][:3]}
            self.ctx.inbox.put(ch)   # rejected if our token was cancelled
            self.chunk = ch
        if self.delivered and st["last_cmd"][6] >= 0.5 and st["chunk_playing"] == self.chunk.get("sent_id"):
            if self.first_closed is None:
                self.first_closed = st["tick"]
            if st["tick"] - self.first_closed >= self.s["closed_ticks"]:
                return SUCCESS
        return RUNNING


def apply(ctx, config):
    for name, cls in [("perceive", Perceive), ("cube_near_seen", CubeNearSeen),
                      ("cube_in_gripper", CubeInGripper), ("cube_in_bowl", CubeInBowl),
                      ("carry", Carry), ("retreat", Retreat), ("recover", Recover),
                      ("place", Place), ("vla_grasp", VlaGrasp)]:
        yield ctx.registry.register(name, VERSION, cls)
