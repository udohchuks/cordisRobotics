# file: main.py
from kitchen import *

VERSION = 16

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
STOVE = "flat_stove_1"
COOK = "flat_stove_1_cook_region"
RACK = "wine_rack_1_top_region"

BOTTLE_XY = [-0.203, -0.06]
RACK_XY = [-0.267, -0.251]
STOVE_XY = [-0.404, 0.202]


# ---------- conditions ----------

class AlwaysOk(Check):
    def ok(self, scene):
        return True


class BowlOnStoveCheck(Check):
    def ok(self, scene):
        return scene.holds("on", BOWL, COOK)


class StoveOnCheck(Check):
    def ok(self, scene):
        return scene.holds("turnon", STOVE)


class BottleOnRackCheck(Check):
    def ok(self, scene):
        return scene.holds("on", BOTTLE, RACK)


class HoldBottleCheck(Check):
    def ok(self, scene):
        return scene.gripper_width < 0.02 and scene.pos(BOTTLE)[2] > 0.93


# ---------- recovery ----------

class UpHigh(MoveSkill):
    ORIENT = "keep"
    TOL = 0.05
    MAX_STEPS = 350

    def target(self, scene):
        x, y, z = scene.eef
        return ([x, y, 1.48], -1)


class FwdHigh(MoveSkill):
    ORIENT = "keep"
    TOL = 0.12
    MAX_STEPS = 400

    def target(self, scene):
        return ([-0.33, 0.05, 1.46], -1)


# ---------- bottle ----------

class OverBottle(MoveSkill):
    ORIENT = "keep"
    TOL = 0.10
    MAX_STEPS = 300

    def target(self, scene):
        return ([BOTTLE_XY[0], BOTTLE_XY[1], 1.42], -1)


class LiftBottle(MoveSkill):
    ORIENT = "keep"
    TOL = 0.06
    MAX_STEPS = 250

    def target(self, scene):
        x, y, z = scene.eef
        return ([x, y, 1.45], +1)


class OverRack(MoveSkill):
    ORIENT = "keep"
    TOL = 0.08
    MAX_STEPS = 350

    def target(self, scene):
        return ([RACK_XY[0], RACK_XY[1], 1.42], +1)


class DownRack(MoveSkill):
    ORIENT = "keep"
    TOL = 0.06
    MAX_STEPS = 250

    def target(self, scene):
        return ([RACK_XY[0], RACK_XY[1], 1.12], +1)


class Retreat(MoveSkill):
    ORIENT = "keep"
    TOL = 0.10
    MAX_STEPS = 250

    def target(self, scene):
        return ([-0.05, 0.02, 1.40], -1)


# ---------- stove ----------

class OverStove(MoveSkill):
    ORIENT = "keep"
    TOL = 0.12
    MAX_STEPS = 350

    def target(self, scene):
        return ([STOVE_XY[0], STOVE_XY[1], 1.42], -1)


# ---------- VLA skills ----------

class PickBottle(VLASkill):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 400

    def done(self, scene):
        return scene.pos(BOTTLE)[2] > 0.94


class TurnOnStoveA(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 400

    def done(self, scene):
        return scene.holds("turnon", STOVE)


class TurnOnStoveB(VLASkill):
    INSTRUCTION = "turn on the stove burner"
    MAX_STEPS = 400

    def done(self, scene):
        return scene.holds("turnon", STOVE)


class OpenGripper(Gripper):
    GRIP = -1


# ---------- behavior tree ----------

def build():
    return Sequence(
        # recover the folded arm (best effort)
        Fallback(Sequence(Leaf("up_high"), Leaf("fwd_high")), Leaf("always_ok")),
        # --- bottle onto the rack (VLA grasp, hand-coded carry) ---
        Fallback(
            Leaf("bottle_on_rack_check"),
            Sequence(
                Fallback(
                    Leaf("hold_bottle_check"),
                    Sequence(
                        Fallback(Leaf("over_bottle"), Leaf("always_ok")),
                        Leaf("pick_bottle"),
                    ),
                ),
                Leaf("lift_bottle"),
                Fallback(Leaf("over_rack"), Leaf("always_ok")),
                Fallback(Leaf("down_rack"), Leaf("always_ok")),
                Leaf("open_gripper"),
                Fallback(Leaf("retreat"), Leaf("always_ok")),
            ),
            Leaf("always_ok"),
        ),
        # --- bowl (already on stove: no-op) ---
        Fallback(Leaf("bowl_on_stove_check"), Leaf("always_ok")),
        # --- stove on (best effort) ---
        Fallback(
            Leaf("stove_on_check"),
            Sequence(
                Fallback(Leaf("over_stove"), Leaf("always_ok")),
                Leaf("turn_on_stove_a"),
            ),
            Sequence(
                Fallback(Leaf("over_stove"), Leaf("always_ok")),
                Leaf("turn_on_stove_b"),
            ),
            Leaf("always_ok"),
        ),
        Leaf("always_ok"),
    )


def apply(ctx, config):
    yield ctx.registry.register("always_ok", VERSION, AlwaysOk)
    yield ctx.registry.register("bowl_on_stove_check", VERSION, BowlOnStoveCheck)
    yield ctx.registry.register("stove_on_check", VERSION, StoveOnCheck)
    yield ctx.registry.register("bottle_on_rack_check", VERSION, BottleOnRackCheck)
    yield ctx.registry.register("hold_bottle_check", VERSION, HoldBottleCheck)
    yield ctx.registry.register("up_high", VERSION, UpHigh)
    yield ctx.registry.register("fwd_high", VERSION, FwdHigh)
    yield ctx.registry.register("over_bottle", VERSION, OverBottle)
    yield ctx.registry.register("lift_bottle", VERSION, LiftBottle)
    yield ctx.registry.register("over_rack", VERSION, OverRack)
    yield ctx.registry.register("down_rack", VERSION, DownRack)
    yield ctx.registry.register("retreat", VERSION, Retreat)
    yield ctx.registry.register("over_stove", VERSION, OverStove)
    yield ctx.registry.register("pick_bottle", VERSION, PickBottle)
    yield ctx.registry.register("turn_on_stove_a", VERSION, TurnOnStoveA)
    yield ctx.registry.register("turn_on_stove_b", VERSION, TurnOnStoveB)
    yield ctx.registry.register("open_gripper", VERSION, OpenGripper)
    yield ctx.registry.register("main", VERSION, build)
