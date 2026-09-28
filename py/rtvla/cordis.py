"""A small Python port of the Cordis core (Step 3).

- A plugin module defines apply(ctx, config) as a generator.
  Every `yield` hands the runtime one undo function (revertible effect).
- Loading runs apply() to the end, collecting undos in order.
  If apply() raises, the undos collected so far run newest-first and the
  fiber is marked FAILED (Cordis 4.4 "failure"): nothing is left behind.
- Unloading runs the undos newest-first (LIFO) and drops the module.
- Each load imports the file under a fresh module name, so an old and a new
  version can be loaded side by side (needed for trial and rollback).
"""
import importlib.util
import itertools
import sys
import traceback

INACTIVE, LOADING, ACTIVE, UNLOADING, FAILED = "INACTIVE", "LOADING", "ACTIVE", "UNLOADING", "FAILED"
_uid = itertools.count(1)


class Fiber:
    def __init__(self, path, config):
        self.uid = next(_uid)
        self.path = path
        self.config = config
        self.state = INACTIVE
        self.undos = []
        self.module = None
        self.module_name = None
        self.error = None

    def __repr__(self):
        return f"<Fiber {self.uid} {self.module_name} {self.state}>"


class Cordis:
    def __init__(self, ctx):
        self.ctx = ctx          # the fixed services plugins may use
        self.fibers = {}

    def load(self, path, config=None):
        f = Fiber(path, config or {})
        f.state = LOADING
        f.module_name = f"plugin_{f.uid}"
        try:
            spec = importlib.util.spec_from_file_location(f.module_name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f.module_name] = mod
            spec.loader.exec_module(mod)
            f.module = mod
            gen = mod.apply(self.ctx, f.config)
            for undo in gen:                     # one iteration = one effect
                f.undos.append(undo)
        except Exception as e:                   # roll back what was installed
            f.error = "".join(traceback.format_exception_only(type(e), e)).strip()
            self._run_undos(f)
            sys.modules.pop(f.module_name, None)
            f.module = None
            f.state = FAILED
            return f
        f.state = ACTIVE
        self.fibers[f.uid] = f
        return f

    def load_no_undo(self, path, config=None):
        """Baseline (dynamic software update without an effect log): run the
        plugin's setup, drop its undos; on a crash, whatever it did stays."""
        f = Fiber(path, config or {})
        f.module_name = f"plugin_{f.uid}"
        try:
            spec = importlib.util.spec_from_file_location(f.module_name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f.module_name] = mod
            spec.loader.exec_module(mod)
            f.module = mod
            for _ in mod.apply(self.ctx, f.config):
                pass
        except Exception as e:
            f.error = "".join(traceback.format_exception_only(type(e), e)).strip()
            f.state = FAILED
            return f
        f.state = ACTIVE
        f.no_undo = True
        return f

    def unload(self, f):
        if f.state != ACTIVE:
            return
        f.state = UNLOADING
        self._run_undos(f)
        sys.modules.pop(f.module_name, None)
        f.module = None
        self.fibers.pop(f.uid, None)
        f.state = INACTIVE

    @staticmethod
    def _run_undos(f):
        while f.undos:
            undo = f.undos.pop()                 # newest first
            try:
                undo()
            except Exception:
                traceback.print_exc()
