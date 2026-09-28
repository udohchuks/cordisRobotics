# file: cook_setup.py
from kitchen import *

VERSION = 3

COOK_X, COOK_Y, COOK_Z = -0.254, 0.202, 0.905
RACK_X, RACK_Y, RACK_Z = -0.267, -0.251, 0.920

# ---------------- checks ----------------

class BowlOnStove(Check):
    def ok(self, scene):
        return scene.holds("on", "akita_black_bowl_1", "flat_stove_1_cook_region")

class BottleOnRack(Check):
    def ok(self, scene):
        return scene.holds("on", "wine_bottle_1", "wine_rack_1_top_region")

class StoveOn(Check):
    def ok(self, scene):
        return scene.holds("turnon", "flat_stove_1")

def _held(scene, obj):
    if scene.gripper_width > 0.06:
        return False
    e = scene.eef
    p = scene.pos(obj)
    return (abs(e[0] - p[0]) < 0.15 and abs(e[1] - p[1]) < 0.15
            and abs(e[2] - p[2]) < 0.30)

class BowlHeld(Check):
    def ok(self, scene):
        return _held(scene, "akita_black_bowl_1")

class BottleHeld(Check):
    def ok(self, scene):
        return _held(scene, "wine_bottle_1")

# ---------------- VLA picks ----------------

class BowlPick(VLASkill):
    INSTRUCTION = "pick up the black bowl"
    MAX_STEPS = 150

    def done(self, scene):
        return _held(scene, "akita_black_bowl_1")

class BottlePick(VLASkill):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 150

    def done(self, scene):
        return _held(scene, "wine_bottle_1")

class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 200

    def done(self, scene):
        return scene.holds("turnon", "flat_stove_1")

# ---------------- geometric place ----------------

class _PlaceMove(MoveSkill):
    """Move so the held object's BASE goes to (TX, TY, TZ + DZ).

    The offset d = eef - object_base is fixed while the grasp holds, and is
    measured once per subclass at the start of the motion.
    """
    OBJ = None
    TX = 0.0
    TY = 0.0
    TZ = 0.0
    DZ = 0.0
    GRIP = 1
    TOL = 0.02
    MAX_STEPS = 100

    def target(self, scene):
        cls = type(self)
        p = scene.pos(self.OBJ)
        e = scene.eef
        if cls.__dict__.get("_d") is None:
            cls._d = [e[0] - p[0], e[1] - p[1], e[2] - p[2]]
        d = cls._d
        return ([self.TX + d[0], self.TY + d[1], self.TZ + self.DZ + d[2]],
                self.GRIP)

class BowlAbove(_PlaceMove):
    OBJ = "akita_black_bowl_1"
    TX, TY, TZ = COOK_X, COOK_Y, COOK_Z
    DZ = 0.12

class BowlDown(_PlaceMove):
    OBJ = "akita_black_bowl_1"
    TX, TY, TZ = COOK_X, COOK_Y, COOK_Z
    DZ = 0.005

class BottleAbove(_PlaceMove):
    OBJ = "wine_bottle_1"
    TX, TY, TZ = RACK_X, RACK_Y, RACK_Z
    DZ = 0.12

class BottleDown(_PlaceMove):
    OBJ = "wine_bottle_1"
    TX, TY, TZ = RACK_X, RACK_Y, RACK_Z
    DZ = 0.005

class OpenGrip(Gripper):
    GRIP = -1

class Retreat(MoveSkill):
    GRIP = -1
    TOL = 0.02
    MAX_STEPS = 60

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], e[2] + 0.12], -1)

# ---------------- behavior tree ----------------

def build():
    return Sequence(
        # bowl onto the stove cook region
        Fallback(
            Leaf("bowl_on_stove"),
            Sequence(
                Fallback(Leaf("bowl_held"), Leaf("bowl_pick")),
                Leaf("bowl_above"),
                Leaf("bowl_down"),
                Leaf("open_grip"),
                Leaf("retreat"),
            ),
        ),
        # bottle onto the wine rack top
        Fallback(
            Leaf("bottle_on_rack"),
            Sequence(
                Fallback(Leaf("bottle_held"), Leaf("bottle_pick")),
                Leaf("bottle_above"),
                Leaf("bottle_down"),
                Leaf("open_grip"),
                Leaf("retreat"),
            ),
        ),
        # finally light the stove
        Fallback(Leaf("stove_on"), Leaf("turn_on_stove")),
    )

# ---------------- registration ----------------

def apply(ctx, config):
    yield ctx.registry.register("bowl_on_stove", VERSION, BowlOnStove)
    yield ctx.registry.register("bottle_on_rack", VERSION, BottleOnRack)
    yield ctx.registry.register("stove_on", VERSION, StoveOn)
    yield ctx.registry.register("bowl_held", VERSION, BowlHeld)
    yield ctx.registry.register("bottle_held", VERSION, BottleHeld)

    yield ctx.registry.register("bowl_pick", VERSION, BowlPick)
    yield ctx.registry.register("bottle_pick", VERSION, BottlePick)
    yield ctx.registry.register("turn_on_stove", VERSION, TurnOnStove)

    yield ctx.registry.register("bowl_above", VERSION, BowlAbove)
    yield ctx.registry.register("bowl_down", VERSION, BowlDown)
    yield ctx.registry.register("bottle_above", VERSION, BottleAbove)
    yield ctx.registry.register("bottle_down", VERSION, BottleDown)
    yield ctx.registry.register("open_grip", VERSION, OpenGrip)
    yield ctx.registry.register("retreat", VERSION, Retreat)

    yield ctx.registry.register("main", VERSION, build)
