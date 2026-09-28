# file: cook_setup.py
from kitchen import *

VERSION = 12

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
COOK = "flat_stove_1_cook_region"
RACK = "wine_rack_1_top_region"

COOK_FB = [-0.254, 0.202, 0.905]
RACK_FB = [-0.267, -0.251, 1.02]

BOWL_DESC = 0.035      # eef height above the bowl point for the grasp
BOTTLE_DESC = 0.07
BOWL_LIFT = 1.10       # fixed absolute lift targets -> always converge
BOTTLE_LIFT = 1.22

GRASP = {}             # obj -> [dx,dy,dz] = eef - object_point, while held


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


def _record_d(scene, obj):
    p = _objp(scene, obj)
    if p is None:
        return False
    e = scene.eef
    GRASP[obj] = [e[0] - p[0], e[1] - p[1], e[2] - p[2]]
    return True


# ---------- plain predicates ----------

def _bowl_on_cook(scene):
    if scene.holds("on", BOWL, COOK):
        return True
    p = _objp(scene, BOWL)
    if p is None:
        return False
    r = _regionp(scene, COOK, COOK_FB)
    return (abs(p[0] - r[0]) < 0.10 and abs(p[1] - r[1]) < 0.10
            and 0.87 < p[2] < 0.99)


def _bottle_on_rack(scene):
    if (scene.holds("on", BOTTLE, RACK) or scene.holds("in", BOTTLE, RACK)):
        return True
    p = _objp(scene, BOTTLE)
    if p is None:
        return False
    r = _regionp(scene, RACK, RACK_FB)
    return (abs(p[0] - r[0]) < 0.13 and abs(p[1] - r[1]) < 0.13
            and 0.95 < p[2] < 1.28)


def _stove_on(scene):
    return scene.holds("turnon", "flat_stove_1")


def _bowl_lifted(scene):
    p = _objp(scene, BOWL)
    if p is None or p[2] <= 0.945:
        return False
    _record_d(scene, BOWL)
    return True


def _bottle_lifted(scene):
    p = _objp(scene, BOTTLE)
    if p is None or p[2] <= 1.00:
        return False
    _record_d(scene, BOTTLE)
    return True


# ---------- checks ----------

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
        return _bowl_lifted(scene)


class BottleLifted(Check):
    def ok(self, scene):
        return _bottle_lifted(scene)


# ---------- gripper ----------

class OpenGrip(Gripper):
    GRIP = -1


class CloseGrip(Gripper):
    GRIP = +1


# ---------- approach / lift ----------

class _Hover(MoveSkill):
    OBJ = None
    DZ = 0.18
    TOL = 0.05
    MAX_STEPS = 150

    def target(self, scene):
        p = _objp(scene, self.OBJ) or list(scene.eef)
        return ([p[0], p[1], p[2] + self.DZ], -1)


class _Descend(_Hover):
    DZ = 0.05


class BowlHover(_Hover):
    OBJ = BOWL
    DZ = 0.18


class BowlDown(_Descend):
    OBJ = BOWL
    DZ = BOWL_DESC


class BottleHover(_Hover):
    OBJ = BOTTLE
    DZ = 0.20


class BottleDown(_Descend):
    OBJ = BOTTLE
    DZ = BOTTLE_DESC


class BowlLift(MoveSkill):
    TOL = 0.04
    MAX_STEPS = 100

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], BOWL_LIFT], 1)


class BottleLift(MoveSkill):
    TOL = 0.04
    MAX_STEPS = 120

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], BOTTLE_LIFT], 1)


# ---------- placing (rigid offset recorded while held) ----------

class _Place(MoveSkill):
    OBJ = None
    REGION = None
    FB = None
    DZ = 0.0
    TOL = 0.04
    MAX_STEPS = 200

    def target(self, scene):
        d = GRASP.get(self.OBJ)
        if d is None:
            return (list(scene.eef), 1)
        r = _regionp(scene, self.REGION, self.FB)
        return ([r[0] + d[0], r[1] + d[1], r[2] + self.DZ + d[2]], 1)


class BowlAbove(_Place):
    OBJ, REGION, FB = BOWL, COOK, COOK_FB
    DZ = 0.14


class BowlPlace(_Place):
    OBJ, REGION, FB = BOWL, COOK, COOK_FB
    DZ = 0.0
    TOL = 0.03


class BottleAbove(_Place):
    OBJ, REGION, FB = BOTTLE, RACK, RACK_FB
    DZ = 0.16


class BottlePlace(_Place):
    OBJ, REGION, FB = BOTTLE, RACK, RACK_FB
    DZ = 0.0
    TOL = 0.05


class Retreat(MoveSkill):
    TOL = 0.04
    MAX_STEPS = 120

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], 1.30], -1)


# ---------- VLA fallbacks ----------

class BowlPutVLA(VLASkill):
    INSTRUCTION = "put the black bowl on the stove"
    MAX_STEPS = 500

    def done(self, scene):
        return _bowl_on_cook(scene)


class BottlePutVLA(VLASkill):
    INSTRUCTION = "put the wine bottle on the wine rack"
    MAX_STEPS = 500

    def done(self, scene):
        return _bottle_on_rack(scene)


class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 200

    def done(self, scene):
        return _stove_on(scene)


# ---------- tasks ----------

def bowl_task():
    geom = Sequence(
        Leaf("open_grip"),
        Retry(2, Sequence(Leaf("bowl_hover"), Leaf("bowl_down"),
                          Leaf("close_grip"), Leaf("bowl_lift"), Leaf("bowl_lifted"))),
        Leaf("bowl_above"), Leaf("bowl_place"),
        Leaf("open_grip"), Leaf("retreat"), Leaf("bowl_ok"),
    )
    return Fallback(
        Leaf("bowl_ok"),
        geom,
        Sequence(Leaf("bowl_put_vla"), Leaf("bowl_ok")),
    )


def bottle_task():
    geom = Sequence(
        Leaf("open_grip"),
        Retry(2, Sequence(Leaf("bottle_hover"), Leaf("bottle_down"),
                          Leaf("close_grip"), Leaf("bottle_lift"), Leaf("bottle_lifted"))),
        Leaf("bottle_above"), Leaf("bottle_place"),
        Leaf("open_grip"), Leaf("retreat"), Leaf("bottle_ok"),
    )
    return Fallback(
        Leaf("bottle_ok"),
        geom,
        Sequence(Leaf("bottle_put_vla"), Leaf("bottle_ok")),
    )


def build():
    # stove stays off until the bowl is placed (hot-zone safety)
    return Sequence(
        bowl_task(),
        bottle_task(),
        Fallback(Leaf("stove_on"), Leaf("turn_on_stove")),
    )


# ---------- registration ----------

def apply(ctx, config):
    yield ctx.registry.register("bowl_ok", VERSION, BowlOk)
    yield ctx.registry.register("bottle_ok", VERSION, BottleOk)
    yield ctx.registry.register("stove_on", VERSION, StoveOn)
    yield ctx.registry.register("bowl_lifted", VERSION, BowlLifted)
    yield ctx.registry.register("bottle_lifted", VERSION, BottleLifted)

    yield ctx.registry.register("open_grip", VERSION, OpenGrip)
    yield ctx.registry.register("close_grip", VERSION, CloseGrip)

    yield ctx.registry.register("bowl_hover", VERSION, BowlHover)
    yield ctx.registry.register("bowl_down", VERSION, BowlDown)
    yield ctx.registry.register("bowl_lift", VERSION, BowlLift)
    yield ctx.registry.register("bowl_above", VERSION, BowlAbove)
    yield ctx.registry.register("bowl_place", VERSION, BowlPlace)

    yield ctx.registry.register("bottle_hover", VERSION, BottleHover)
    yield ctx.registry.register("bottle_down", VERSION, BottleDown)
    yield ctx.registry.register("bottle_lift", VERSION, BottleLift)
    yield ctx.registry.register("bottle_above", VERSION, BottleAbove)
    yield ctx.registry.register("bottle_place", VERSION, BottlePlace)

    yield ctx.registry.register("retreat", VERSION, Retreat)

    yield ctx.registry.register("bowl_put_vla", VERSION, BowlPutVLA)
    yield ctx.registry.register("bottle_put_vla", VERSION, BottlePutVLA)
    yield ctx.registry.register("turn_on_stove", VERSION, TurnOnStove)

    yield ctx.registry.register("main", VERSION, build)
