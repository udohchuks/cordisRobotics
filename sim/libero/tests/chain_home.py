# file: chain_home.py
from kitchen import *
VERSION = 1
START = [-0.207, 0.002, 1.178]
class BowlStove(VLASkill):
    INSTRUCTION = "put the bowl on the stove"
    MAX_STEPS = 300
    def done(self, scene):
        return scene.holds("on", "akita_black_bowl_1", "flat_stove_1_cook_region")
class Home(MoveSkill):
    ORIENT = "down"; MAX_STEPS = 150; TOL = 0.03
    def target(self, scene):
        return START, -1
class BottleRack(VLASkill):
    INSTRUCTION = "put the wine bottle on the rack"
    MAX_STEPS = 300
    def done(self, scene):
        return scene.holds("on", "wine_bottle_1", "wine_rack_1_top_region")
def build():
    return Sequence(Leaf("bowl_stove"), Leaf("home"), Retry(3, Sequence(Leaf("home"), Leaf("bottle_rack"))))
def apply(ctx, config):
    for n, c in [("bowl_stove", BowlStove), ("home", Home), ("bottle_rack", BottleRack)]:
        yield ctx.registry.register(n, VERSION, c)
    yield ctx.registry.register("main", VERSION, build)
