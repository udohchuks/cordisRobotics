"""A separate, persistent VLA process (baseline for 'restart the code process only').

It loads the real SmolVLA weights once, then serves grasp requests over a
Unix socket. For each request it waits the configured delay and returns the
stand-in chunk (the toy sim cannot use SmolVLA's joint actions), so the
code runtime can be restarted without reloading the model.
usage: python -m rtvla.vla_server /tmp/vla.sock
"""
import os
import sys
import threading
import time
from multiprocessing.connection import Listener

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nodes"))


def serve(addr):
    from rtvla import real_vla
    t0 = time.time()
    real_vla.load(int(os.environ.get("TORCH_THREADS", "1")))
    print(f"vla server: weights loaded in {time.time() - t0:.1f} s", flush=True)
    import basics
    if os.path.exists(addr):
        os.remove(addr)
    lis = Listener(addr, family="AF_UNIX")
    print("vla server: ready", flush=True)

    def handle(conn):
        try:
            while True:
                pose, delay, prefix = conn.recv()
                conn.send(basics.fake_vla(pose, "sleep", delay, 0, prefix, local=True))
        except (EOFError, OSError):
            pass
    while True:
        c = lis.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()


if __name__ == "__main__":
    serve(sys.argv[1] if len(sys.argv) > 1 else "/tmp/vla.sock")
