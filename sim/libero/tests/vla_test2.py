# file: vla_test2.py
from kitchen import *
VERSION = 1
class BowlStove(VLASkill):
    INSTRUCTION = "put the bowl on the stove"
    MAX_STEPS = 300
    def done(self, scene):
        return scene.holds("on", "akita_black_bowl_1", "flat_stove_1_cook_region")
class StoveOn(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 300
    def done(self, scene):
        return scene.holds("turnon", "flat_stove_1")
class BottleRack(VLASkill):
    INSTRUCTION = "put the wine bottle on the rack"
    MAX_STEPS = 300
    def done(self, scene):
        return scene.holds("on", "wine_bottle_1", "wine_rack_1_top_region")
def build():
    return Sequence(Leaf("bowl_stove"), Leaf("bottle_rack"), Leaf("stove_on"))
def apply(ctx, config):
    yield ctx.registry.register("bowl_stove", VERSION, BowlStove)
    yield ctx.registry.register("stove_on", VERSION, StoveOn)
    yield ctx.registry.register("bottle_rack", VERSION, BottleRack)
    yield ctx.registry.register("main", VERSION, build)
