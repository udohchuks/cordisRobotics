# file: cook_setup.py
from kitchen import *

VERSION = 6

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
BOWL_REGION = "flat_stove_1_cook_region"
BOTTLE_REGION = "wine_rack_1_top_region"

BOWL_FB = [-0.254, 0.202, 0.905]
BOTTLE_FB = [-0.267, -0.251, 0.95]

BOWL_DZ = 0.05
BOTTLE_DZ = 0.09

TOL = 0.05          # controller has ~0.03 m steady-state error

GRASP = {}          # obj -> [dx,dy,dz] = eef - object_pos, frozen at grasp time


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


def _try_record(obj, scene):
    """Record the grasp offset once, only while the grip is actually closed."""
    if obj in GRASP:
        return
    p = _objp(scene, obj)
    if p is None:
        return
    try:
        w = scene.gripper_width
    except Exception:
        return
    if w > 0.075:
        return
    e = scene.eef
    if abs(e[0] - p[0]) > 0.09 or abs(e[1] - p[1]) > 0.09:
        return
    if not (-0.10 < e[2] - p[2] < 0.18):
        return
    GRASP[obj] = [e[0] - p[0], e[1] - p[1], e[2] - p[2]]


# ---------------- goal checks ----------------

class BowlOk(Check):
    def ok(self, scene):
        return scene.holds("on", BOWL, BOWL_REGION)


class BottleOk(Check):
    def ok(self, scene):
        return (scene.holds("on", BOTTLE, BOTTLE_REGION) or
                scene.holds("in", BOTTLE, BOTTLE_REGION))


class StoveOn(Check):
    def ok(self, scene):
        return scene.holds("turnon", "flat_stove_1")


class BottleGrasp(Check):
    def ok(self, scene):
        _try_record(BOTTLE, scene)
        return BOTTLE in GRASP


class BowlGrasp(Check):
    def ok(self, scene):
        _try_record(BOWL, scene)
        return BOWL in GRASP


# ---------------- gripper ----------------

class OpenGrip(Gripper):
    GRIP = -1


class CloseGrip(Gripper):
    GRIP = +1


# ---------------- geometric moves ----------------

class _Move(MoveSkill):
    TOL = TOL
    MAX_STEPS = 200


class _Hover(_Move):
    OBJ = None
    DZ = 0.15

    def target(self, scene):
        p = _objp(scene, self.OBJ) or scene.eef
        return ([p[0], p[1], p[2] + self.DZ], -1)


class _Descend(_Hover):
    DZ = 0.10


class BottleHover(_Hover):
    OBJ = BOTTLE


class BottleDown(_Descend):
    OBJ = BOTTLE
    DZ = BOTTLE_DZ


class BowlHover(_Hover):
    OBJ = BOWL


class BowlDown(_Descend):
    OBJ = BOWL
    DZ = BOWL_DZ


class _Place(_Move):
    OBJ = None
    REGION = None
    FB = None
    DZ = 0.13

    def target(self, scene):
        d = GRASP.get(self.OBJ)
        if d is None:
            return (list(scene.eef), 1)
        r = _regionp(scene, self.REGION, self.FB)
        return ([r[0] + d[0], r[1] + d[1], r[2] + self.DZ + d[2]], 1)


class BottleAbove(_Place):
    OBJ, REGION, FB = BOTTLE, BOTTLE_REGION, BOTTLE_FB
    DZ = 0.13


class BottlePlace(_Place):
    OBJ, REGION, FB = BOTTLE, BOTTLE_REGION, BOTTLE_FB
    DZ = 0.015


class BowlAbove(_Place):
    OBJ, REGION, FB = BOWL, BOWL_REGION, BOWL_FB
    DZ = 0.13


class BowlPlace(_Place):
    OBJ, REGION, FB = BOWL, BOWL_REGION, BOWL_FB
    DZ = 0.015


class Retreat(_Move):
    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], min(e[2] + 0.12, 1.35)], -1)


# ---------------- VLA fallbacks ----------------

class BottlePickVLA(VLASkill):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 150

    def done(self, scene):
        _try_record(BOTTLE, scene)
        return BOTTLE in GRASP


class BowlPickVLA(VLASkill):
    INSTRUCTION = "pick up the black bowl"
    MAX_STEPS = 150

    def done(self, scene):
        _try_record(BOWL, scene)
        return BOWL in GRASP


class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 200

    def done(self, scene):
        return scene.holds("turnon", "flat_stove_1")


# ---------------- behavior tree ----------------

def pick_place(obj, hover, descend, grasp, above, place, ok, pick_vla):
    return Fallback(
        Leaf(ok),
        Sequence(Leaf("open_grip"), Leaf(hover), Leaf(descend),
                 Leaf("close_grip"), Leaf(grasp),
                 Leaf(above), Leaf(place),
                 Leaf("open_grip"), Leaf("retreat"), Leaf(ok)),
        Sequence(Leaf(pick_vla),
                 Leaf(above), Leaf(place),
                 Leaf("open_grip"), Leaf("retreat"), Leaf(ok)),
    )


def build():
    bottle = pick_place(BOTTLE, "bottle_hover", "bottle_down", "bottle_grasp",
                        "bottle_above", "bottle_place", "bottle_ok", "bottle_pick_vla")
    bowl = pick_place(BOWL, "bowl_hover", "bowl_down", "bowl_grasp",
                      "bowl_above", "bowl_place", "bowl_ok", "bowl_pick_vla")
    return Sequence(bottle, bowl, Fallback(Leaf("stove_on"), Leaf("turn_on_stove")))


# ---------------- registration ----------------

def apply(ctx, config):
    yield ctx.registry.register("bowl_ok", VERSION, BowlOk)
    yield ctx.registry.register("bottle_ok", VERSION, BottleOk)
    yield ctx.registry.register("stove_on", VERSION, StoveOn)
    yield ctx.registry.register("bottle_grasp", VERSION, BottleGrasp)
    yield ctx.registry.register("bowl_grasp", VERSION, BowlGrasp)

    yield ctx.registry.register("open_grip", VERSION, OpenGrip)
    yield ctx.registry.register("close_grip", VERSION, CloseGrip)

    yield ctx.registry.register("bottle_hover", VERSION, BottleHover)
    yield ctx.registry.register("bottle_down", VERSION, BottleDown)
    yield ctx.registry.register("bowl_hover", VERSION, BowlHover)
    yield ctx.registry.register("bowl_down", VERSION, BowlDown)
    yield ctx.registry.register("bottle_above", VERSION, BottleAbove)
    yield ctx.registry.register("bottle_place", VERSION, BottlePlace)
    yield ctx.registry.register("bowl_above", VERSION, BowlAbove)
    yield ctx.registry.register("bowl_place", VERSION, BowlPlace)
    yield ctx.registry.register("retreat", VERSION, Retreat)

    yield ctx.registry.register("bottle_pick_vla", VERSION, BottlePickVLA)
    yield ctx.registry.register("bowl_pick_vla", VERSION, BowlPickVLA)
    yield ctx.registry.register("turn_on_stove", VERSION, TurnOnStove)

    yield ctx.registry.register("main", VERSION, build)
