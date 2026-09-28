"""Faulty repair: blocks the event loop for 0.3 s on every tick (below the watchdog limit)."""
import time

from basics import MoveTo

VERSION = 2


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0], c[1], c[2] + self.s["handoff_height"]]]

    def tick(self, snap):
        time.sleep(0.3)
        return super().tick(snap)


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
