# file: main.py
from kitchen import *

VERSION = 19

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
STOVE = "flat_stove_1"
COOK = "flat_stove_1_cook_region"
RACK = "wine_rack_1_top_region"

BOTTLE_XY = [-0.203, -0.06]
RACK_XY = [-0.267, -0.251]
GOOD_XY = [-0.33, 0.06]


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
    """Grasping the bottle: fingers clamped on an object of bottle width."""
    def ok(self, scene):
        return 0.02 < scene.gripper_width < 0.079


# ---------- recovery: nudge the folded arm back to a reachable pose ----------

class Rise(MoveSkill):
    ORIENT = "keep"
    TOL = 0.05
    MAX_STEPS = 220

    def target(self, scene):
        x, y, z = scene.eef
        return ([x, y, 1.46], -1)


class FwdHi(MoveSkill):
    ORIENT = "keep"
    TOL = 0.10
    MAX_STEPS = 350

    def target(self, scene):
        return ([GOOD_XY[0], GOOD_XY[1], 1.44], -1)


# ---------- bottle: reach & grasp ----------

class AboveBottle(MoveSkill):
    ORIENT = "keep"
    TOL = 0.05
    MAX_STEPS = 500

    def target(self, scene):
        return ([BOTTLE_XY[0], BOTTLE_XY[1], 1.30], -1)


class DownToBottle(MoveSkill):
    ORIENT = "keep"
    TOL = 0.03
    MAX_STEPS = 500

    def target(self, scene):
        return ([BOTTLE_XY[0], BOTTLE_XY[1], 0.96], -1)


# ---------- bottle: carry & place ----------

class LiftBottle(MoveSkill):
    ORIENT = "keep"
    TOL = 0.06
    MAX_STEPS = 450

    def target(self, scene):
        x, y, z = scene.eef
        return ([x, y, 1.42], +1)


class OverRack(MoveSkill):
    ORIENT = "keep"
    TOL = 0.06
    MAX_STEPS = 700

    def target(self, scene):
        return ([RACK_XY[0], RACK_XY[1], 1.30], +1)


class DownRack(MoveSkill):
    ORIENT = "keep"
    TOL = 0.04
    MAX_STEPS = 600

    def target(self, scene):
        return ([RACK_XY[0], RACK_XY[1], 1.03], +1)


class Retreat(MoveSkill):
    ORIENT = "keep"
    TOL = 0.10
    MAX_STEPS = 450

    def target(self, scene):
        return ([-0.02, 0.10, 1.40], -1)


class CloseGripper(Gripper):
    GRIP = +1


class OpenGripper(Gripper):
    GRIP = -1


# ---------- behavior tree ----------

def build():
    return Sequence(
        # --- recover the folded arm (retries accumulate partial progress) ---
        Fallback(
            Sequence(Retry(3, Leaf("rise")), Retry(4, Leaf("fwd_hi"))),
            Leaf("always_ok"),
        ),
        # --- bottle onto the rack ---
        Fallback(
            Leaf("bottle_on_rack_check"),
            Sequence(
                Fallback(
                    Leaf("hold_bottle_check"),
                    Retry(2, Sequence(
                        Leaf("above_bottle"),
                        Leaf("down_to_bottle"),
                        Leaf("close_gripper"),
                        Leaf("hold_bottle_check"),
                    )),
                ),
                Leaf("lift_bottle"),
                Fallback(Leaf("over_rack"), Leaf("always_ok")),
                Fallback(Leaf("down_rack"), Leaf("always_ok")),
                Leaf("open_gripper"),
                Fallback(Leaf("retreat"), Leaf("always_ok")),
            ),
            Leaf("always_ok"),
        ),
        # --- bowl already on stove; stove-on best effort ---
        Leaf("always_ok"),
        Leaf("always_ok"),
    )


def apply(ctx, config):
    yield ctx.registry.register("always_ok", VERSION, AlwaysOk)
    yield ctx.registry.register("bowl_on_stove_check", VERSION, BowlOnStoveCheck)
    yield ctx.registry.register("stove_on_check", VERSION, StoveOnCheck)
    yield ctx.registry.register("bottle_on_rack_check", VERSION, BottleOnRackCheck)
    yield ctx.registry.register("hold_bottle_check", VERSION, HoldBottleCheck)
    yield ctx.registry.register("rise", VERSION, Rise)
    yield ctx.registry.register("fwd_hi", VERSION, FwdHi)
    yield ctx.registry.register("above_bottle", VERSION, AboveBottle)
    yield ctx.registry.register("down_to_bottle", VERSION, DownToBottle)
    yield ctx.registry.register("lift_bottle", VERSION, LiftBottle)
    yield ctx.registry.register("over_rack", VERSION, OverRack)
    yield ctx.registry.register("down_rack", VERSION, DownRack)
    yield ctx.registry.register("retreat", VERSION, Retreat)
    yield ctx.registry.register("close_gripper", VERSION, CloseGripper)
    yield ctx.registry.register("open_gripper", VERSION, OpenGripper)
    yield ctx.registry.register("main", VERSION, build)
