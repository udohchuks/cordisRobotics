"""Bridge thread (Step 2/3): the only Python code that touches shared memory.

Every 33 ms: read the state slot and publish robot state, bump the
heartbeat, and send the inbox's newest chunk if its token is still valid.
It runs in its own thread, outside the asyncio loop.
"""
import ctypes
import random
import threading
import time

from .shm import Shm
from .services import PluginHung  # noqa: F401  (re-exported)


class Bridge(threading.Thread):
    def __init__(self, ctx, period=0.033, node_ids=None):
        super().__init__(daemon=True)
        self.ctx = ctx
        self.shm = Shm()
        self.period = period
        self.stop_flag = False
        self.heartbeat = self.shm.read_command_field("heartbeat")
        self.next_id = None
        self.reset_req = None
        self.node_ids = node_ids or {}
        self.write_times = []
        self.sent_log = []   # (wall time, chunk id, token, node, start, steps) for T3
        self.session = random.getrandbits(62) | 1
        self.wake = threading.Event()
        self._wd_cur, self._wd_n = None, 0
        self._rej_bad, self._last_node = 0, None
        self.main_thread = threading.main_thread().ident
        ctx.bridge = self

    def request_reset(self, cube_xyz):
        self.reset_req = list(cube_xyz)

    def run(self):
        while self.next_id is None and not self.stop_flag:
            s = self.shm.read_state()
            if s and s["boot_id"]:
                self.ctx.robot.update(s)
                # the chunk counter never goes back: continue from what Rust saw
                self.next_id = max(s["last_chunk_seen"], self.shm.read_command_field("chunk_id")) + 1
            time.sleep(0.005)
        t_next = time.monotonic()
        woke = False
        while not self.stop_flag:
            s = self.shm.read_state()
            if s:
                self.ctx.robot.update(s)
                if s["rejected_bad"] > self._rej_bad:       # Rust refused the last chunk we sent
                    n = self._last_node or ""
                    self.ctx.rust_rejected_by_node[n] = self.ctx.rust_rejected_by_node.get(n, 0) + s["rejected_bad"] - self._rej_bad
                    self._rej_bad = s["rejected_bad"]
            self._watchdog()
            self.heartbeat += 1
            with self.ctx.halt_lock:
                hs, ht = self.ctx.halt_seq, self.ctx.halt_token
            fields = {"heartbeat": self.heartbeat, "py_session": self.session,
                      "halt_seq": hs, "halt_token": ht}
            if self.reset_req is not None:
                fields["reset_seq"] = self.shm.read_command_field("reset_seq") + 1
                fields["reset_cube"] = self.reset_req
                self.reset_req = None
            chunk, owner_none = self.ctx.inbox.take()
            boot = s["boot_id"] if s else 0
            if owner_none:
                cid = self._id()
                fields.update(boot_id=boot, chunk_id=cid, steps_used=0, owner=0,
                              token=0, built_on=0, start_tick=0)
                self.sent_log.append((time.monotonic(), cid, 0, "owner_none", 0, 0, s["tick"] if s else -1))
            elif chunk is not None and self.ctx.ownership.check(chunk["token"]):
                # re-check owner and token at send
                cid = self._id()
                acts = chunk.get("_joint", chunk["actions"])   # MuJoCo mode: IK done at put time
                flat = [v for a in acts for v in a]
                fields.update(boot_id=boot, chunk_id=cid, built_on=chunk["built_on"],
                              start_tick=chunk["start"], owner=chunk["owner"],
                              steps_used=len(chunk["actions"]), token=chunk["token"],
                              node_id=self.node_ids.get(chunk["node"], 9) * 100 + chunk["version"], actions=flat)
                chunk["sent_id"] = cid
                self._last_node = chunk["node"]
                self.ctx.sent.add(cid, dict(chunk, id=cid))
                self.sent_log.append((time.monotonic(), cid, chunk["token"], chunk["node"],
                                      chunk["start"], len(chunk["actions"]), s["tick"] if s else -1))
            self.shm.write_command(**fields)
            self.write_times.append(time.monotonic())
            if not woke:
                t_next += self.period
            dt = t_next - time.monotonic()
            if dt > 0:
                woke = self.wake.wait(dt)   # a halt wakes us early
                self.wake.clear()
            else:
                t_next = time.monotonic()
                woke = False

    def _watchdog(self):
        """A plugin call that runs too long (e.g. an endless loop) is halted:
        its token is revoked at once and an exception is raised inside it."""
        ctx = self.ctx
        with ctx.halt_lock:
            cur = ctx.in_plugin
            # count bridge cycles that saw the same call still running; a GIL
            # stall freezes this thread too, so it cannot cause a false alarm
            if cur is None or cur != self._wd_cur:
                self._wd_cur, self._wd_n = cur, 0
                return
            self._wd_n += 1
            # fire after watchdog_s of bridge cycles, and again every watchdog_s
            # while the same call is still stuck
            n_fire = int(round(ctx.watchdog_s / self.period))
            if self._wd_n < n_fire or self._wd_n % n_fire:
                return
            ctx.watchdog_fired.append(cur)
            ctx.halt_seq += 1
            ctx.halt_token = max(ctx.halt_token, cur[2] or 0)
            ctx.halt_log.append((ctx.halt_seq, cur[2], time.monotonic()))
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(self.main_thread),
                                                       ctypes.py_object(PluginHung))
        if cur[2]:
            ctx.tokens.cancel(cur[2])

    def _id(self):
        cid = self.next_id
        self.next_id += 1
        return cid

    def quit_rust(self):
        self.shm.write_command(quit=1)
