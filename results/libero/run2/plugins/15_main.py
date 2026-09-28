# file: main.py
from kitchen import *

VERSION = 15

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
STOVE = "flat_stove_1"
COOK = "flat_stove_1_cook_region"
RACK = "wine_rack_1_top_region"

COOK_XY = [-0.254, 0.202]
RACK_XY = [-0.267, -0.251]
STOVE_XY = [-0.404, 0.202]
SAFE_XY = [-0.02, 0.02, 1.18]


# ---------- conditions ----------

class AlwaysOk(Check):
    def ok(self, scene):
        return True


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


# ---------- recovery moves ----------

class UpHigh(MoveSkill):
    ORIENT = "keep"
    TOL = 0.04
    MAX_STEPS = 300

    def target(self, scene):
        x, y, z = scene.eef
        return ([x, y, 1.48], -1)


class FwdHigh(MoveSkill):
    ORIENT = "keep"
    TOL = 0.12
    MAX_STEPS = 400

    def target(self, scene):
        return ([-0.33, 0.05, 1.46], -1)


# ---------- bottle: reach (horizontal then descend) ----------

class OverBottleH(MoveSkill):
    ORIENT = "keep"
    TOL = 0.05
    MAX_STEPS = 250

    def target(self, scene):
        return ([-0.203, -0.06, 1.36], -1)


class DownToBottle(MoveSkill):
    ORIENT = "down"
    TOL = 0.05
    MAX_STEPS = 250

    def target(self, scene):
        return ([-0.203, -0.06, 1.25], -1)


# ---------- bottle: carry & place ----------

class LiftBottle(MoveSkill):
    ORIENT = "keep"
    TOL = 0.05
    MAX_STEPS = 250

    def target(self, scene):
        x, y, z = scene.eef
        return ([x, y, 1.42], +1)


class OverRack(MoveSkill):
    ORIENT = "keep"
    TOL = 0.05
    MAX_STEPS = 300

    def target(self, scene):
        return ([RACK_XY[0], RACK_XY[1], 1.36], +1)


class DownRack(MoveSkill):
    ORIENT = "keep"
    TOL = 0.04
    MAX_STEPS = 250

    def target(self, scene):
        return ([RACK_XY[0], RACK_XY[1], 1.10], +1)


class Retreat(MoveSkill):
    ORIENT = "keep"
    TOL = 0.07
    MAX_STEPS = 250

    def target(self, scene):
        return ([-0.05, 0.02, 1.35], -1)


# ---------- stove approach ----------

class ApproachStove(MoveSkill):
    ORIENT = "keep"
    TOL = 0.10
    MAX_STEPS = 250

    def target(self, scene):
        return ([STOVE_XY[0], STOVE_XY[1], 1.20], -1)


# ---------- VLA skills ----------

class PickBowl(VLASkill):
    INSTRUCTION = "pick up the black bowl"
    MAX_STEPS = 300

    def done(self, scene):
        return scene.pos(BOWL)[2] > 0.94


class PickBottle(VLASkill):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 350

    def done(self, scene):
        return scene.pos(BOTTLE)[2] > 0.94


class TurnOnStoveA(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 350

    def done(self, scene):
        return scene.holds("turnon", STOVE)


class TurnOnStoveB(VLASkill):
    INSTRUCTION = "turn on the stove burner"
    MAX_STEPS = 350

    def done(self, scene):
        return scene.holds("turnon", STOVE)


class OpenGripper(Gripper):
    GRIP = -1


# ---------- behavior tree ----------

def build():
    return Sequence(
        # --- recover the folded arm (best effort) ---
        Fallback(Sequence(Leaf("up_high"), Leaf("fwd_high")), Leaf("always_ok")),
        # --- bottle onto the rack ---
        Fallback(
            Leaf("bottle_on_rack_check"),
            Sequence(
                Fallback(
                    Leaf("hold_bottle_check"),
                    Sequence(
                        Leaf("over_bottle_h"),
                        Leaf("down_to_bottle"),
                        Leaf("pick_bottle"),
                    ),
                ),
                Leaf("lift_bottle"),
                Leaf("over_rack"),
                Leaf("down_rack"),
                Leaf("open_gripper"),
                Leaf("retreat"),
            ),
            Leaf("always_ok"),
        ),
        # --- bowl onto the stove (no-op if already there) ---
        Fallback(
            Leaf("bowl_on_stove_check"),
            Sequence(
                Fallback(
                    Leaf("hold_bowl_check"),
                    Sequence(Leaf("over_bottle_h"), Leaf("pick_bowl")),
                ),
                Leaf("always_ok"),
            ),
            Leaf("always_ok"),
        ),
        # --- stove on (best effort) ---
        Fallback(
            Leaf("stove_on_check"),
            Sequence(Leaf("approach_stove"), Leaf("turn_on_stove_a")),
            Sequence(Leaf("approach_stove"), Leaf("turn_on_stove_b")),
            Leaf("always_ok"),
        ),
        Leaf("always_ok"),
    )


def apply(ctx, config):
    yield ctx.registry.register("always_ok", VERSION, AlwaysOk)
    yield ctx.registry.register("bowl_on_stove_check", VERSION, BowlOnStoveCheck)
    yield ctx.registry.register("stove_on_check", VERSION, StoveOnCheck)
    yield ctx.registry.register("bottle_on_rack_check", VERSION, BottleOnRackCheck)
    yield ctx.registry.register("hold_bowl_check", VERSION, HoldBowlCheck)
    yield ctx.registry.register("hold_bottle_check", VERSION, HoldBottleCheck)
    yield ctx.registry.register("up_high", VERSION, UpHigh)
    yield ctx.registry.register("fwd_high", VERSION, FwdHigh)
    yield ctx.registry.register("over_bottle_h", VERSION, OverBottleH)
    yield ctx.registry.register("down_to_bottle", VERSION, DownToBottle)
    yield ctx.registry.register("lift_bottle", VERSION, LiftBottle)
    yield ctx.registry.register("over_rack", VERSION, OverRack)
    yield ctx.registry.register("down_rack", VERSION, DownRack)
    yield ctx.registry.register("retreat", VERSION, Retreat)
    yield ctx.registry.register("approach_stove", VERSION, ApproachStove)
    yield ctx.registry.register("pick_bowl", VERSION, PickBowl)
    yield ctx.registry.register("pick_bottle", VERSION, PickBottle)
    yield ctx.registry.register("turn_on_stove_a", VERSION, TurnOnStoveA)
    yield ctx.registry.register("turn_on_stove_b", VERSION, TurnOnStoveB)
    yield ctx.registry.register("open_gripper", VERSION, OpenGripper)
    yield ctx.registry.register("main", VERSION, build)
