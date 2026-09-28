"""Faulty repair: raises inside tick() right after its first chunk was sent,
so the chunk is already in Rust when the node dies."""
from basics import MoveTo

VERSION = 2


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0], c[1], c[2] + self.s["handoff_height"]]]

    def tick(self, snap):
        st = super().tick(snap)
        if self.chunk is not None and self.chunk.get("sent_id"):
            raise KeyError("planted bug: raised after sending")
        return st


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
