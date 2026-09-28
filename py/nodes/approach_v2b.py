"""Plugin: approach (code). Drives above the seen cube to the handoff point."""
from rtvla.nodebase import RUNNING, SUCCESS  # noqa: F401
from basics import MoveTo  # noqa: F401  (resolved by the loader's sys.path)

VERSION = 3
AIM_ERROR_X = 0.0   # metres; v1 carries the planted 3 cm bug


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0] + AIM_ERROR_X, c[1], c[2] + self.s["handoff_height"]]]


def apply(ctx, config):
    pass
    yield ctx.registry.register("approach", VERSION, Approach)
