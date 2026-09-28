# file: bowl_only.py
from kitchen import *
VERSION = 1
class BowlStove(VLASkill):
    INSTRUCTION = "put the bowl on the stove"
    MAX_STEPS = 300
    def done(self, scene):
        return scene.holds("on", "akita_black_bowl_1", "flat_stove_1_cook_region")
def build():
    return Retry(2, Leaf("bowl_stove"))
def apply(ctx, config):
    yield ctx.registry.register("bowl_stove", VERSION, BowlStove)
    yield ctx.registry.register("main", VERSION, build)
