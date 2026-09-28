# file: main.py
from kitchen import *

VERSION = 20

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
STOVE = "flat_stove_1"
COOK = "flat_stove_1_cook_region"
RACK = "wine_rack_1_top_region"

BOTTLE_XY = [-0.203, -0.06]
RACK_XY = [-0.267, -0.251]
STOVE_XY = [-0.404, 0.202]


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
        return 0.02 < scene.gripper_width < 0.079


# ---------- recovery: crawl back to the table in small non-fatal steps ----------

def _esc(name, tgt, budget=200):
    cls = type(name, (MoveSkill,), {
        "ORIENT": "keep", "TOL": 0.06, "MAX_STEPS": budget,
        "target": lambda self, scene: (list(tgt), -1),
    })
    return name, cls, tgt


class Esc1(MoveSkill):
    ORIENT = "keep"; TOL = 0.05; MAX_STEPS = 200
    def target(self, scene):
        return ([-0.60, -0.05, 1.14], -1)

class Esc2(MoveSkill):
    ORIENT = "keep"; TOL = 0.05; MAX_STEPS = 200
    def target(self, scene):
        return ([-0.52, -0.01, 1.20], -1)

class Esc3(MoveSkill):
    ORIENT = "keep"; TOL = 0.05; MAX_STEPS = 200
    def target(self, scene):
        return ([-0.44, 0.02, 1.26], -1)

class Esc4(MoveSkill):
    ORIENT = "keep"; TOL = 0.05; MAX_STEPS = 200
    def target(self, scene):
        return ([-0.36, 0.03, 1.32], -1)

class Esc5(MoveSkill):
    ORIENT = "keep"; TOL = 0.05; MAX_STEPS = 200
    def target(self, scene):
        return ([-0.28, 0.01, 1.36], -1)

class Esc6(MoveSkill):
    ORIENT = "keep"; TOL = 0.05; MAX_STEPS = 200
    def target(self, scene):
        return ([-0.22, 0.00, 1.38], -1)


# ---------- bottle ----------

class AboveBottle(MoveSkill):
    ORIENT = "keep"; TOL = 0.05; MAX_STEPS = 400
    def target(self, scene):
        return ([BOTTLE_XY[0], BOTTLE_XY[1], 1.30], -1)

class DownBottle(MoveSkill):
    ORIENT = "keep"; TOL = 0.03; MAX_STEPS = 400
    def target(self, scene):
        return ([BOTTLE_XY[0], BOTTLE_XY[1], 1.02], -1)

class LiftBottle(MoveSkill):
    ORIENT = "keep"; TOL = 0.06; MAX_STEPS = 400
    def target(self, scene):
        x, y, z = scene.eef
        return ([x, y, 1.42], +1)

class OverRack(MoveSkill):
    ORIENT = "keep"; TOL = 0.06; MAX_STEPS = 500
    def target(self, scene):
        return ([RACK_XY[0], RACK_XY[1], 1.30], +1)

class DownRack(MoveSkill):
    ORIENT = "keep"; TOL = 0.04; MAX_STEPS = 500
    def target(self, scene):
        return ([RACK_XY[0], RACK_XY[1], 1.03], +1)

class Retreat(MoveSkill):
    ORIENT = "keep"; TOL = 0.10; MAX_STEPS = 300
    def target(self, scene):
        return ([-0.05, 0.05, 1.42], -1)


# ---------- stove ----------

class OverStove(MoveSkill):
    ORIENT = "keep"; TOL = 0.06; MAX_STEPS = 500
    def target(self, scene):
        return ([STOVE_XY[0], STOVE_XY[1], 1.18], -1)


class CloseGripper(Gripper):
    GRIP = +1

class OpenGripper(Gripper):
    GRIP = -1


# ---------- VLA ----------

class TurnOnStoveA(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 500
    def done(self, scene):
        return scene.holds("turnon", STOVE)

class TurnOnStoveB(VLASkill):
    INSTRUCTION = "press the stove knob"
    MAX_STEPS = 500
    def done(self, scene):
        return scene.holds("turnon", STOVE)

class TurnOnStoveC(VLASkill):
    INSTRUCTION = "turn the stove on"
    MAX_STEPS = 500
    def done(self, scene):
        return scene.holds("turnon", STOVE)


def build():
    return Sequence(
        Leaf("open_gripper"),
        # --- recover the jammed arm (each step non-fatal, progress compounds) ---
        Fallback(Leaf("esc1"), Leaf("always_ok")),
        Fallback(Leaf("esc2"), Leaf("always_ok")),
        Fallback(Leaf("esc3"), Leaf("always_ok")),
        Fallback(Leaf("esc4"), Leaf("always_ok")),
        Fallback(Leaf("esc5"), Leaf("always_ok")),
        Fallback(Leaf("esc6"), Leaf("always_ok")),
        # --- bottle onto the rack ---
        Fallback(
            Leaf("bottle_on_rack_check"),
            Sequence(
                Fallback(
                    Leaf("hold_bottle_check"),
                    Sequence(
                        Fallback(Leaf("above_bottle"), Leaf("always_ok")),
                        Fallback(Leaf("down_bottle"), Leaf("always_ok")),
                        Leaf("close_gripper"),
                        Leaf("hold_bottle_check"),
                    ),
                ),
                Fallback(Leaf("lift_bottle"), Leaf("always_ok")),
                Fallback(Leaf("over_rack"), Leaf("always_ok")),
                Fallback(Leaf("down_rack"), Leaf("always_ok")),
                Leaf("open_gripper"),
                Fallback(Leaf("retreat"), Leaf("always_ok")),
            ),
            Leaf("always_ok"),
        ),
        # --- stove on (best effort) ---
        Fallback(
            Leaf("stove_on_check"),
            Sequence(Fallback(Leaf("over_stove"), Leaf("always_ok")), Leaf("turn_on_stove_a")),
            Sequence(Fallback(Leaf("over_stove"), Leaf("always_ok")), Leaf("turn_on_stove_b")),
            Sequence(Fallback(Leaf("over_stove"), Leaf("always_ok")), Leaf("turn_on_stove_c")),
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
    for nm, cls in [("esc1", Esc1), ("esc2", Esc2), ("esc3", Esc3),
                    ("esc4", Esc4), ("esc5", Esc5), ("esc6", Esc6)]:
        yield ctx.registry.register(nm, VERSION, cls)
    yield ctx.registry.register("above_bottle", VERSION, AboveBottle)
    yield ctx.registry.register("down_bottle", VERSION, DownBottle)
    yield ctx.registry.register("lift_bottle", VERSION, LiftBottle)
    yield ctx.registry.register("over_rack", VERSION, OverRack)
    yield ctx.registry.register("down_rack", VERSION, DownRack)
    yield ctx.registry.register("retreat", VERSION, Retreat)
    yield ctx.registry.register("over_stove", VERSION, OverStove)
    yield ctx.registry.register("close_gripper", VERSION, CloseGripper)
    yield ctx.registry.register("open_gripper", VERSION, OpenGripper)
    yield ctx.registry.register("turn_on_stove_a", VERSION, TurnOnStoveA)
    yield ctx.registry.register("turn_on_stove_b", VERSION, TurnOnStoveB)
    yield ctx.registry.register("turn_on_stove_c", VERSION, TurnOnStoveC)
    yield ctx.registry.register("main", VERSION, build)
