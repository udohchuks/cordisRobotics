"""Faulty repair: sends actions containing NaN (e.g. a division by zero)."""
from basics import MoveTo
from rtvla.nodebase import plan_path

VERSION = 2


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0], c[1], c[2] + self.s["handoff_height"]]]

    def send(self, snap, wps):
        ch = plan_path(self.ctx, snap, wps, self.grip(snap), self.s.get("speed", 0.2), D=self.ctx.D,
                       token=self.token, node=self.name, version=self.version, run=self.run, owner=1)
        for a in ch["actions"][5:]:
            a[0] = float("nan")                       # planted bug
        self.chunk = ch
        self.ctx.inbox.put(ch)


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
