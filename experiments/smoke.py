"""Smoke test: v1 (buggy) episodes, then v2 episodes. Prints outcomes."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, read_ticks, tick_metrics, pin_python, ROOT  # noqa: E402
from rtvla.runtime import Runtime, NODES  # noqa: E402

ver = sys.argv[1] if len(sys.argv) > 1 else "v2"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
log = "/tmp/smoke_ticks.csv"
p = start_rust(60, log)
pin_python()
rt = Runtime(approach_path=os.path.join(NODES, f"approach_{ver}.py"))
asyncio.run(rt.run(n_episodes=n))
rt.bridge.quit_rust()
p.wait()
for e in rt.episodes:
    print(f"episode v{e['approach_version']}: ok={e['ok']} {e['end']-e['start']:.1f}s")
for ev in rt.ctx.events[-60:]:
    print(ev[1:])
print(tick_metrics(read_ticks(log)))
print("tree tick max ms", max(rt.tick_times) * 1000)
