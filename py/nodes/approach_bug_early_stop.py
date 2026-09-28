"""Plugin: approach (code). Drives above the seen cube to the handoff point."""
import math

from basics import MoveTo
from rtvla.nodebase import RUNNING, SUCCESS

VERSION = 1


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0], c[1], c[2] + self.s["handoff_height"]]]

    def tick(self, snap):
        wps = self.waypoints(snap)
        if self.chunk is None:
            self.send(snap, wps)
        if math.dist(snap["robot"]["pose"][:3], wps[-1]) < 0.03:
            return SUCCESS
        return RUNNING


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
