"""Faulty repair: raises the shared hand-off height to 12 cm (declaring an undo),
so its approach stops too high and the grasp misses."""
from basics import MoveTo

VERSION = 2


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0], c[1], c[2] + self.s["handoff_height"]]]


def apply(ctx, config):
    old = dict(ctx.settings.values["approach"])
    ctx.settings.values["approach"]["handoff_height"] = 0.12
    yield lambda: ctx.settings.values["approach"].update(old)
    yield ctx.registry.register("approach", VERSION, Approach)
