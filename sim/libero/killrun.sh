#!/bin/bash
# Stop a LIBERO run's processes (runtime, plant, Rust loop) without matching this shell.
for pid in $(pgrep -f 'python.*sim/libero/(agent_rt|plant)\.py|release/live_lib'); do
  [ "$pid" != "$$" ] && [ "$pid" != "$PPID" ] && kill "$pid" 2>/dev/null
done
