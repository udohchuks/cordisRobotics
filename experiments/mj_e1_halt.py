"""Route 1, experiment 1: halt before collision (MuJoCo SO-101).

A code node sweeps the arm (shoulder_pan) toward the bowl wall at a fixed
speed, streaming 50-step joint chunks every 5 ticks through the real bridge.
When the plant's gripper-bowl distance drops to d, the halt is issued:
  nohalt   reference, nothing is issued (shows the collision)
  rust     ctx.revoke(token): Rust raises its halt floor, drops queued and
           playing chunks, decelerates at the joint accel cap
  pyonly   old behaviour: token revoked in Python only (no new chunks are sent),
           chunks already in Rust keep playing to their end
  stall    Python is inside a GIL-holding call when the halt is due; the
           halt is issued when the call returns; meanwhile only Rust's
           heartbeat rule protects the robot
Same controller, limits, stopping policy and start state in all conditions.
"""
import json, os, re, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sim", "mujoco"))
import numpy as np
from mjrun import start, plant_read, load_plant, ROOT  # noqa
from ik import ik
from rtvla.bridge import Bridge  # noqa
from rtvla.services import Ctx  # noqa
import csv

OUT = os.path.join(ROOT, "results_mj", "e1"); os.makedirs(OUT, exist_ok=True)
Q_ARM, _ = ik((0.24, 0.0, 0.03), [0, 0, 0, 0.5, 0])     # low pose, gripper down
PAN0, PAN_GOAL = -0.55, 0.60
Q0 = [PAN0] + list(Q_ARM[1:5]) + [0.0]
RAMP = 4.0      # rad/s^2 planned acceleration of the sweep
GIL_N = 25


def plan(t, w):
    """planned pan angle t seconds after the sweep starts (accel ramp, then w)."""
    ta = w / RAMP
    x = 0.5 * RAMP * t * t if t < ta else 0.5 * RAMP * ta * ta + w * (t - ta)
    return min(PAN0 + x, PAN_GOAL)


def trial(cond, d_halt, w, rep, dur=6.0):
    tag = f"{cond}_d{int(d_halt*100)}_w{w}_r{rep}"
    # paired randomization: the seed depends only on (rep, w, d), so every
    # condition sees the same start pan and bowl position
    rng = np.random.default_rng(1000 * rep + int(w * 10) * 37 + int(d_halt * 100))
    global PAN0
    PAN0 = -0.55 + rng.uniform(-0.05, 0.05)
    bxy = (0.23 + rng.uniform(-0.01, 0.01), -0.09 + rng.uniform(-0.01, 0.01))
    q0 = [PAN0] + list(Q_ARM[1:5]) + [0.0]
    shm, plant, rust, pl_out, rs_log = start(q0, dur, "e1", plant_args=["--cube=0.0,0.28,0.0125", f"--bowl={bxy[0]},{bxy[1]},0"])
    ctx = Ctx({}); br = Bridge(ctx); br.start()
    while ctx.robot.get() is None or br.next_id is None:
        time.sleep(0.005)
    time.sleep(0.3)                                   # settle
    tok = ctx.ownership.take(1, "approach")
    t_start_tick = ctx.robot.get()["tick"] + 2
    stop = threading.Event()

    def node():                                       # the code node
        while not stop.is_set() and ctx.tokens.ok(tok):
            s = ctx.robot.get(); st = s["tick"] + 2
            acts = []
            for k in range(50):
                p = plan((st + k - t_start_tick) * 0.033, w) if st + k >= t_start_tick else PAN0
                acts.append([p] + list(Q_ARM[1:5]) + [0.0, 0.0])
            ctx.inbox.put({"token": tok, "node": "approach", "version": 1, "run": 0, "owner": 1,
                           "start": st, "built_on": s["chunk_playing"], "actions": acts, "target": acts[-1][:3]})
            time.sleep(5 * 0.033)
    th = threading.Thread(target=node, daemon=True); th.start()
    ev = {"cond": cond, "d_halt": d_halt, "w": w, "rep": rep, "pan0": PAN0, "bowl_xy": bxy}
    t0 = time.monotonic()
    while time.monotonic() - t0 < dur - 0.6:
        p = plant_read(shm)
        if p and p["dist"] <= d_halt and "cross_step" not in ev:
            ev["cross_step"] = p["step"]; ev["cross_tick"] = ctx.robot.get()["tick"]
            if cond == "rust":
                ctx.revoke(tok)
            elif cond == "pyonly":
                ctx.tokens.cancel(tok); stop.set()
            elif cond == "stall":
                re.match(r"(a+)+$", "a" * GIL_N + "b")        # holds the GIL
                ctx.revoke(tok)
            if cond != "nohalt":
                q = None
                while q is None:
                    q = plant_read(shm)
                ev["issue_step"] = q["step"]; ev["issue_tick"] = ctx.robot.get()["tick"]
                if cond in ("rust", "stall"):
                    ev["halt_seq"] = ctx.halt_seq
        time.sleep(0.0005)
    stop.set()
    br.stop_flag = True; time.sleep(0.1)
    rust.wait(); plant.wait(timeout=20)
    import shutil
    os.makedirs(os.path.join(OUT, "logs"), exist_ok=True)
    shutil.copy(pl_out, os.path.join(OUT, "logs", tag + "_plant.npz"))
    shutil.copy(rs_log, os.path.join(OUT, "logs", tag + "_ticks.csv"))
    return analyse(ev, pl_out, rs_log, tag)


def analyse(ev, pl_out, rs_log, tag):
    P, z = load_plant(pl_out)
    rows = list(csv.DictReader(open(rs_log)))
    ev["plant_lag_steps"] = int(z["lag_steps"]); ev["plant_steps"] = len(P["t"])
    ev["late_ticks"] = sum(1 for r in rows if int(r["late_us"]) > 33000)
    dt = float(z["dt"])
    f = P["fbowl"]
    ev["contact"] = bool((f > 0.01).any())
    ev["peak_force"] = float(f.max()); ev["impulse"] = float(f.sum() * dt)
    b0 = np.array([P["bx"][0], P["by"][0]]); b1 = np.array([P["bx"][-1], P["by"][-1]])
    ev["bowl_disp_mm"] = float(np.linalg.norm(b1 - b0) * 1000)
    ev["min_dist_mm"] = float(P["dist"].min() * 1000)
    ev["ftable_peak"] = float(P["ftable"].max())
    ev["plant_rtf"] = float(P["t"][-1] / P["wall"][-1])
    # t = 0 is the moment the halt was DUE (distance crossed d), for every condition
    if "cross_step" not in ev:
        ev["note"] = "never crossed"; json.dump(ev, open(os.path.join(OUT, tag + ".json"), "w")); return ev
    i0 = ev["cross_step"] - 1
    it = ev["cross_tick"]
    if "issue_step" in ev:
        ev["issue_ms_after_due"] = (ev["issue_step"] - ev["cross_step"]) * dt * 1000
    rows_t = [(int(r["tick"]), r) for r in rows]
    if "halt_seq" in ev:
        ack = [t for t, r in rows_t if int(r["halt_ack"]) >= ev["halt_seq"] and t >= ev["issue_tick"] - 1]
        ev["ack_ticks_after_issue"] = (ack[0] - ev["issue_tick"]) if ack else None
        ev["ack_ticks_after_due"] = (ack[0] - it) if ack else None
    c0 = np.array([float(r["c0"]) for _, r in rows_t]); tk = np.array([t for t, _ in rows_t])
    v = np.diff(c0) / 0.033                       # v[k]: commanded pan speed into tick tk[k+1]
    k_due = int(np.searchsorted(tk, it))
    v_ref = v[max(k_due - 1, 0)]
    brake = [int(tk[k + 1]) for k in range(k_due, len(v)) if v[k] < 0.9 * v_ref]
    ev["brake_ticks_after_due"] = (brake[0] - it) if brake else None
    reasons = [(t, int(r["reason"])) for t, r in rows_t if t >= it]
    hold = [(t, rs) for t, rs in reasons if rs in (2, 3, 4, 6)]
    ev["first_hold_ticks_after_due"] = (hold[0][0] - it) if hold else None
    ev["hold_reason"] = hold[0][1] if hold else None
    qv = np.gradient(P["q0"], dt)
    after = np.where((np.arange(len(qv)) > i0) & (np.abs(qv) < 0.02))[0]
    stop_i = int(after[0]) if len(after) else len(qv) - 1
    ev["stop_ms_after_due"] = (stop_i - i0) * dt * 1000
    tip = np.stack([P["tx"], P["ty"], P["tz"]], 1)
    ev["travel_after_due_mm"] = float(np.linalg.norm(np.diff(tip[i0:stop_i + 1], axis=0), axis=1).sum() * 1000)
    ev["tip_speed_at_due"] = float(np.linalg.norm(tip[i0 + 1] - tip[i0 - 4]) / (5 * dt))
    fc = np.where(f > 0.01)[0]
    ev["first_contact_ms_after_due"] = float((fc[0] - i0) * dt * 1000) if len(fc) else None
    json.dump(ev, open(os.path.join(OUT, tag + ".json"), "w"))
    return ev


if __name__ == "__main__":
    conds = sys.argv[1].split(","); ds = [float(x) for x in sys.argv[2].split(",")]
    ws = [float(x) for x in sys.argv[3].split(",")]; reps = int(sys.argv[4])
    for rep in range(reps):
        for w in ws:
            for d in ds:
                for c in conds:
                    if c == "nohalt" and d != ds[0]:
                        continue
                    e = trial(c, d, w, rep)
                    print(json.dumps({k: e.get(k) for k in ("cond", "d_halt", "w", "rep", "contact", "peak_force", "impulse", "bowl_disp_mm", "min_dist_mm", "issue_ms_after_due", "ack_ticks_after_issue", "brake_ticks_after_due", "first_hold_ticks_after_due", "hold_reason", "stop_ms_after_due", "travel_after_due_mm", "tip_speed_at_due", "late_ticks", "plant_lag_steps", "plant_rtf")}), flush=True)
