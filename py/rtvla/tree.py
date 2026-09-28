"""Behavior tree (Step 4). Control nodes follow BehaviorTree.CPP semantics."""
import itertools
import time
import traceback

from .services import PluginHung

RUNNING, SUCCESS, FAILURE = "running", "success", "failure"
_run = itertools.count(1)


class Node:
    def tick(self, ctx, snap):
        raise NotImplementedError

    def halt(self):
        pass


class _Guard:
    """Marks that plugin code is running, for the watchdog."""

    def __init__(self, ctx, leaf):
        self.ctx, self.leaf = ctx, leaf

    def __enter__(self):
        inst = self.leaf.inst
        with self.ctx.halt_lock:
            self.ctx.in_plugin = (self.leaf.name, self.leaf.run, getattr(inst, "token", None), time.monotonic())

    def __exit__(self, *exc):
        try:
            pass
        finally:
            with self.ctx.halt_lock:
                self.ctx.in_plugin = None
        return False


class Leaf(Node):
    """Looks up the live version of `name` in the registry at each start.
    Halting is done by the runtime, not by plugin code: on halt, or when the
    plugin raises or hangs, the run's token is revoked, so Rust drops its
    chunks even if the plugin's own halt() is buggy."""

    def __init__(self, name):
        self.name = name
        self.inst = None
        self.version = None
        self.run = None

    def _token(self):
        return getattr(self.inst, "token", None) if self.inst is not None else None

    def _error(self, ctx):
        ctx.events.append((time.monotonic(), "error", self.name, self.version, traceback.format_exc(limit=1), self.run))
        ctx.revoke(self._token())

    def tick(self, ctx, snap):
        if self.inst is None:
            self.ctx = ctx
            ctx.running.add(self.name)
            self.version, cls = ctx.registry.lookup(self.name)
            self.run = next(_run)
            ctx.events.append((time.monotonic(), "start", self.name, self.version, self.run))
            try:
                with _Guard(ctx, self):
                    self.inst = cls(ctx, ctx.settings.of(self.name), self.name, self.version, self.run)
                    self.inst.start(snap)
            except (Exception, PluginHung):
                self._error(ctx)
                self._end(ctx, FAILURE)
                return FAILURE
        try:
            with _Guard(ctx, self):
                st = self.inst.tick(snap)
        except (Exception, PluginHung):
            self._error(ctx)
            st = FAILURE
        if st == RUNNING:
            if getattr(self.inst, "DRIVES", False):
                ctx.driving_now = True
            return RUNNING
        self._end(ctx, st)
        return st

    def _end(self, ctx, st):
        try:
            if self.inst is not None:
                with _Guard(ctx, self):
                    self.inst.finish()
        except (Exception, PluginHung):
            pass
        ctx.events.append((time.monotonic(), st, self.name, self.version, self.run))
        ctx.running.discard(self.name)
        self.inst = None

    def halt(self):
        if self.inst is not None:
            tok = self._token()
            try:
                with _Guard(self.ctx, self):
                    self.inst.halt()
            except (Exception, PluginHung):
                pass
            finally:
                self.ctx.revoke(tok)      # runtime-owned: never depends on the plugin
                self.ctx.events.append((time.monotonic(), "halt", self.name, self.version, self.run))
                self.ctx.running.discard(self.name)
                self.inst = None

    @property
    def running(self):
        return self.inst is not None


class Sequence(Node):
    def __init__(self, *children):
        self.c = list(children)
        self.i = 0

    def tick(self, ctx, snap):
        while self.i < len(self.c):
            st = self.c[self.i].tick(ctx, snap)
            if st == RUNNING:
                return RUNNING
            if st == FAILURE:
                self.halt()
                return FAILURE
            self.i += 1
        self.halt()
        return SUCCESS

    def halt(self):
        for ch in self.c:
            ch.halt()
        self.i = 0


class Fallback(Node):
    def __init__(self, *children):
        self.c = list(children)
        self.i = 0

    def tick(self, ctx, snap):
        while self.i < len(self.c):
            st = self.c[self.i].tick(ctx, snap)
            if st == RUNNING:
                return RUNNING
            if st == SUCCESS:
                self.halt()
                return SUCCESS
            self.i += 1
        self.halt()
        return FAILURE

    def halt(self):
        for ch in self.c:
            ch.halt()
        self.i = 0


class ReactiveSequence(Node):
    """Re-ticks every child each tick; a failure halts the later children."""

    def __init__(self, *children):
        self.c = list(children)

    def tick(self, ctx, snap):
        for i, ch in enumerate(self.c):
            st = ch.tick(ctx, snap)
            if st == RUNNING:
                for later in self.c[i + 1:]:
                    later.halt()
                return RUNNING
            if st == FAILURE:
                self.halt()
                return FAILURE
        self.halt()
        return SUCCESS

    def halt(self):
        for ch in self.c:
            ch.halt()


class Retry(Node):
    def __init__(self, n, child):
        self.n, self.child, self.k = n, child, 0

    def tick(self, ctx, snap):
        st = self.child.tick(ctx, snap)
        if st == FAILURE:
            self.k += 1
            self.child.halt()
            if self.k < self.n:
                return RUNNING
            self.k = 0
            return FAILURE
        if st == SUCCESS:
            self.k = 0
        return st

    def halt(self):
        self.child.halt()
        self.k = 0


class Timeout(Node):
    def __init__(self, seconds, child):
        self.s, self.child, self.t0 = seconds, child, None

    def tick(self, ctx, snap):
        if self.t0 is None:
            self.t0 = time.monotonic()
        if time.monotonic() - self.t0 > self.s:
            self.halt()
            return FAILURE
        st = self.child.tick(ctx, snap)
        if st != RUNNING:
            self.t0 = None
        return st

    def halt(self):
        self.child.halt()
        self.t0 = None


class ForceFailure(Node):
    def __init__(self, child):
        self.child = child

    def tick(self, ctx, snap):
        st = self.child.tick(ctx, snap)
        return RUNNING if st == RUNNING else FAILURE

    def halt(self):
        self.child.halt()


def pick_place_tree():
    """The Step 4 example tree (outer Retry left to the episode runner)."""
    grasp_once = Sequence(
        Leaf("perceive"),
        ReactiveSequence(Leaf("cube_near_seen"), Leaf("approach")),
        Timeout(4.0, Leaf("vla_grasp")),
        Leaf("cube_in_gripper"),
    )
    get_cube = Fallback(
        Leaf("cube_in_gripper"),
        Retry(2, Fallback(grasp_once, ForceFailure(Leaf("recover")))),
    )
    return Sequence(
        get_cube,
        ReactiveSequence(Leaf("cube_in_gripper"), Leaf("carry")),
        Leaf("place"),
        Leaf("cube_in_bowl"),
        Leaf("retreat"),
    )
