"""Plugin: approach with a bug that throws inside tick() now and then (T1)."""
import random

from basics import MoveTo

VERSION = 2


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0], c[1], c[2] + self.s["handoff_height"]]]

    def tick(self, snap):
        if random.random() < 0.2:
            raise ValueError("planted bug: approach threw")
        return super().tick(snap)


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
