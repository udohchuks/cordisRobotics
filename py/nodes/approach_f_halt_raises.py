"""Faulty repair: correct motion, but its halt() raises and does no clean-up.
Run with a cube move during approach, so the node gets halted."""
from basics import MoveTo

VERSION = 2


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0], c[1], c[2] + self.s["handoff_height"]]]

    def halt(self):
        raise RuntimeError("planted bug: halt() crashed")


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
