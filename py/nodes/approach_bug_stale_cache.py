"""Plugin: approach (code). Drives above the seen cube to the handoff point."""
from basics import MoveTo

VERSION = 1
_target = {}


class Approach(MoveTo):
    def waypoints(self, snap):
        if "cube" not in _target:
            _target["cube"] = list(self.ctx.blackboard.get("cube_seen"))
        c = _target["cube"]
        return [[c[0], c[1], c[2] + self.s["handoff_height"]]]


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
