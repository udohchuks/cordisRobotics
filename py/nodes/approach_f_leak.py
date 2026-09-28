"""Faulty repair: aims 3 cm off AND starts a thread without declaring an undo."""
import threading
import time

from basics import MoveTo

VERSION = 2


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0] - 0.03, c[1], c[2] + self.s["handoff_height"]]]


def apply(ctx, config):
    threading.Thread(target=lambda: time.sleep(3600), daemon=True).start()   # no undo
    yield ctx.registry.register("approach", VERSION, Approach)
