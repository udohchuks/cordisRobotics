"""Faulty repair: aims 1 m away, far outside the workspace."""
from basics import MoveTo

VERSION = 2


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0] + 1.0, c[1], c[2] + self.s["handoff_height"]]]


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
