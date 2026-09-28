# file: cook_setup.py
from kitchen import *

VERSION = 5

BOWL = "akita_black_bowl_1"
BOTTLE = "wine_bottle_1"
BOWL_REGION = "flat_stove_1_cook_region"
BOTTLE_REGION = "wine_rack_1_top_region"

# fallbacks if scene.pos(<region>) is unavailable
BOWL_FB = [-0.254, 0.202, 0.905]
BOTTLE_FB = [-0.267, -0.251, 0.95]

BOWL_DZ = 0.06      # eef height above the bowl's reported point when grasping
BOTTLE_DZ = 0.10    # same for the bottle

GRASP = {}          # obj -> [dx,dy,dz] = eef - object_pos, valid while held


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
        if all(x == x for x in p):          # not NaN
            return p
    except Exception:
        pass
    return list(fb)


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


# ---------------- grasp check (also records the held offset) ----------------

class _Grasp(Check):
    OBJ = None

    def ok(self, scene):
        p = _objp(scene, self.OBJ)
        try:
            w = scene.gripper_width
        except Exception:
            return False
        if p is None or w > 0.075:
            return False
        e = scene.eef
        if abs(e[0] - p[0]) > 0.07 or abs(e[1] - p[1]) > 0.07:
            return False
        if not (-0.06 < e[2] - p[2] < 0.16):
            return False
        GRASP[self.OBJ] = [e[0] - p[0], e[1] - p[1], e[2] - p[2]]
        return True


class BottleGrasp(_Grasp):
    OBJ = BOTTLE


class BowlGrasp(_Grasp):
    OBJ = BOWL


# ---------------- gripper ----------------

class OpenGrip(Gripper):
    GRIP = -1


class CloseGrip(Gripper):
    GRIP = +1


# ---------------- geometric moves ----------------

class _Move(MoveSkill):
    TOL = 0.02
    MAX_STEPS = 120


class _Hover(_Move):
    OBJ = None
    DZ = 0.15

    def target(self, scene):
        p = _objp(scene, self.OBJ) or scene.eef
        return ([p[0], p[1], p[2] + self.DZ], -1)


class _Descend(_Hover):
    OBJ = None
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
            return (list(scene.eef), 1)          # nothing held: hold still
        r = _regionp(scene, self.REGION, self.FB)
        return ([r[0] + d[0], r[1] + d[1], r[2] + self.DZ + d[2]], 1)


class BottleAbove(_Place):
    OBJ, REGION, FB = BOTTLE, BOTTLE_REGION, BOTTLE_FB
    DZ = 0.13


class BottlePlace(_Place):
    OBJ, REGION, FB = BOTTLE, BOTTLE_REGION, BOTTLE_FB
    DZ = 0.01


class BowlAbove(_Place):
    OBJ, REGION, FB = BOWL, BOWL_REGION, BOWL_FB
    DZ = 0.13


class BowlPlace(_Place):
    OBJ, REGION, FB = BOWL, BOWL_REGION, BOWL_FB
    DZ = 0.01


class Retreat(_Move):
    """Lift straight up; target clamped, so it always converges."""
    def target(self, scene):
        e = scene.eef
        return ([e[0], e[1], min(e[2] + 0.10, 1.35)], -1)


# ---------------- VLA fallbacks ----------------

class _VLAPick(VLASkill):
    OBJ = None
    MIN_Z = 0.95

    def done(self, scene):
        p = _objp(scene, self.OBJ)
        try:
            w = scene.gripper_width
        except Exception:
            return False
        if p is None or w > 0.075 or p[2] < self.MIN_Z:
            return False
        e = scene.eef
        if abs(e[0] - p[0]) > 0.10 or abs(e[1] - p[1]) > 0.10:
            return False
        GRASP[self.OBJ] = [e[0] - p[0], e[1] - p[1], e[2] - p[2]]
        return True


class BottlePickVLA(_VLAPick):
    INSTRUCTION = "pick up the wine bottle"
    MAX_STEPS = 150
    OBJ = BOTTLE
    MIN_Z = 0.95


class BowlPickVLA(_VLAPick):
    INSTRUCTION = "pick up the black bowl"
    MAX_STEPS = 150
    OBJ = BOWL
    MIN_Z = 0.945


class TurnOnStove(VLASkill):
    INSTRUCTION = "turn on the stove"
    MAX_STEPS = 200

    def done(self, scene):
        return scene.holds("turnon", "flat_stove_1")


# ---------------- behavior tree ----------------

def build():
    bottle = Fallback(
        Leaf("bottle_ok"),
        Sequence(Leaf("open_grip"), Leaf("bottle_hover"), Leaf("bottle_down"),
                 Leaf("close_grip"), Leaf("bottle_grasp"),
                 Leaf("bottle_above"), Leaf("bottle_place"),
                 Leaf("open_grip"), Leaf("retreat"), Leaf("bottle_ok")),
        Sequence(Leaf("bottle_pick_vla"),
                 Leaf("bottle_above"), Leaf("bottle_place"),
                 Leaf("open_grip"), Leaf("retreat"), Leaf("bottle_ok")),
    )
    bowl = Fallback(
        Leaf("bowl_ok"),
        Sequence(Leaf("open_grip"), Leaf("bowl_hover"), Leaf("bowl_down"),
                 Leaf("close_grip"), Leaf("bowl_grasp"),
                 Leaf("bowl_above"), Leaf("bowl_place"),
                 Leaf("open_grip"), Leaf("retreat"), Leaf("bowl_ok")),
        Sequence(Leaf("bowl_pick_vla"),
                 Leaf("bowl_above"), Leaf("bowl_place"),
                 Leaf("open_grip"), Leaf("retreat"), Leaf("bowl_ok")),
    )
    # stove stays off until everything else is done (hot-zone safety)
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
