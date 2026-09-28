"""Faulty repair: stamps its chunks with a token it does not own."""
from basics import MoveTo
from rtvla.nodebase import plan_path

VERSION = 2


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0], c[1], c[2] + self.s["handoff_height"]]]

    def send(self, snap, wps):
        ch = plan_path(self.ctx, snap, wps, self.grip(snap), self.s.get("speed", 0.2), D=self.ctx.D,
                       token=self.token + 1000, node=self.name, version=self.version, run=self.run, owner=1)
        self.chunk = ch                               # planted bug: token it does not own
        self.ctx.inbox.put(ch)


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
