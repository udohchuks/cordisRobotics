# file: chain4.py
from kitchen import *
VERSION = 1
START = [-0.207, 0.002, 1.178]
class BowlStove(VLASkill):
    INSTRUCTION = "put the bowl on the stove"
    MAX_STEPS = 300
    def done(self, scene):
        return scene.holds("on", "akita_black_bowl_1", "flat_stove_1_cook_region")
class BottleRack(VLASkill):
    INSTRUCTION = "put the wine bottle on the rack"
    MAX_STEPS = 300
    def done(self, scene):
        return scene.holds("on", "wine_bottle_1", "wine_rack_1_top_region")
class Open(Gripper):
    GRIP = -1
class Up(MoveSkill):
    MAX_STEPS = 60; TOL = 0.03
    def start(self, snap):
        super().start(snap); self.goal = None
    def target(self, scene):
        if self.goal is None:
            e = scene.eef; self.goal = [e[0], e[1], max(e[2] + 0.12, 1.15)]
        return self.goal, -1
class Home(MoveSkill):
    ORIENT = "down"; MAX_STEPS = 150; TOL = 0.04
    def target(self, scene):
        return START, -1
class Ok(Check):
    pass
def build():
    return Sequence(Retry(2, Leaf("bottle_rack")), Leaf("open"), Fallback(Leaf("up"), Leaf("ok")),
                    Fallback(Leaf("home"), Leaf("ok")), Retry(3, Leaf("bowl_stove")))
def apply(ctx, config):
    for n, c in [("bowl_stove", BowlStove), ("bottle_rack", BottleRack), ("open", Open), ("up", Up), ("home", Home), ("ok", Ok)]:
        yield ctx.registry.register(n, VERSION, c)
    yield ctx.registry.register("main", VERSION, build)
