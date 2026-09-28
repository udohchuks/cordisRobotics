"""Plugin: approach (code). Drives above the seen cube to the handoff point."""
from basics import MoveTo

VERSION = 1


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0] + 0.03, c[1], c[2] + self.s["handoff_height"]]]


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
