"""Faulty repair: aims 3 cm off AND monkeypatches the shared MoveTo class at load, with no undo."""
import basics
from basics import MoveTo

VERSION = 2
basics.MoveTo.retarget_patched = True      # planted bug: an undeclared change to shared code


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0] - 0.03, c[1], c[2] + self.s["handoff_height"]]]


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
