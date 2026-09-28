"""Shared-memory layout: one source of truth for Rust and Python.

Every field is 8 bytes (u64, i64 or f64), little-endian, 8-byte aligned.
Arrays are n consecutive 8-byte values. Running this file writes layout.json,
which the Rust loop reads at startup, so both sides use the same offsets.
"""
import json
import os

MAX_STEPS = 50
ACT = 7  # x y z rx ry rz gripper (rotation unused in the toy sim)

COMMAND = [  # written by Python, read by Rust
    ("seq", "u64", 1),
    ("boot_id", "u64", 1),
    ("heartbeat", "u64", 1),
    ("chunk_id", "u64", 1),
    ("built_on", "u64", 1),
    ("start_tick", "i64", 1),
    ("owner", "u64", 1),        # 0 none, 1 code, 2 vla
    ("steps_used", "u64", 1),   # 0 means "owner none": hold now
    ("token", "u64", 1),
    ("node_id", "u64", 1),
    ("reset_seq", "u64", 1),    # sim control: changes -> place cube
    ("reset_cube", "f64", 3),
    ("quit", "u64", 1),
    ("py_session", "u64", 1),   # random per Python start; Rust forgets old halts when it changes
    ("halt_seq", "u64", 1),     # halt request counter (Python bumps it on every halt)
    ("halt_token", "u64", 1),   # highest token Python asked to halt (tokens only grow)
    ("actions", "f64", MAX_STEPS * ACT),
]

STATE = [  # written by Rust, read by Python
    ("seq", "u64", 1),
    ("boot_id", "u64", 1),
    ("tick", "i64", 1),
    ("pose", "f64", ACT),
    ("last_cmd", "f64", ACT),
    ("last_chunk_seen", "u64", 1),
    ("chunk_playing", "u64", 1),
    ("chunk_queued", "u64", 1),
    ("step_playing", "i64", 1),
    ("reason", "u64", 1),
    ("cube", "f64", 3),
    ("cube_attached", "u64", 1),
    ("bowl", "f64", 3),
    ("successes", "u64", 1),
    ("releases", "u64", 1),
    ("heartbeat_seen", "u64", 1),
    ("halt_floor", "u64", 1),   # owned by Rust: chunks with token <= this never play
    ("halt_ack", "u64", 1),     # last halt_seq Rust applied
    ("halt_ack_tick", "i64", 1),
    ("rejected_bad", "u64", 1),     # chunks rejected for non-finite values
    ("rejected_halted", "u64", 1),  # chunks rejected because their token was halted
    ("session_seen", "u64", 1),
]

PLANT = [  # MuJoCo plant exchange (Route 1). r_*: written by Rust, p_*: written by the plant
    ("r_seq", "u64", 1),
    ("r_tick", "i64", 1),
    ("r_quit", "u64", 1),
    ("r_target", "f64", 6),     # joint targets after the limiter
    ("p_seq", "u64", 1),
    ("p_step", "u64", 1),
    ("p_time", "f64", 1),
    ("p_qpos", "f64", 6),
    ("p_qvel", "f64", 6),
    ("p_dist", "f64", 1),       # min distance gripper <-> bowl (m)
    ("p_rtf", "f64", 1),        # plant real-time factor
    ("p_force", "f64", 1),      # robot-bowl normal contact force (N)
    ("p_cube", "f64", 3),
    ("p_bowl", "f64", 3),
    ("p_tip", "f64", 3),
    ("p_cube_yaw", "f64", 1),
    ("p_resets", "u64", 1),
    # LIBERO mode (live_lib): Rust writes the 7-D command, the plant publishes
    # eef pos (3), eef axis-angle (3), gripper width (1)
    ("r_act", "f64", 7),
    ("p_lstate", "f64", 7),
    ("r_ring", "f64", 16 * 7),  # command of tick t at slot t % 16, so a slow plant can replay every tick
]

STATE_BASE = 4096
PLANT_BASE = 6144
TOTAL = 8192

REASONS = {0: "idle", 1: "play", 2: "hold_empty", 3: "hold_owner_none",
           4: "hold_heartbeat", 5: "blend", 6: "hold_halted"}


def build():
    out = {"max_steps": MAX_STEPS, "act": ACT, "total": TOTAL,
           "command": {}, "state": {}, "reasons": REASONS}
    off = 0
    for name, typ, n in COMMAND:
        out["command"][name] = {"offset": off, "type": typ, "n": n}
        off += 8 * n
    assert off <= STATE_BASE, off
    off = STATE_BASE
    for name, typ, n in STATE:
        out["state"][name] = {"offset": off, "type": typ, "n": n}
        off += 8 * n
    assert off <= PLANT_BASE, off
    out["plant"] = {}
    off = PLANT_BASE
    for name, typ, n in PLANT:
        out["plant"][name] = {"offset": off, "type": typ, "n": n}
        off += 8 * n
    assert off <= TOTAL, off
    return out


LAYOUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "layout.json")

if __name__ == "__main__":
    with open(LAYOUT_PATH, "w") as f:
        json.dump(build(), f, indent=1)
    print("wrote", os.path.abspath(LAYOUT_PATH))
