# file: main.py
from kitchen import *

VERSION = 3

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
STOVE = "flat_stove_1"
COOK = "flat_stove_1_cook_region"
RACK = "wine_rack_1_top_region"


# ---------- conditions ----------

class BowlOnStoveCheck(Check):
    def ok(self, scene):
        x, y, z = scene.pos(BOWL)
        if scene.holds("on", BOWL, COOK):
            return True
        return abs(x + 0.254) < 0.06 and abs(y - 0.202) < 0.06 and z < 1.0


class StoveOnCheck(Check):
    def ok(self, scene):
        return scene.holds("turnon", STOVE)


class BottleOnRackCheck(Check):
    def ok(self, scene):
        return scene.holds("on", BOTTLE, RACK)


# ---------- approach moves ----------

class ApproachBowl(MoveSkill):
    ORIENT = "down"
    TOL = 0.03

    def target(self, scene):
        x, y, z = scene.pos(BOWL)
        return ([x, y, z + 0.18], -1)


class ApproachBottle(MoveSkill):
    ORIENT = "down"
    TOL = 0.03

    def target(self, scene):
        x, y, z = scene.pos(BOTTLE)
        return ([x, y, z + 0.18], -1)


class Retreat(MoveSkill):
    ORIENT = "down"
    TOL = 0.04

    def target(self, scene):
        return ([-0.02, 0.02, 1.18], -1)


# ---------- manipulation steps ----------

class PickBowl(VLASkill):
    INSTRUCTION = "pick up the black bowl"
    MAX_STEPS = 300

    def done(self, scene):
        return scene.pos(BOWL)[2] > 0.95


class PlaceBowlOnStove(VLASkill):
    INSTRUCTION = "put the black bowl on the stove"
    MAX_STEPS = 300

    def done(self, scene):
        x, y, z = scene.pos(BOWL)
        return abs(x + 0.254) < 0.07 and abs(y - 0.202) < 0.07 and z < 1.0


class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 300

    def done(self, scene):
        return scene.holds("turnon", STOVE)


class PickBottle(VLASkill):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 300

    def done(self, scene):
        return scene.pos(BOTTLE)[2] > 0.95


class PlaceBottleOnRack(VLASkill):
    INSTRUCTION = "put the wine bottle on the wine rack"
    MAX_STEPS = 300

    def done(self, scene):
        return scene.holds("on", BOTTLE, RACK)


class OpenGripper(Gripper):
    GRIP = -1


# ---------- behavior tree ----------

def build():
    return Sequence(
        Fallback(
            Leaf("bowl_on_stove_check"),
            Sequence(
                Leaf("approach_bowl"),
                Leaf("pick_bowl"),
                Leaf("place_bowl_on_stove"),
                Leaf("open_gripper"),
                Leaf("retreat"),
            ),
        ),
        Fallback(
            Leaf("stove_on_check"),
            Leaf("turn_on_stove"),
        ),
        Fallback(
            Leaf("bottle_on_rack_check"),
            Sequence(
                Leaf("approach_bottle"),
                Leaf("pick_bottle"),
                Leaf("place_bottle_on_rack"),
                Leaf("open_gripper"),
            ),
        ),
    )


def apply(ctx, config):
    yield ctx.registry.register("bowl_on_stove_check", VERSION, BowlOnStoveCheck)
    yield ctx.registry.register("stove_on_check", VERSION, StoveOnCheck)
    yield ctx.registry.register("bottle_on_rack_check", VERSION, BottleOnRackCheck)
    yield ctx.registry.register("approach_bowl", VERSION, ApproachBowl)
    yield ctx.registry.register("approach_bottle", VERSION, ApproachBottle)
    yield ctx.registry.register("retreat", VERSION, Retreat)
    yield ctx.registry.register("pick_bowl", VERSION, PickBowl)
    yield ctx.registry.register("place_bowl_on_stove", VERSION, PlaceBowlOnStove)
    yield ctx.registry.register("turn_on_stove", VERSION, TurnOnStove)
    yield ctx.registry.register("pick_bottle", VERSION, PickBottle)
    yield ctx.registry.register("place_bottle_on_rack", VERSION, PlaceBottleOnRack)
    yield ctx.registry.register("open_gripper", VERSION, OpenGripper)
    yield ctx.registry.register("main", VERSION, build)
