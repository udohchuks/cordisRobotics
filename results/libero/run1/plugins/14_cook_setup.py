# file: cook_setup.py
from kitchen import *

VERSION = 14

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
COOK = "flat_stove_1_cook_region"
RACK = "wine_rack_1_top_region"

COOK_XY = (-0.254, 0.202)
RACK_XY = (-0.267, -0.251)

BOWL_UP_Z = 0.95
BOTTLE_UP_Z = 0.98
BOWL_DOWN = 0.045     # eef above bowl point when grasping
BOTTLE_DOWN = 0.10
BOWL_LIFT = 1.12
BOTTLE_LIFT = 1.25
BOWL_ON_Z = 0.91      # desired bowl centre once placed
BOTTLE_ON_Z = 1.08    # desired bottle centre once placed

OFF = {}              # obj -> [dx,dy,dz] = eef - object, captured while held


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


def _record(scene, obj):
    p = _objp(scene, obj)
    if p is None:
        return
    e = scene.eef
    OFF[obj] = [e[0] - p[0], e[1] - p[1], e[2] - p[2]]


# ---------------- predicates ----------------

def _on_cook(scene):
    if scene.holds("on", BOWL, COOK):
        return True
    p = _objp(scene, BOWL)
    if p is None:
        return False
    x, y = _region_xy(scene, COOK, COOK_XY)
    return abs(p[0] - x) < 0.12 and abs(p[1] - y) < 0.12 and p[2] < 1.00


def _on_rack(scene):
    if scene.holds("on", BOTTLE, RACK) or scene.holds("in", BOTTLE, RACK):
        return True
    p = _objp(scene, BOTTLE)
    if p is None:
        return False
    x, y = _region_xy(scene, RACK, RACK_XY)
    return abs(p[0] - x) < 0.15 and abs(p[1] - y) < 0.15 and 0.95 < p[2] < 1.40


def _stove_on(scene):
    return scene.holds("turnon", "flat_stove_1")


def _bowl_up(scene):
    p = _objp(scene, BOWL)
    return p is not None and p[2] > BOWL_UP_Z


def _bottle_up(scene):
    p = _objp(scene, BOTTLE)
    return p is not None and p[2] > BOTTLE_UP_Z


# ---------------- checks ----------------

class BowlOk(Check):
    def ok(self, scene):
        return _on_cook(scene)


class BottleOk(Check):
    def ok(self, scene):
        return _on_rack(scene)


class StoveOn(Check):
    def ok(self, scene):
        return _stove_on(scene)


class BowlGrasped(Check):
    def ok(self, scene):
        if not _bowl_up(scene):
            return False
        _record(scene, BOWL)
        return True


class BottleGrasped(Check):
    def ok(self, scene):
        if not _bottle_up(scene):
            return False
        _record(scene, BOTTLE)
        return True


class Nop(Check):
    def ok(self, scene):
        return True


# ---------------- gripper ----------------

class OpenGrip(Gripper):
    GRIP = -1


class CloseGrip(Gripper):
    GRIP = +1


# ---------------- geometric bowl ----------------

class BowlSide(MoveSkill):
    TOL = 0.07
    MAX_STEPS = 70

    def target(self, scene):
        p = _objp(scene, BOWL) or list(scene.eef)
        return ([p[0], p[1] + 0.16, p[2] + 0.22], -1)


class BowlHover(MoveSkill):
    TOL = 0.05
    MAX_STEPS = 70

    def target(self, scene):
        p = _objp(scene, BOWL) or list(scene.eef)
        return ([p[0], p[1], p[2] + 0.17], -1)


class BowlDown(MoveSkill):
    TOL = 0.03
    MAX_STEPS = 70

    def target(self, scene):
        p = _objp(scene, BOWL) or list(scene.eef)
        return ([p[0], p[1], p[2] + BOWL_DOWN], -1)


class BowlLift(MoveSkill):
    TOL = 0.04
    MAX_STEPS = 80

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], BOWL_LIFT], 1)


# ---------------- geometric bottle ----------------

class BottleHover(MoveSkill):
    TOL = 0.05
    MAX_STEPS = 90

    def target(self, scene):
        p = _objp(scene, BOTTLE) or list(scene.eef)
        return ([p[0], p[1], p[2] + 0.20], -1)


class BottleDown(MoveSkill):
    TOL = 0.04
    MAX_STEPS = 90

    def target(self, scene):
        p = _objp(scene, BOTTLE) or list(scene.eef)
        return ([p[0], p[1], p[2] + BOTTLE_DOWN], -1)


class BottleLift(MoveSkill):
    TOL = 0.04
    MAX_STEPS = 90

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], BOTTLE_LIFT], 1)


# ---------------- geometric placing ----------------

class BowlAbove(MoveSkill):
    TOL = 0.06
    MAX_STEPS = 90

    def target(self, scene):
        o = OFF.get(BOWL)
        if o is None:
            return (list(scene.eef), 1)
        x, y = _region_xy(scene, COOK, COOK_XY)
        return ([x + o[0], y + o[1], 1.30], 1)


class BowlPlace(MoveSkill):
    TOL = 0.03
    MAX_STEPS = 100

    def target(self, scene):
        o = OFF.get(BOWL)
        if o is None:
            return (list(scene.eef), 1)
        x, y = _region_xy(scene, COOK, COOK_XY)
        return ([x + o[0], y + o[1], BOWL_ON_Z + o[2]], 1)


class BottleAbove(MoveSkill):
    TOL = 0.06
    MAX_STEPS = 90

    def target(self, scene):
        o = OFF.get(BOTTLE)
        if o is None:
            return (list(scene.eef), 1)
        x, y = _region_xy(scene, RACK, RACK_XY)
        return ([x + o[0], y + o[1], 1.35], 1)


class BottlePlace(MoveSkill):
    TOL = 0.03
    MAX_STEPS = 100

    def target(self, scene):
        o = OFF.get(BOTTLE)
        if o is None:
            return (list(scene.eef), 1)
        x, y = _region_xy(scene, RACK, RACK_XY)
        return ([x + o[0], y + o[1], BOTTLE_ON_Z + o[2]], 1)


class Retreat(MoveSkill):
    TOL = 0.04
    MAX_STEPS = 100

    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], 1.35], -1)


# ---------------- VLA ----------------

class BowlPickVLA(VLASkill):
    INSTRUCTION = "pick up the black bowl"
    MAX_STEPS = 500

    def done(self, scene):
        return _bowl_up(scene)


class BowlPutVLA(VLASkill):
    INSTRUCTION = "put the black bowl on the stove"
    MAX_STEPS = 600

    def done(self, scene):
        return _on_cook(scene)


class BottlePickVLA(VLASkill):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 500

    def done(self, scene):
        return _bottle_up(scene)


class BottlePutVLA(VLASkill):
    INSTRUCTION = "put the wine bottle on the wine rack"
    MAX_STEPS = 600

    def done(self, scene):
        return _on_rack(scene)


class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 400

    def done(self, scene):
        return _stove_on(scene)


# ---------------- tasks ----------------

def bowl_pick_geom():
    return Fallback(
        Sequence(Leaf("bowl_side"), Leaf("bowl_hover"), Leaf("bowl_down"),
                 Leaf("close_grip"), Leaf("bowl_lift"), Leaf("bowl_grasped")),
        Sequence(Leaf("bowl_hover"), Leaf("bowl_down"),
                 Leaf("close_grip"), Leaf("bowl_lift"), Leaf("bowl_grasped")),
    )


def bowl_place_seq():
    return Sequence(Leaf("bowl_above"), Leaf("bowl_place"),
                    Leaf("open_grip"), Leaf("retreat"), Leaf("bowl_ok"))


def bowl_task():
    return Fallback(
        Leaf("bowl_ok"),
        Sequence(Leaf("open_grip"), bowl_pick_geom(), bowl_place_seq()),
        Sequence(Leaf("open_grip"),
                 Retry(2, Sequence(Leaf("bowl_pick_vla"), Leaf("bowl_grasped"))),
                 bowl_place_seq()),
        Sequence(Leaf("bowl_put_vla"), Leaf("bowl_ok")),
    )


def bottle_pick_geom():
    return Retry(2, Sequence(Leaf("bottle_hover"), Leaf("bottle_down"),
                             Leaf("close_grip"), Leaf("bottle_lift"),
                             Leaf("bottle_grasped")))


def bottle_place_seq():
    return Sequence(Leaf("bottle_above"), Leaf("bottle_place"),
                    Leaf("open_grip"), Leaf("retreat"), Leaf("bottle_ok"))


def bottle_task():
    return Fallback(
        Leaf("bottle_ok"),
        Sequence(Leaf("open_grip"), bottle_pick_geom(), bottle_place_seq()),
        Sequence(Leaf("open_grip"),
                 Retry(2, Sequence(Leaf("bottle_pick_vla"), Leaf("bottle_grasped"))),
                 bottle_place_seq()),
        Sequence(Leaf("bottle_put_vla"), Leaf("bottle_ok")),
    )


def build():
    # stove only after the bowl is really on the cook region, so the arm never
    # works in a hot zone; if it never gets there we simply don't turn it on.
    return Sequence(
        bowl_task(),
        bottle_task(),
        Fallback(Leaf("stove_on"),
                 Sequence(Leaf("bowl_ok"), Leaf("turn_on_stove"))),
    )


# ---------------- registration ----------------

def apply(ctx, config):
    yield ctx.registry.register("bowl_ok", VERSION, BowlOk)
    yield ctx.registry.register("bottle_ok", VERSION, BottleOk)
    yield ctx.registry.register("stove_on", VERSION, StoveOn)
    yield ctx.registry.register("bowl_grasped", VERSION, BowlGrasped)
    yield ctx.registry.register("bottle_grasped", VERSION, BottleGrasped)
    yield ctx.registry.register("nop", VERSION, Nop)

    yield ctx.registry.register("open_grip", VERSION, OpenGrip)
    yield ctx.registry.register("close_grip", VERSION, CloseGrip)

    yield ctx.registry.register("bowl_side", VERSION, BowlSide)
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

    yield ctx.registry.register("bowl_pick_vla", VERSION, BowlPickVLA)
    yield ctx.registry.register("bowl_put_vla", VERSION, BowlPutVLA)
    yield ctx.registry.register("bottle_pick_vla", VERSION, BottlePickVLA)
    yield ctx.registry.register("bottle_put_vla", VERSION, BottlePutVLA)
    yield ctx.registry.register("turn_on_stove", VERSION, TurnOnStove)

    yield ctx.registry.register("main", VERSION, build)
