"""Keep-out monitor (MuJoCo demo): polls the plant's gripper-bowl distance
every 2 ms. It fires when the fingers ENTER the zone (distance drops below
`d` after having been above d + 5 mm) while a watched node owns the arm: that
run's token is revoked and Rust is asked to drop its chunks (the Rust-owned
halt path). Entry-only, so a node that starts inside the zone (e.g. after a
halt) can still move out."""
import struct
import threading
import time


class KeepOut(threading.Thread):
    def __init__(self, ctx, watched=("approach",), d=0.03):
        super().__init__(daemon=True)
        self.ctx, self.watched, self.d = ctx, set(watched), d
        self.stop_flag = False
        self.fired = []

    def run(self):
        shm = self.ctx.bridge.shm
        P = shm.L["plant"]
        o_seq, o_dist, o_step = P["p_seq"]["offset"], P["p_dist"]["offset"], P["p_step"]["offset"]
        armed = False
        while not self.stop_flag:
            s1 = struct.unpack_from("<Q", shm.mv, o_seq)[0]
            dist = struct.unpack_from("<d", shm.mv, o_dist)[0]
            step = struct.unpack_from("<Q", shm.mv, o_step)[0]
            if s1 % 2:
                time.sleep(0.0005); continue
            if dist > self.d + 0.005:
                armed = True
            if armed and dist < self.d:
                armed = False
                owner, token, node = self.ctx.ownership.snapshot()
                if node in self.watched and token and self.ctx.tokens.ok(token):
                    ver = run = None
                    for ev in reversed(self.ctx.events):
                        if ev[1] == "start" and ev[2] == node:
                            ver, run = ev[3], ev[4]
                            break
                    t = time.monotonic()
                    self.ctx.revoke(token)
                    self.ctx.events.append((t, "safety_halt", node, ver, run))
                    self.fired.append({"t": t, "node": node, "version": ver, "run": run, "token": token,
                                       "dist": dist, "plant_step": step, "halt_seq": self.ctx.halt_seq})
                else:
                    self.entries_unwatched = getattr(self, "entries_unwatched", 0) + 1
            time.sleep(0.002)
