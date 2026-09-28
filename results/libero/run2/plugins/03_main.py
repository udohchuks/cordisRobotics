# file: main.py
from kitchen import *

VERSION = 4

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
STOVE = "flat_stove_1"
COOK = "flat_stove_1_cook_region"
RACK = "wine_rack_1_top_region"

COOK_XY = [-0.254, 0.202]
RACK_XY = [-0.267, -0.251]
SAFE_XY = [-0.02, 0.02, 1.18]


# ---------- conditions ----------

class BowlOnStoveCheck(Check):
    def ok(self, scene):
        if scene.holds("on", BOWL, COOK):
            return True
        x, y, z = scene.pos(BOWL)
        return abs(x - COOK_XY[0]) < 0.06 and abs(y - COOK_XY[1]) < 0.06 and z < 1.0


class StoveOnCheck(Check):
    def ok(self, scene):
        return scene.holds("turnon", STOVE)


class BottleOnRackCheck(Check):
    def ok(self, scene):
        return scene.holds("on", BOTTLE, RACK)


class HoldBowlCheck(Check):
    def ok(self, scene):
        return scene.gripper_width < 0.02 and scene.pos(BOWL)[2] > 0.93


class HoldBottleCheck(Check):
    def ok(self, scene):
        return scene.gripper_width < 0.02 and scene.pos(BOTTLE)[2] > 0.93


# ---------- approach / carry / place moves ----------

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


class BowlOverStove(MoveSkill):
    TOL = 0.03
    ORIENT = "keep"

    def target(self, scene):
        return ([COOK_XY[0], COOK_XY[1], scene.eef[2]], +1)


class BowlDownStove(MoveSkill):
    TOL = 0.02
    ORIENT = "keep"

    def target(self, scene):
        drop = max(0.0, scene.pos(BOWL)[2] - 0.91)
        return ([COOK_XY[0], COOK_XY[1], scene.eef[2] - drop], +1)


class BottleOverRack(MoveSkill):
    TOL = 0.03
    ORIENT = "keep"

    def target(self, scene):
        return ([RACK_XY[0], RACK_XY[1], scene.eef[2]], +1)


class BottleDownRack(MoveSkill):
    TOL = 0.02
    ORIENT = "keep"

    def target(self, scene):
        drop = max(0.0, scene.pos(BOTTLE)[2] - 0.96)
        return ([RACK_XY[0], RACK_XY[1], scene.eef[2] - drop], +1)


class Retreat(MoveSkill):
    ORIENT = "down"
    TOL = 0.04

    def target(self, scene):
        return (SAFE_XY, -1)


# ---------- VLA grasps ----------

class PickBowl(VLASkill):
    INSTRUCTION = "pick up the black bowl"
    MAX_STEPS = 300

    def done(self, scene):
        return scene.pos(BOWL)[2] > 0.94


class PickBottle(VLASkill):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 300

    def done(self, scene):
        return scene.pos(BOTTLE)[2] > 0.94


class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 300

    def done(self, scene):
        return scene.holds("turnon", STOVE)


class OpenGripper(Gripper):
    GRIP = -1


# ---------- behavior tree ----------

def build():
    return Sequence(
        # --- bowl onto the stove ---
        Fallback(
            Leaf("bowl_on_stove_check"),
            Sequence(
                Fallback(
                    Leaf("hold_bowl_check"),
                    Sequence(Leaf("approach_bowl"), Leaf("pick_bowl")),
                ),
                Leaf("bowl_over_stove"),
                Leaf("bowl_down_stove"),
                Leaf("open_gripper"),
                Leaf("retreat"),
            ),
        ),
        # --- stove on (only after the arm is clear) ---
        Fallback(
            Leaf("stove_on_check"),
            Leaf("turn_on_stove"),
        ),
        # --- bottle onto the rack ---
        Fallback(
            Leaf("bottle_on_rack_check"),
            Sequence(
                Fallback(
                    Leaf("hold_bottle_check"),
                    Sequence(Leaf("approach_bottle"), Leaf("pick_bottle")),
                ),
                Leaf("bottle_over_rack"),
                Leaf("bottle_down_rack"),
                Leaf("open_gripper"),
                Leaf("retreat"),
            ),
        ),
    )


def apply(ctx, config):
    yield ctx.registry.register("bowl_on_stove_check", VERSION, BowlOnStoveCheck)
    yield ctx.registry.register("stove_on_check", VERSION, StoveOnCheck)
    yield ctx.registry.register("bottle_on_rack_check", VERSION, BottleOnRackCheck)
    yield ctx.registry.register("hold_bowl_check", VERSION, HoldBowlCheck)
    yield ctx.registry.register("hold_bottle_check", VERSION, HoldBottleCheck)
    yield ctx.registry.register("approach_bowl", VERSION, ApproachBowl)
    yield ctx.registry.register("approach_bottle", VERSION, ApproachBottle)
    yield ctx.registry.register("bowl_over_stove", VERSION, BowlOverStove)
    yield ctx.registry.register("bowl_down_stove", VERSION, BowlDownStove)
    yield ctx.registry.register("bottle_over_rack", VERSION, BottleOverRack)
    yield ctx.registry.register("bottle_down_rack", VERSION, BottleDownRack)
    yield ctx.registry.register("retreat", VERSION, Retreat)
    yield ctx.registry.register("pick_bowl", VERSION, PickBowl)
    yield ctx.registry.register("pick_bottle", VERSION, PickBottle)
    yield ctx.registry.register("turn_on_stove", VERSION, TurnOnStove)
    yield ctx.registry.register("open_gripper", VERSION, OpenGripper)
    yield ctx.registry.register("main", VERSION, build)
