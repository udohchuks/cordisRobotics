# file: cook_setup.py
from kitchen import *

VERSION = 13

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
COOK = "flat_stove_1_cook_region"
RACK = "wine_rack_1_top_region"

COOK_XY_FB = (-0.254, 0.202)
RACK_XY_FB = (-0.267, -0.251)

BOWL_LIFT_Z = 1.12
BOTTLE_LIFT_Z = 1.24

D = {}          # obj -> [dx,dy,dz] = eef - object, captured at the grasp


def _v(p):
    return [float(p[0]), float(p[1]), float(p[2])]


def _objp(scene, obj):
    try:
        return _v(scene.pos(obj))
    except Exception:
        return None


def _region_xy(scene, name, fb):
    try:
        p = _v(scene.pos(name))
        if all(x == x for x in p):
            return p[0], p[1]
    except Exception:
        pass
    return list(fb)


def _off(scene, obj):
    p = _objp(scene, obj)
    if p is None:
        return None
    e = scene.eef
    return [e[0] - p[0], e[1] - p[1], e[2] - p[2]]


def _grasp_off(scene, obj):
    o = D.get(obj)
    if o is None:
        o = _off(scene, obj)
        if o is not None:
            D[obj] = o
    return o


# ---------------- goal / state predicates ----------------

def _bowl_on_cook(scene):
    if scene.holds("on", BOWL, COOK):
        return True
    p = _objp(scene, BOWL)
    if p is None:
        return False
    x, y = _region_xy(scene, COOK, COOK_XY_FB)
    return abs(p[0] - x) < 0.11 and abs(p[1] - y) < 0.11 and p[2] < 1.00


def _bottle_on_rack(scene):
    if scene.holds("on", BOTTLE, RACK) or scene.holds("in", BOTTLE, RACK):
        return True
    p = _objp(scene, BOTTLE)
    if p is None:
        return False
    x, y = _region_xy(scene, RACK, RACK_XY_FB)
    return abs(p[0] - x) < 0.14 and abs(p[1] - y) < 0.14 and 0.95 < p[2] < 1.40


def _stove_on(scene):
    return scene.holds("turnon", "flat_stove_1")


def _bowl_lifted(scene):
    p = _objp(scene, BOWL)
    return p is not None and p[2] > 0.95


def _bottle_lifted(scene):
    p = _objp(scene, BOTTLE)
    return p is not None and p[2] > 0.98


# ---------------- checks ----------------

class BowlOk(Check):
    def ok(self, scene):
        return _bowl_on_cook(scene)


class BottleOk(Check):
    def ok(self, scene):
        return _bottle_on_rack(scene)


class StoveOn(Check):
    def ok(self, scene):
        return _stove_on(scene)


class BowlLifted(Check):
    def ok(self, scene):
        if _bowl_lifted(scene):
            _grasp_off(scene, BOWL)
            return True
        return False


class BottleLifted(Check):
    def ok(self, scene):
        if _bottle_lifted(scene):
            _grasp_off(scene, BOTTLE)
            return True
        return False


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
    DZ = 0.18
    TOL = 0.05
    MAX_STEPS = 250

    def target(self, scene):
        p = _objp(scene, self.OBJ) or list(scene.eef)
        return ([p[0], p[1], p[2] + self.DZ], -1)


class BowlPrep(MoveSkill):
    """Come in from -x, the direction the controller moves freely."""
    TOL = 0.06
    MAX_STEPS = 250

    def target(self, scene):
        p = _objp(scene, BOWL) or list(scene.eef)
        return ([p[0] - 0.14, p[1], p[2] + 0.22], -1)


class BowlHover(_Hover):
    OBJ = BOWL
    DZ = 0.18
    TOL = 0.09


class BowlDown(_Hover):
    OBJ = BOWL
    DZ = 0.055
    TOL = 0.05
    MAX_STEPS = 150


class BowlDown2(_Hover):
    OBJ = BOWL
    DZ = 0.015
    TOL = 0.05
    MAX_STEPS = 150


class BottleHover(_Hover):
    OBJ = BOTTLE
    DZ = 0.20
    TOL = 0.05


class BottleDown(_Hover):
    OBJ = BOTTLE
    DZ = 0.09
    TOL = 0.04
    MAX_STEPS = 200


class BottleLift(MoveSkill):
    TOL = 0.04
    MAX_STEPS = 150

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], BOTTLE_LIFT_Z], 1)


class BowlLift(MoveSkill):
    TOL = 0.04
    MAX_STEPS = 150

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], BOWL_LIFT_Z], 1)


# ---------------- placing: high approach, then descend to contact, then release

class _PlaceHigh(MoveSkill):
    OBJ = None
    REGION = None
    XY_FB = None
    HZ = 1.28
    TOL = 0.05
    MAX_STEPS = 250

    def target(self, scene):
        o = _grasp_off(scene, self.OBJ)
        if o is None:
            return (list(scene.eef), 1)
        x, y = _region_xy(scene, self.REGION, self.XY_FB)
        return ([x + o[0], y + o[1], self.HZ], 1)


class _PlaceLow(_PlaceHigh):
    HZ = 0.86
    TOL = 0.02
    MAX_STEPS = 130


class BowlAbove(_PlaceHigh):
    OBJ, REGION, XY_FB = BOWL, COOK, COOK_XY_FB
    HZ = 1.28


class BowlPlace(_PlaceLow):
    OBJ, REGION, XY_FB = BOWL, COOK, COOK_XY_FB
    HZ = 0.84


class BottleAbove(_PlaceHigh):
    OBJ, REGION, XY_FB = BOTTLE, RACK, RACK_XY_FB
    HZ = 1.30


class BottlePlace(_PlaceLow):
    OBJ, REGION, XY_FB = BOTTLE, RACK, RACK_XY_FB
    HZ = 0.88


class Retreat(MoveSkill):
    TOL = 0.04
    MAX_STEPS = 200

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], 1.32], -1)


# ---------------- VLA ----------------

class BowlPickVLA(VLASkill):
    INSTRUCTION = "pick up the black bowl"
    MAX_STEPS = 400

    def done(self, scene):
        return _bowl_lifted(scene)


class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 250

    def done(self, scene):
        return _stove_on(scene)


# ---------------- tasks ----------------

def bottle_task():
    pick = Retry(2, Sequence(Leaf("bottle_hover"), Leaf("bottle_down"),
                             Leaf("close_grip"), Leaf("bottle_lift"),
                             Leaf("bottle_lifted")))
    return Fallback(
        Leaf("bottle_ok"),
        Sequence(
            Leaf("open_grip"),
            Fallback(Leaf("bottle_lifted"), pick),
            Sequence(
                Leaf("bottle_above"),
                Fallback(Leaf("bottle_place"), Leaf("nop")),
                Leaf("open_grip"), Leaf("retreat"),
            ),
            Fallback(Leaf("bottle_ok"), Leaf("nop")),
        ),
        Leaf("nop"),
    )


def bowl_task():
    pick = Fallback(
        Sequence(Leaf("bowl_prep"), Leaf("bowl_hover"), Leaf("bowl_down"),
                 Leaf("close_grip"), Leaf("bowl_lift"), Leaf("bowl_lifted")),
        Sequence(Leaf("open_grip"), Leaf("bowl_hover"), Leaf("bowl_down2"),
                 Leaf("close_grip"), Leaf("bowl_lift"), Leaf("bowl_lifted")),
        Sequence(Leaf("open_grip"), Leaf("bowl_hover"), Leaf("bowl_pick_vla"),
                 Leaf("bowl_lifted")),
    )
    return Fallback(
        Leaf("bowl_ok"),
        Sequence(
            Leaf("open_grip"),
            Fallback(Leaf("bowl_lifted"), pick),
            Sequence(
                Leaf("bowl_lifted"),
                Leaf("bowl_above"),
                Fallback(Leaf("bowl_place"), Leaf("nop")),
                Leaf("open_grip"), Leaf("retreat"),
            ),
            Fallback(Leaf("bowl_ok"), Leaf("nop")),
        ),
        Leaf("nop"),
    )


def build():
    # bottle first (secures progress), bowl next, stove only once the bowl is
    # really on the cook region -- never place the bowl onto a hot stove.
    return Sequence(
        bottle_task(),
        bowl_task(),
        Fallback(Leaf("stove_on"),
                 Sequence(Leaf("bowl_ok"), Leaf("turn_on_stove"))),
    )


# ---------------- registration ----------------

def apply(ctx, config):
    yield ctx.registry.register("bowl_ok", VERSION, BowlOk)
    yield ctx.registry.register("bottle_ok", VERSION, BottleOk)
    yield ctx.registry.register("stove_on", VERSION, StoveOn)
    yield ctx.registry.register("bowl_lifted", VERSION, BowlLifted)
    yield ctx.registry.register("bottle_lifted", VERSION, BottleLifted)
    yield ctx.registry.register("nop", VERSION, Nop)

    yield ctx.registry.register("open_grip", VERSION, OpenGrip)
    yield ctx.registry.register("close_grip", VERSION, CloseGrip)

    yield ctx.registry.register("bowl_prep", VERSION, BowlPrep)
    yield ctx.registry.register("bowl_hover", VERSION, BowlHover)
    yield ctx.registry.register("bowl_down", VERSION, BowlDown)
    yield ctx.registry.register("bowl_down2", VERSION, BowlDown2)
    yield ctx.registry.register("bowl_lift", VERSION, BowlLift)
    yield ctx.registry.register("bowl_above", VERSION, BowlAbove)
    yield ctx.registry.register("bowl_place", VERSION, BowlPlace)

    yield ctx.registry.register("bottle_hover", VERSION, BottleHover)
    yield ctx.registry.register("bottle_down", VERSION, BottleDown)
    yield ctx.registry.register("bottle_lift", VERSION, BottleLift)
    yield ctx.registry.register("bottle_above", VERSION, BottleAbove)
    yield ctx.registry.register("bottle_place", VERSION, BottlePlace)

    yield ctx.registry.register("retreat", VERSION, Retreat)

    yield ctx.registry.register("bowl_pick_vla", VERSION, BowlPickVLA)
    yield ctx.registry.register("turn_on_stove", VERSION, TurnOnStove)

    yield ctx.registry.register("main", VERSION, build)
