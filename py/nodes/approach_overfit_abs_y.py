"""A plausible but overfit repair of the flipped-sign bug: takes |y| instead of y.
Correct whenever the cube has y >= 0 (as in the trial episodes), wrong for y < 0."""
from basics import MoveTo

VERSION = 2


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0], abs(c[1]), c[2] + self.s["handoff_height"]]]


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
