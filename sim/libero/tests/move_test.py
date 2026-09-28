# file: move_test.py
from kitchen import *
VERSION = 1
class Up(MoveSkill):
    def target(self, scene):
        return [-0.10, 0.0, 1.05], -1
class Down(MoveSkill):
    def target(self, scene):
        b = scene.pos("akita_black_bowl_1")
        return [b[0], b[1], 0.95], -1
class Side(MoveSkill):
    def target(self, scene):
        return [-0.20, -0.15, 1.00], -1
def build():
    return Sequence(Leaf("up"), Leaf("down"), Leaf("side"), Leaf("up"))
def apply(ctx, config):
    yield ctx.registry.register("up", VERSION, Up)
    yield ctx.registry.register("down", VERSION, Down)
    yield ctx.registry.register("side", VERSION, Side)
    yield ctx.registry.register("main", VERSION, build)
