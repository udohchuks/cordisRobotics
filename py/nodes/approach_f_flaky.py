"""Faulty repair: correct on most cube positions, 3 cm off on a fraction p of them
(p from RTVLA_FLAKY_P), decided per episode from the seen cube position."""
import os
import random

from basics import MoveTo

VERSION = 2
P = float(os.environ.get("RTVLA_FLAKY_P", "0.3"))


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        bad = random.Random(round(c[0], 6) * 1e6 + round(c[1], 6) * 1e3).random() < P
        return [[c[0] + (0.03 if bad else 0.0), c[1], c[2] + self.s["handoff_height"]]]


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
