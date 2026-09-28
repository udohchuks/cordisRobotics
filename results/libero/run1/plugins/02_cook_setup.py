# file: cook_setup.py
from kitchen import *

VERSION = 2

RACK_TOP_Z = 0.920

# ---------------- checks ----------------

class BowlOnStove(Check):
    def ok(self, scene):
        return scene.holds("on", "akita_black_bowl_1", "flat_stove_1_cook_region")

class BottleOnRack(Check):
    def ok(self, scene):
        return scene.holds("on", "wine_bottle_1", "wine_rack_1_top_region")

class BottleHeld(Check):
    def ok(self, scene):
        return scene.gripper_width < 0.05 and scene.pos("wine_bottle_1")[2] > 0.95

class StoveOn(Check):
    def ok(self, scene):
        return scene.holds("turnon", "flat_stove_1")

# ---------------- VLA steps ----------------

class BowlToStove(VLASkill):
    INSTRUCTION = "put the black bowl on the stove"
    MAX_STEPS = 300

    def done(self, scene):
        return scene.holds("on", "akita_black_bowl_1", "flat_stove_1_cook_region")

class BottlePick(VLASkill):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 200

    def done(self, scene):
        return scene.pos("wine_bottle_1")[2] > 0.95

class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 200

    def done(self, scene):
        return scene.holds("turnon", "flat_stove_1")

# ---------------- geometric place on the rack ----------------

class _RackMove(MoveSkill):
    """Move so that the *bottle base* ends up at a wanted height on the rack.

    The gripper holds the bottle with a constant offset d = eef - bottle_base,
    measured once at the start of this move.  We keep the orientation, so d
    stays valid for the whole motion.
    """
    TOL = 0.02
    MAX_STEPS = 80
    Z_EXTRA = 0.0
    _d = None

    def target(self, scene):
        b = scene.pos("wine_bottle_1")
        e = scene.eef
        if _RackMove._d is None:
            _RackMove._d = [e[0] - b[0], e[1] - b[1], e[2] - b[2]]
        d = _RackMove._d
        rt = scene.pos("wine_rack_1")
        return ([rt[0] + d[0], rt[1] + d[1], RACK_TOP_Z + d[2] + self.Z_EXTRA], 1)

class RackAbove(_RackMove):
    Z_EXTRA = 0.12          # first go above the rack, bottle clear of it

class RackPlace(_RackMove):
    Z_EXTRA = 0.02          # lower the bottle base just above the rack top

class OpenGrip(Gripper):
    GRIP = -1

class RackRetreat(MoveSkill):
    TOL = 0.02
    MAX_STEPS = 60

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], e[2] + 0.10], -1)

# ---------------- tree ----------------

def build():
    return Sequence(
        Fallback(Leaf("bowl_on_stove"), Leaf("bowl_to_stove")),
        Fallback(
            Leaf("bottle_on_rack"),
            Sequence(
                Fallback(Leaf("bottle_held"), Leaf("bottle_pick")),
                Leaf("rack_above"),
                Leaf("rack_place"),
                Leaf("open_grip"),
                Leaf("rack_retreat"),
            ),
        ),
        Fallback(Leaf("stove_on"), Leaf("turn_on_stove")),
    )

# ---------------- registration ----------------

def apply(ctx, config):
    yield ctx.registry.register("bowl_on_stove", VERSION, BowlOnStove)
    yield ctx.registry.register("bottle_on_rack", VERSION, BottleOnRack)
    yield ctx.registry.register("bottle_held", VERSION, BottleHeld)
    yield ctx.registry.register("stove_on", VERSION, StoveOn)

    yield ctx.registry.register("bowl_to_stove", VERSION, BowlToStove)
    yield ctx.registry.register("bottle_pick", VERSION, BottlePick)
    yield ctx.registry.register("turn_on_stove", VERSION, TurnOnStove)

    yield ctx.registry.register("rack_above", VERSION, RackAbove)
    yield ctx.registry.register("rack_place", VERSION, RackPlace)
    yield ctx.registry.register("open_grip", VERSION, OpenGrip)
    yield ctx.registry.register("rack_retreat", VERSION, RackRetreat)

    yield ctx.registry.register("main", VERSION, build)
