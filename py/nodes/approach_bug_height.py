"""Plugin: approach (code). Drives above the seen cube to the handoff point."""
from basics import MoveTo

VERSION = 1


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        h = 0.12
        return [[c[0], c[1], c[2] + h]]


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
