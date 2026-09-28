# file: cook_setup.py
from kitchen import *

VERSION = 1

# ---------- checks ----------

class BottleOnRack(Check):
    def ok(self, scene):
        return scene.holds("on", "wine_bottle_1", "wine_rack_1_top_region")

class BowlOnStove(Check):
    def ok(self, scene):
        return scene.holds("on", "akita_black_bowl_1", "flat_stove_1_cook_region")

class StoveOn(Check):
    def ok(self, scene):
        return scene.holds("turnon", "flat_stove_1")

# ---------- manipulation skills ----------

class BottleToRack(VLASkill):
    INSTRUCTION = "put the wine bottle on the wine rack"
    MAX_STEPS = 400

    def done(self, scene):
        return scene.holds("on", "wine_bottle_1", "wine_rack_1_top_region")

class BowlToStove(VLASkill):
    INSTRUCTION = "put the black bowl on the stove"
    MAX_STEPS = 400

    def done(self, scene):
        return scene.holds("on", "akita_black_bowl_1", "flat_stove_1_cook_region")

class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 300

    def done(self, scene):
        return scene.holds("turnon", "flat_stove_1")

# ---------- registration ----------

def build():
    yield ctx.registry.register("bottle_on_rack", VERSION, BottleOnRack)
    yield ctx.registry.register("bowl_on_stove", VERSION, BowlOnStove)
    yield ctx.registry.register("stove_on", VERSION, StoveOn)
    yield ctx.registry.register("bottle_to_rack", VERSION, BottleToRack)
    yield ctx.registry.register("bowl_to_stove", VERSION, BowlToStove)
    yield ctx.registry.register("turn_on_stove", VERSION, TurnOnStove)

    return Sequence(
        Fallback(Leaf("bottle_on_rack"), Leaf("bottle_to_rack")),
        Fallback(Leaf("bowl_on_stove"), Leaf("bowl_to_stove")),
        Fallback(Leaf("stove_on"), Leaf("turn_on_stove")),
    )

yield ctx.registry.register("main", VERSION, build)
