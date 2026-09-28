"""Task 1 check: Python writes a chunk; Rust must play exactly those steps.

Also a torn-read test: a writer thread hammers the state-slot-like pattern
and a reader must never accept a half-written snapshot.
"""
import csv
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py"))
from rtvla.shm import Shm  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
LIVE = os.environ.get("RTVLA_LIVE", os.path.join(ROOT, "rust", "target", "release", "live"))


def roundtrip():
    shm = Shm(create=True)
    log = "/tmp/rt_ticks.csv"
    proc = subprocess.Popen([LIVE, "--layout", os.path.join(ROOT, "layout.json"),
                             "--duration", "3", "--log", log])
    time.sleep(0.3)
    st = shm.read_state()
    tick = st["tick"]
    boot = st["boot_id"]
    start = tick + 5
    acts = []
    for i in range(20):  # move +x 5 mm per step from the start pose
        acts += [0.0 + 0.005 * i, 0.0, 0.15, 0, 0, 0, 0.0]
    shm.write_command(boot_id=boot, heartbeat=1, chunk_id=1, built_on=0,
                      start_tick=start, owner=1, steps_used=20, token=77,
                      node_id=3, actions=acts)
    # keep heartbeat alive
    for k in range(60):
        shm.write_command(heartbeat=2 + k)
        time.sleep(0.033)
    proc.wait()
    rows = list(csv.DictReader(open(log)))
    played = [r for r in rows if r["chunk"] == "1" and int(r["step"]) >= 0]
    steps = [int(r["step"]) for r in played]
    first_tick = int(played[0]["tick"])
    ok = (steps == list(range(20)) and first_tick == start
          and all(r["token"] == "77" for r in played))
    late = max(int(r["late_us"]) for r in rows)
    print(f"roundtrip: played steps 0..19 at start tick {first_tick} (asked {start}): {ok}; max lateness {late} us")
    return ok


def torn_read():
    """Writer updates seq + two fields that must always be equal."""
    shm = Shm(create=True)
    stop = False
    off_a = shm.L["state"]["tick"]["offset"]
    off_b = shm.L["state"]["step_playing"]["offset"]
    import struct

    def writer():
        v = 0
        while not stop:
            seq = struct.unpack_from("<Q", shm.mv, shm.L["state"]["seq"]["offset"])[0]
            struct.pack_into("<Q", shm.mv, shm.L["state"]["seq"]["offset"], seq + 1)
            struct.pack_into("<q", shm.mv, off_a, v)
            struct.pack_into("<q", shm.mv, off_b, v)
            struct.pack_into("<Q", shm.mv, shm.L["state"]["seq"]["offset"], seq + 2)
            v += 1
            if v % 50 == 0:
                time.sleep(0.0001)

    t = threading.Thread(target=writer)
    t.start()
    bad = got = none = 0
    t_end = time.time() + 2
    while time.time() < t_end:
        s = shm.read_state()
        if s is None:
            none += 1
            continue
        got += 1
        if s["tick"] != s["step_playing"]:
            bad += 1
    stop = True
    t.join()
    print(f"torn-read: {got} snapshots accepted, {bad} torn, {none} gave up (kept last good)")
    return bad == 0 and got > 0


if __name__ == "__main__":
    a = roundtrip()
    b = torn_read()
    sys.exit(0 if a and b else 1)
