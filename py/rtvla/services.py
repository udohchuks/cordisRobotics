"""Fixed services (Step 3): never swapped. Plugins reach them through ctx."""
import hashlib
import itertools
import json
import threading
import time


class PluginHung(BaseException):
    """Raised by the watchdog inside a plugin call that ran too long. A
    BaseException, so a plugin's `except Exception` cannot swallow it."""


class Registry:
    """Node registry (Step 4): name -> live version. Cordis service broker."""

    def __init__(self):
        self.lock = threading.Lock()
        self.entries = {}  # name -> list of (uid, version, node_class), in load order
        self.live = {}     # name -> uid chosen as live
        self._uid = itertools.count(1)

    def register(self, name, version, node_class):
        """A plugin calls this from apply(); returns the undo."""
        with self.lock:
            uid = next(self._uid)
            self.entries.setdefault(name, []).append((uid, version, node_class))
            if name not in self.live:
                self.live[name] = uid

        def undo():
            with self.lock:
                lst = self.entries.get(name, [])
                self.entries[name] = [e for e in lst if e[0] != uid]
                if not self.entries[name]:
                    del self.entries[name]
                if self.live.get(name) == uid:
                    rest = self.entries.get(name)
                    if rest:
                        self.live[name] = rest[-1][0]
                    else:
                        self.live.pop(name, None)
        return undo

    def newest(self, name):
        with self.lock:
            return self.entries[name][-1][0]

    def set_live(self, name, uid):
        with self.lock:
            assert any(e[0] == uid for e in self.entries[name])
            self.live[name] = uid

    def lookup(self, name):
        """(version, node_class) of the live version."""
        with self.lock:
            uid = self.live[name]
            for e in self.entries[name]:
                if e[0] == uid:
                    return e[1], e[2]
        raise KeyError(name)

    def size(self):
        with self.lock:
            return sum(len(v) for v in self.entries.values())


class Blackboard:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v


class Settings:
    """Plain hand-set values for now (Step 4 'simple version')."""

    def __init__(self, values):
        self.values = dict(values)
        self.version = 1

    def of(self, node):
        return dict(self.values.get(node, {}))


class Tokens:
    def __init__(self):
        self._n = itertools.count(1)
        self.cancelled = set()
        self.lock = threading.Lock()

    def new(self):
        return next(self._n)

    def cancel(self, t):
        with self.lock:
            self.cancelled.add(t)

    def ok(self, t):
        with self.lock:
            return t not in self.cancelled


class Ownership:
    """Who may drive the arm now: owner (1 code, 2 vla), token, node."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.lock = threading.Lock()
        self.owner, self.token, self.node = 0, 0, ""

    def take(self, owner, node):
        """Ownership passes straight to the new node; the old token is cancelled."""
        with self.lock:
            if self.token:
                self.tokens.cancel(self.token)
            self.token = self.tokens.new()
            self.owner, self.node = owner, node
            return self.token

    def release(self, token):
        with self.lock:
            if token == self.token:
                self.tokens.cancel(token)
                self.owner, self.token, self.node = 0, 0, ""
                return True
            self.tokens.cancel(token)
            return False

    def check(self, token):
        with self.lock:
            return token == self.token and self.tokens.ok(token)

    def snapshot(self):
        with self.lock:
            return (self.owner, self.token, self.node)


class Inbox:
    """Chunk inbox: latest wins; only the current owner's token gets in."""

    def __init__(self, ownership):
        self.own = ownership
        self.lock = threading.Lock()
        self.item = None
        self.owner_none = False
        self.rejected = 0
        self.by_node = {}

    def put(self, chunk):
        if not self.own.check(chunk["token"]):
            self.rejected += 1
            n = chunk.get("node", "")
            self.by_node[n] = self.by_node.get(n, 0) + 1
            return False
        with self.lock:
            self.item = chunk
        return True

    def put_owner_none(self):
        with self.lock:
            self.item = None
            self.owner_none = True

    def take(self):
        with self.lock:
            it, on = self.item, self.owner_none
            self.item, self.owner_none = None, False
            return it, on


class RobotState:
    def __init__(self):
        self.lock = threading.Lock()
        self.s = None

    def update(self, s):
        with self.lock:
            self.s = s

    def get(self):
        with self.lock:
            return dict(self.s) if self.s else None


class SentTable:
    """chunk id -> what was sent (node, version, run, token, start, actions)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.t = {}

    def add(self, cid, rec):
        with self.lock:
            self.t[cid] = rec

    def get(self, cid):
        with self.lock:
            return self.t.get(cid)

    def all(self):
        with self.lock:
            return dict(self.t)


def state_hash(*objs):
    return hashlib.sha256(json.dumps(objs, sort_keys=True, default=str).encode()).hexdigest()[:16]


class Ctx:
    """Everything a plugin may touch."""

    def __init__(self, settings):
        self.registry = Registry()
        self.blackboard = Blackboard()
        self.settings = Settings(settings)
        self.tokens = Tokens()
        self.ownership = Ownership(self.tokens)
        self.inbox = Inbox(self.ownership)
        self.robot = RobotState()
        self.sent = SentTable()
        self.bridge = None     # set by the runtime
        self.workers = None    # thread pool for slow work
        self.clock = time.monotonic
        # halt requests: Python only asks; Rust owns the halt floor and confirms
        self.halt_lock = threading.Lock()
        self.halt_seq = 0
        self.halt_token = 0
        self.halt_log = []        # (halt_seq, token, monotonic time of the request)
        self.in_plugin = None     # (name, run, token, t_start) while plugin code runs
        self.watchdog_s = 0.5
        self.watchdog_fired = []
        self.rust_rejected_by_node = {}   # node name -> chunks Rust refused (non-finite)
        self.inbox_rejected_by_node = {}  # node name -> chunks refused for a wrong token

    def revoke(self, token):
        """Halt a run: its token is cancelled here and Rust is asked to drop
        every chunk with a token <= it (queued or already playing)."""
        if not token:
            return
        self.tokens.cancel(token)
        with self.halt_lock:
            self.halt_seq += 1
            self.halt_token = max(self.halt_token, token)
            self.halt_log.append((self.halt_seq, token, time.monotonic()))
        if self.bridge is not None:
            self.bridge.wake.set()      # send it now, not at the next 33 ms cycle
