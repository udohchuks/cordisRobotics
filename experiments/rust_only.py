"""Rust loop alone (no Python at all) for N seconds: the machine's own timing noise."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, read_ticks, tick_metrics, RESULTS
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 300
p = start_rust(secs, "/tmp/rust_only.csv"); p.wait()
m = tick_metrics(read_ticks("/tmp/rust_only.csv")); print(m)
json.dump(m, open(os.path.join(RESULTS, "rust_only.json"), "w"), indent=1)
