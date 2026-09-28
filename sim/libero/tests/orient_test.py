# file: orient_test.py
from kitchen import *
VERSION = 1
class Twist(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 40
class Home(MoveSkill):
    ORIENT = "down"
    MAX_STEPS = 120
    def target(self, scene):
        return [-0.10, 0.0, 1.05], -1
class Far(MoveSkill):
    ORIENT = "down"
    MAX_STEPS = 120
    def target(self, scene):
        return [-0.25, -0.10, 1.00], -1
def build():
    return Sequence(Fallback(Leaf("twist"), Leaf("home")), Leaf("home"), Leaf("far"))
def apply(ctx, config):
    yield ctx.registry.register("twist", VERSION, Twist)
    yield ctx.registry.register("home", VERSION, Home)
    yield ctx.registry.register("far", VERSION, Far)
    yield ctx.registry.register("main", VERSION, build)
