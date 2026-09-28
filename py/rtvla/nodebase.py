"""Helpers shared by node plugins: the node contract and chunk planning."""
import math

from .tree import RUNNING, SUCCESS, FAILURE  # noqa: F401

MAX_STEPS = 50
DT = 0.033


class NodeBase:
    DRIVES = False
    OWNER = 1  # 1 code, 2 vla

    def __init__(self, ctx, settings, name, version, run):
        self.ctx, self.s, self.name, self.version, self.run = ctx, settings, name, version, run
        self.token = None

    # contract --------------------------------------------------------------
    def start(self, snap):
        if self.DRIVES:
            self.token = self.ctx.ownership.take(self.OWNER, self.name)

    def tick(self, snap):
        return SUCCESS

    def halt(self):
        """Hook for plugin clean-up. The runtime revokes the token itself."""

    def finish(self):
        """Normal end: keep ownership (the next node takes it over directly)."""


def old_action_at(ctx, st, tick):
    """The action the arm will be told at `tick` by what is queued/playing."""
    for cid in (st["chunk_queued"], st["chunk_playing"]):
        rec = ctx.sent.get(cid) if cid else None
        if rec:
            i = tick - rec["start"]
            if 0 <= i < len(rec["actions"]):
                return list(rec["actions"][i]), cid
            if i >= len(rec["actions"]) and rec["actions"]:
                return list(rec["actions"][-1]), cid
    return list(st["last_cmd"]), (st["chunk_queued"] or st["chunk_playing"])


def plan_path(ctx, snap, waypoints, grip, speed, D=2, token=None, node="", version=0,
              run=0, owner=1, pad_to=MAX_STEPS):
    """Straight lines through waypoints at `speed`, starting from the old
    chunk's action at the start tick b + D; padded with holds at the end."""
    st = snap["robot"]
    b = st["tick"]
    start = b + D
    a0, built_on = old_action_at(ctx, st, start)
    pts = [a0[:3]] + [list(w) for w in waypoints]
    step = speed * DT
    acts = []
    cur = pts[0]
    for nxt in pts[1:]:
        d = math.dist(cur, nxt)
        n = max(1, int(math.ceil(d / step)))
        for k in range(1, n + 1):
            p = [cur[i] + (nxt[i] - cur[i]) * k / n for i in range(3)]
            acts.append(p + [0.0, 0.0, 0.0, grip])
        cur = nxt
    if not acts:
        acts.append(list(pts[-1]) + [0.0, 0.0, 0.0, grip])
    acts = acts[:MAX_STEPS]
    while len(acts) < pad_to:
        acts.append(list(acts[-1]))
    return {"token": token, "node": node, "version": version, "run": run, "owner": owner,
            "start": start, "built_on": built_on, "actions": acts, "target": list(pts[-1])}


def steps_left(st, sent_id, n):
    if st["chunk_queued"] == sent_id:
        return n
    if st["chunk_playing"] == sent_id and st["step_playing"] >= 0:
        return n - st["step_playing"] - 1
    return 0


def pose(snap):
    return snap["robot"]["pose"][:3]
