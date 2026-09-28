# file: cook_setup.py
from kitchen import *

VERSION = 8

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
BOWL_REGION = "flat_stove_1_cook_region"
BOTTLE_REGION = "wine_rack_1_top_region"

BOWL_FB = [-0.254, 0.202, 0.905]
BOTTLE_FB = [-0.267, -0.251, 0.99]

BOWL_DESC = 0.03      # eef height over the bowl point at the grasp instant
BOTTLE_DESC = 0.09    # ... and over the bottle point

GRASP = {}            # obj -> [dx,dy,dz] = eef - object_point, valid while held
PRE = {}              # obj -> object z just before grasping


def _v(p):
    return [float(p[0]), float(p[1]), float(p[2])]


def _objp(scene, obj):
    try:
        return _v(scene.pos(obj))
    except Exception:
        return None


def _regionp(scene, name, fb):
    try:
        p = _v(scene.pos(name))
        if all(x == x for x in p):
            return p
    except Exception:
        pass
    return list(fb)


# ---------------- goal checks (geometric, so a floating object cannot fool us) ----

class BowlOk(Check):
    def ok(self, scene):
        if scene.holds("on", BOWL, BOWL_REGION):
            return True
        p = _objp(scene, BOWL)
        if p is None:
            return False
        r = _regionp(scene, BOWL_REGION, BOWL_FB)
        return (abs(p[0] - r[0]) < 0.12 and abs(p[1] - r[1]) < 0.12
                and 0.88 < p[2] < 1.00)


class BottleOk(Check):
    def ok(self, scene):
        if (scene.holds("on", BOTTLE, BOTTLE_REGION) or
                scene.holds("in", BOTTLE, BOTTLE_REGION)):
            return True
        p = _objp(scene, BOTTLE)
        if p is None:
            return False
        r = _regionp(scene, BOTTLE_REGION, BOTTLE_FB)
        return (abs(p[0] - r[0]) < 0.13 and abs(p[1] - r[1]) < 0.13
                and 0.95 < p[2] < 1.30)


class StoveOn(Check):
    def ok(self, scene):
        return scene.holds("turnon", "flat_stove_1")


class Nop(Check):
    def ok(self, scene):
        return True


# ---------------- gripper ----------------

class OpenGrip(Gripper):
    GRIP = -1


class CloseGrip(Gripper):
    GRIP = +1


# ---------------- approach ----------------

class _Hover(MoveSkill):
    OBJ = None
    DZ = 0.15
    TOL = 0.05
    MAX_STEPS = 150

    def target(self, scene):
        p = _objp(scene, self.OBJ)
        if p is None:
            p = list(scene.eef)
        PRE[self.OBJ] = p[2]
        return ([p[0], p[1], p[2] + self.DZ], -1)


class _Descend(_Hover):
    pass


class BowlHover(_Hover):
    OBJ = BOWL
    DZ = 0.16


class BowlDown(_Descend):
    OBJ = BOWL
    DZ = BOWL_DESC


class BottleHover(_Hover):
    OBJ = BOTTLE
    DZ = 0.16


class BottleDown(_Descend):
    OBJ = BOTTLE
    DZ = BOTTLE_DESC


# ---------------- lift + verified hold ----------------

class _Lift(MoveSkill):
    OBJ = None
    TOL = 0.05
    MAX_STEPS = 60

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], e[2] + 0.12], 1)


class BowlLift(_Lift):
    OBJ = BOWL


class BottleLift(_Lift):
    OBJ = BOTTLE


class _Held(Check):
    """True only if the object actually rose with the gripper."""
    OBJ = None
    RISE = 0.05

    def ok(self, scene):
        p = _objp(scene, self.OBJ)
        if p is None:
            return False
        pre = PRE.get(self.OBJ, 0.90)
        if p[2] < pre + self.RISE:
            return False
        e = scene.eef
        GRASP[self.OBJ] = [e[0] - p[0], e[1] - p[1], e[2] - p[2]]
        return True


class BowlHeld(_Held):
    OBJ = BOWL


class BottleHeld(_Held):
    OBJ = BOTTLE


# ---------------- geometric placing ----------------

class _Place(MoveSkill):
    OBJ = None
    REGION = None
    FB = None
    DZ = 0.03
    TOL = 0.05
    MAX_STEPS = 200

    def target(self, scene):
        d = GRASP.get(self.OBJ)
        if d is None:
            return (list(scene.eef), 1)
        r = _regionp(scene, self.REGION, self.FB)
        return ([r[0] + d[0], r[1] + d[1], r[2] + self.DZ + d[2]], 1)


class BowlAbove(_Place):
    OBJ, REGION, FB = BOWL, BOWL_REGION, BOWL_FB
    DZ = 0.15


class BowlPlace(_Place):
    OBJ, REGION, FB = BOWL, BOWL_REGION, BOWL_FB
    DZ = 0.03
    TOL = 0.06


class BottleAbove(_Place):
    OBJ, REGION, FB = BOTTLE, BOTTLE_REGION, BOTTLE_FB
    DZ = 0.16


class BottlePlace(_Place):
    OBJ, REGION, FB = BOTTLE, BOTTLE_REGION, BOTTLE_FB
    DZ = 0.04
    TOL = 0.10


class Retreat(MoveSkill):
    TOL = 0.05
    MAX_STEPS = 100

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], min(e[2] + 0.12, 1.35)], -1)


# ---------------- VLA fallbacks (only if geometry fails) ----------------

class BowlPickVLA(VLASkill):
    INSTRUCTION = "pick up the black bowl"
    MAX_STEPS = 150

    def done(self, scene):
        p = _objp(scene, BOWL)
        return p is not None and p[2] > PRE.get(BOWL, 0.90) + 0.05


class BottlePickVLA(VLASkill):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 150

    def done(self, scene):
        p = _objp(scene, BOTTLE)
        return p is not None and p[2] > PRE.get(BOTTLE, 0.90) + 0.05


class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 200

    def done(self, scene):
        return scene.holds("turnon", "flat_stove_1")


# ---------------- behavior tree ----------------

def place_of(obj):
    if obj == BOWL:
        return ("bowl_above", "bowl_place", "bowl_ok")
    return ("bottle_above", "bottle_place", "bottle_ok")


def task(obj, hover, down, lift, held, above, place, ok, vla, fallback_dz):
    geom = Sequence(
        Leaf("open_grip"),
        Retry(2, Sequence(Leaf(hover), Leaf(down), Leaf("close_grip"),
                          Leaf(lift), Leaf(held))),
        Leaf(above), Leaf(place), Leaf("open_grip"), Leaf("retreat"), Leaf(ok),
    )
    vla_seq = Sequence(
        Leaf("open_grip"), Leaf(hover), Leaf(vla), Leaf(lift), Leaf(held),
        Leaf(above), Leaf(place), Leaf("open_grip"), Leaf("retreat"), Leaf(ok),
    )
    return Fallback(Leaf(ok), geom, vla_seq, Leaf(ok))


def build():
    bottle = task(BOTTLE, "bottle_hover", "bottle_down", "bottle_lift",
                  "bottle_held", "bottle_above", "bottle_place", "bottle_ok",
                  "bottle_pick_vla", 0.04)
    bowl = task(BOWL, "bowl_hover", "bowl_down", "bowl_lift",
                "bowl_held", "bowl_above", "bowl_place", "bowl_ok",
                "bowl_pick_vla", 0.03)
    # stove last: it must stay cold while the arm works near the cook region
    return Sequence(bottle, bowl, Fallback(Leaf("stove_on"), Leaf("turn_on_stove")))


# ---------------- registration ----------------

def apply(ctx, config):
    yield ctx.registry.register("bowl_ok", VERSION, BowlOk)
    yield ctx.registry.register("bottle_ok", VERSION, BottleOk)
    yield ctx.registry.register("stove_on", VERSION, StoveOn)
    yield ctx.registry.register("nop", VERSION, Nop)

    yield ctx.registry.register("open_grip", VERSION, OpenGrip)
    yield ctx.registry.register("close_grip", VERSION, CloseGrip)

    yield ctx.registry.register("bowl_hover", VERSION, BowlHover)
    yield ctx.registry.register("bowl_down", VERSION, BowlDown)
    yield ctx.registry.register("bowl_lift", VERSION, BowlLift)
    yield ctx.registry.register("bowl_held", VERSION, BowlHeld)
    yield ctx.registry.register("bowl_above", VERSION, BowlAbove)
    yield ctx.registry.register("bowl_place", VERSION, BowlPlace)

    yield ctx.registry.register("bottle_hover", VERSION, BottleHover)
    yield ctx.registry.register("bottle_down", VERSION, BottleDown)
    yield ctx.registry.register("bottle_lift", VERSION, BottleLift)
    yield ctx.registry.register("bottle_held", VERSION, BottleHeld)
    yield ctx.registry.register("bottle_above", VERSION, BottleAbove)
    yield ctx.registry.register("bottle_place", VERSION, BottlePlace)

    yield ctx.registry.register("retreat", VERSION, Retreat)

    yield ctx.registry.register("bowl_pick_vla", VERSION, BowlPickVLA)
    yield ctx.registry.register("bottle_pick_vla", VERSION, BottlePickVLA)
    yield ctx.registry.register("turn_on_stove", VERSION, TurnOnStove)

    yield ctx.registry.register("main", VERSION, build)
