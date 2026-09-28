"""Faulty repair for the MuJoCo demo: a sign error on y and a wrong height
constant send the gripper low toward the bowl wall instead of above the cube."""
from basics import MoveTo

VERSION = 3


class Approach(MoveTo):
    def waypoints(self, snap):
        c = self.ctx.blackboard.get("cube_seen")
        return [[c[0], -c[1], c[2] + 0.02]]          # planted bugs: -y, 2 cm instead of 5 cm


def apply(ctx, config):
    yield ctx.registry.register("approach", VERSION, Approach)
