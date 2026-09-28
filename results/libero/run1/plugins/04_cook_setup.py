# file: cook_setup.py
from kitchen import *

VERSION = 4

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
BOWL_REGION = "flat_stove_1_cook_region"
BOTTLE_REGION = "wine_rack_1_top_region"

# known from the task description (safety rule) / current scene
BOWL_TARGET = [-0.254, 0.202, 0.905]
BOTTLE_TARGET = [-0.267, -0.251, 0.95]

# grasp offset captured at the moment of contact:  d = eef - object_pos
GRASP = {}


def _region(scene, name, fallback):
    try:
        p = scene.pos(name)
        if p is not None and len(p) >= 3:
            vals = [float(p[0]), float(p[1]), float(p[2])]
            if all(v == v for v in vals):      # not NaN
                return vals
    except Exception:
        pass
    return list(fallback)


def _grasp_ok(scene, obj):
    """Strict contact test: fingers partly closed AND centred on the object."""
    try:
        w = scene.gripper_width
    except Exception:
        return False
    if not (0.008 < w < 0.072):          # not full-open, not closed on air
        return False
    e = scene.eef
    try:
        p = scene.pos(obj)
    except Exception:
        return False
    return (abs(e[0] - p[0]) < 0.06 and abs(e[1] - p[1]) < 0.06
            and abs(e[2] - p[2]) < 0.18)


def _record(obj, scene):
    if obj not in GRASP:
        try:
            GRASP[obj] = (list(scene.eef), list(scene.pos(obj)))
        except Exception:
            pass


# ---------------- checks ----------------

class BowlOnStove(Check):
    def ok(self, scene):
        return scene.holds("on", BOWL, BOWL_REGION)

class BottleOnRack(Check):
    def ok(self, scene):
        return scene.holds("on", BOTTLE, BOTTLE_REGION)

class StoveOn(Check):
    def ok(self, scene):
        return scene.holds("turnon", "flat_stove_1")

class BowlHeld(Check):
    def ok(self, scene):
        if _grasp_ok(scene, BOWL):
            _record(BOWL, scene)
            return True
        return False

class BottleHeld(Check):
    def ok(self, scene):
        if _grasp_ok(scene, BOTTLE):
            _record(BOTTLE, scene)
            return True
        return False


# ---------------- VLA steps ----------------

class BowlPick(VLASkill):
    INSTRUCTION = "pick up the black bowl"
    MAX_STEPS = 200

    def done(self, scene):
        if _grasp_ok(scene, BOWL):
            _record(BOWL, scene)
            return True
        return False

class BottlePick(VLASkill):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 200

    def done(self, scene):
        if _grasp_ok(scene, BOTTLE):
            _record(BOTTLE, scene)
            return True
        return False

class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 200

    def done(self, scene):
        return scene.holds("turnon", "flat_stove_1")


# ---------------- geometric placing ----------------

class _Place(MoveSkill):
    OBJ = None
    REGION = None
    FALLBACK = (0.0, 0.0, 0.0)
    DZ = 0.0
    TOL = 0.02
    MAX_STEPS = 120

    def target(self, scene):
        e0, p0 = GRASP[self.OBJ]                 # captured at contact
        r = _region(scene, self.REGION, self.FALLBACK)
        return ([r[0] + (e0[0] - p0[0]),
                 r[1] + (e0[1] - p0[1]),
                 r[2] + self.DZ + (e0[2] - p0[2])], 1)

class BowlAbove(_Place):
    OBJ, REGION, FALLBACK = BOWL, BOWL_REGION, BOWL_TARGET
    DZ = 0.12

class BowlDown(_Place):
    OBJ, REGION, FALLBACK = BOWL, BOWL_REGION, BOWL_TARGET
    DZ = 0.005

class BottleAbove(_Place):
    OBJ, REGION, FALLBACK = BOTTLE, BOTTLE_REGION, BOTTLE_TARGET
    DZ = 0.14

class BottleDown(_Place):
    OBJ, REGION, FALLBACK = BOTTLE, BOTTLE_REGION, BOTTLE_TARGET
    DZ = 0.005

class OpenGrip(Gripper):
    GRIP = -1

class Retreat(MoveSkill):
    """Lift straight up to a fixed ceiling height (converges, stateless)."""
    TOL = 0.02
    MAX_STEPS = 80

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], min(e[2] + 0.12, 1.30)], -1)


# ---------------- behavior tree ----------------

def build():
    return Sequence(
        Fallback(
            Leaf("bowl_on_stove"),
            Sequence(
                Fallback(Leaf("bowl_held"), Leaf("bowl_pick")),
                Leaf("bowl_above"),
                Leaf("bowl_down"),
                Leaf("open_grip"),
                Leaf("retreat"),
                Leaf("bowl_on_stove"),
            ),
        ),
        Fallback(
            Leaf("bottle_on_rack"),
            Sequence(
                Fallback(Leaf("bottle_held"), Leaf("bottle_pick")),
                Leaf("bottle_above"),
                Leaf("bottle_down"),
                Leaf("open_grip"),
                Leaf("retreat"),
                Leaf("bottle_on_rack"),
            ),
        ),
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
