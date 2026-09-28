"""Python side of the shared-memory bridge (seqlock read/write)."""
import json
import mmap
import os
import struct

from .layout import LAYOUT_PATH, build

SHM_PATH = os.environ.get("RTVLA_SHM", "/dev/shm/rtvla.shm")
_FMT = {"u64": "<Q", "i64": "<q", "f64": "<d"}


class Shm:
    def __init__(self, path=SHM_PATH, create=False):
        self.L = build()
        with open(LAYOUT_PATH) as f:
            assert json.load(f) == json.loads(json.dumps(self.L)), "layout.json out of date"
        if create:
            with open(path, "wb") as f:
                f.write(b"\0" * self.L["total"])
        fd = os.open(path, os.O_RDWR)
        self.mm = mmap.mmap(fd, self.L["total"])
        os.close(fd)
        self.mv = memoryview(self.mm)
        self.cmd_seq = 0

    # ---- raw field access -------------------------------------------------
    def _get(self, slot, name):
        spec = self.L[slot][name]
        fmt = _FMT[spec["type"]]
        if spec["n"] == 1:
            return struct.unpack_from(fmt, self.mv, spec["offset"])[0]
        return list(struct.unpack_from("<%dd" % spec["n"], self.mv, spec["offset"]))

    def _put(self, slot, name, value):
        spec = self.L[slot][name]
        if spec["n"] == 1:
            struct.pack_into(_FMT[spec["type"]], self.mv, spec["offset"], value)
        else:
            vals = list(value) + [0.0] * (spec["n"] - len(value))
            struct.pack_into("<%dd" % spec["n"], self.mv, spec["offset"], *vals)

    # ---- command slot: Python is the single writer -------------------------
    def write_command(self, **fields):
        """Seqlock write: seq odd -> write fields -> seq even."""
        self.cmd_seq = self._get("command", "seq") + 1
        if self.cmd_seq % 2 == 0:
            self.cmd_seq += 1
        self._put("command", "seq", self.cmd_seq)          # odd: writing
        for k, v in fields.items():
            self._put("command", k, v)
        self.cmd_seq += 1
        self._put("command", "seq", self.cmd_seq)          # even: done

    def read_command_field(self, name):
        return self._get("command", name)

    # ---- state slot: Rust is the single writer -----------------------------
    def read_state(self, retries=2):
        """Seqlock read. Returns a dict, or None if every try saw a write."""
        for _ in range(retries + 1):
            s1 = self._get("state", "seq")
            if s1 % 2:
                continue
            snap = {n: self._get("state", n) for n in self.L["state"] if n != "seq"}
            if self._get("state", "seq") == s1:
                snap["seq"] = s1
                return snap
        return None
