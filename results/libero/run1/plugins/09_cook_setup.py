# file: cook_setup.py
from kitchen import *

VERSION = 9

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
COOK = "flat_stove_1_cook_region"
RACK = "wine_rack_1_top_region"

COOK_FB = [-0.254, 0.202, 0.905]
RACK_FB = [-0.267, -0.251, 1.005]

GRASP = {}          # obj -> [dx,dy,dz] = eef - object_point, valid while held


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


def _d(scene, obj):
    if obj in GRASP:
        return GRASP[obj]
    p = _objp(scene, obj)
    if p is None:
        return None
    e = scene.eef
    return [e[0] - p[0], e[1] - p[1], e[2] - p[2]]


def _record(scene, obj):
    p = _objp(scene, obj)
    if p is None:
        return False
    e = scene.eef
    GRASP[obj] = [e[0] - p[0], e[1] - p[1], e[2] - p[2]]
    return True


# ---------------- goal checks (geometric: an air-closed gripper fools nothing) ----

class BowlOk(Check):
    def ok(self, scene):
        if scene.holds("on", BOWL, COOK):
            return True
        p = _objp(scene, BOWL)
        if p is None:
            return False
        r = _regionp(scene, COOK, COOK_FB)
        return (abs(p[0] - r[0]) < 0.10 and abs(p[1] - r[1]) < 0.10
                and 0.88 < p[2] < 0.98)


class BottleOk(Check):
    def ok(self, scene):
        if (scene.holds("on", BOTTLE, RACK) or scene.holds("in", BOTTLE, RACK)):
            return True
        p = _objp(scene, BOTTLE)
        if p is None:
            return False
        r = _regionp(scene, RACK, RACK_FB)
        return (abs(p[0] - r[0]) < 0.13 and abs(p[1] - r[1]) < 0.13
                and 0.95 < p[2] < 1.16)


class StoveOn(Check):
    def ok(self, scene):
        return scene.holds("turnon", "flat_stove_1")


# ---------------- held checks (rise = real grasp; also records the offset) ----

class BowlLifted(Check):
    def ok(self, scene):
        p = _objp(scene, BOWL)
        if p is None or p[2] <= 0.93:
            return False
        _record(scene, BOWL)
        return True


class BottleLifted(Check):
    def ok(self, scene):
        p = _objp(scene, BOTTLE)
        if p is None or p[2] <= 0.95:
            return False
        _record(scene, BOTTLE)
        return True


# ---------------- gripper ----------------

class OpenGrip(Gripper):
    GRIP = -1


class CloseGrip(Gripper):
    GRIP = +1


# ---------------- VLA picks ----------------

class BowlPickVLA(VLASkill):
    INSTRUCTION = "pick up the black bowl"
    MAX_STEPS = 300

    def done(self, scene):
        return BowlLifted().ok(scene)


class BottlePickVLA(VLASkill):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 300

    def done(self, scene):
        return BottleLifted().ok(scene)


class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 200

    def done(self, scene):
        return scene.holds("turnon", "flat_stove_1")


# ---------------- geometric bottle pick (fallback) ----------------

class BottleHover(MoveSkill):
    TOL = 0.04
    MAX_STEPS = 150

    def target(self, scene):
        p = _objp(scene, BOTTLE) or list(scene.eef)
        return ([p[0], p[1], p[2] + 0.20], -1)


class BottleDown(MoveSkill):
    TOL = 0.03
    MAX_STEPS = 150

    def target(self, scene):
        p = _objp(scene, BOTTLE) or list(scene.eef)
        return ([p[0], p[1], p[2] + 0.06], -1)


class BottleLift(MoveSkill):
    """Absolute target -> converges (a moving target never does)."""
    TOL = 0.04
    MAX_STEPS = 100

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], 1.22], 1)


# ---------------- geometric placing ----------------

class _Place(MoveSkill):
    OBJ = None
    REGION = None
    FB = None
    DZ = 0.0
    TOL = 0.05
    MAX_STEPS = 200

    def target(self, scene):
        d = _d(scene, self.OBJ)
        if d is None:
            return (list(scene.eef), 1)
        r = _regionp(scene, self.REGION, self.FB)
        return ([r[0] + d[0], r[1] + d[1], r[2] + self.DZ + d[2]], 1)


class BowlAbove(_Place):
    OBJ, REGION, FB = BOWL, COOK, COOK_FB
    DZ = 0.16
    TOL = 0.05


class BowlPlace(_Place):
    OBJ, REGION, FB = BOWL, COOK, COOK_FB
    DZ = 0.005
    TOL = 0.03


class BottleAbove(_Place):
    OBJ, REGION, FB = BOTTLE, RACK, RACK_FB
    DZ = 0.18
    TOL = 0.05


class BottlePlace(_Place):
    OBJ, REGION, FB = BOTTLE, RACK, RACK_FB
    DZ = 0.01
    TOL = 0.10          # the rack may block the last cm; release there


class Retreat(MoveSkill):
    """Absolute target -> always converges, clears the hot zone (stove off here)."""
    TOL = 0.04
    MAX_STEPS = 120

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], 1.30], -1)


# ---------------- tasks ----------------

def bowl_task():
    return Fallback(
        Leaf("bowl_ok"),
        Sequence(
            Leaf("open_grip"),
            Fallback(Leaf("bowl_lifted"),
                     Sequence(Leaf("bowl_pick_vla"), Leaf("bowl_lifted"))),
            Leaf("bowl_above"), Leaf("bowl_place"),
            Leaf("open_grip"), Leaf("retreat"),
            Leaf("bowl_ok"),
        ),
    )


def bottle_task():
    return Fallback(
        Leaf("bottle_ok"),
        Sequence(
            Leaf("open_grip"),
            Fallback(
                Sequence(Leaf("bottle_pick_vla"), Leaf("bottle_lifted")),
                Sequence(
                    Retry(2, Sequence(Leaf("bottle_hover"), Leaf("bottle_down"),
                                      Leaf("close_grip"), Leaf("bottle_lift"),
                                      Leaf("bottle_lifted"))),
                ),
            ),
            Leaf("bottle_above"), Leaf("bottle_place"),
            Leaf("open_grip"), Leaf("retreat"),
            Leaf("bottle_ok"),
        ),
    )


def build():
    return Sequence(
        bowl_task(),
        bottle_task(),
        Fallback(Leaf("stove_on"), Leaf("turn_on_stove")),
    )


# ---------------- registration ----------------

def apply(ctx, config):
    yield ctx.registry.register("bowl_ok", VERSION, BowlOk)
    yield ctx.registry.register("bottle_ok", VERSION, BottleOk)
    yield ctx.registry.register("stove_on", VERSION, StoveOn)
    yield ctx.registry.register("bowl_lifted", VERSION, BowlLifted)
    yield ctx.registry.register("bottle_lifted", VERSION, BottleLifted)

    yield ctx.registry.register("open_grip", VERSION, OpenGrip)
    yield ctx.registry.register("close_grip", VERSION, CloseGrip)

    yield ctx.registry.register("bottle_hover", VERSION, BottleHover)
    yield ctx.registry.register("bottle_down", VERSION, BottleDown)
    yield ctx.registry.register("bottle_lift", VERSION, BottleLift)

    yield ctx.registry.register("bowl_above", VERSION, BowlAbove)
    yield ctx.registry.register("bowl_place", VERSION, BowlPlace)
    yield ctx.registry.register("bottle_above", VERSION, BottleAbove)
    yield ctx.registry.register("bottle_place", VERSION, BottlePlace)
    yield ctx.registry.register("retreat", VERSION, Retreat)

    yield ctx.registry.register("bowl_pick_vla", VERSION, BowlPickVLA)
    yield ctx.registry.register("bottle_pick_vla", VERSION, BottlePickVLA)
    yield ctx.registry.register("turn_on_stove", VERSION, TurnOnStove)

    yield ctx.registry.register("main", VERSION, build)
