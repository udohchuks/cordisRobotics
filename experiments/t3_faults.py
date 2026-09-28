"""T3: fault cases, checked against Rust's own tick log.

(a) A VLA reply that arrives after its token was cancelled never plays
    (a1: normal path through the inbox; a2: the stale chunk is forced into
    the inbox anyway, so only the bridge's re-check at send can stop it).
(b) A halt with a chunk queued: owner-none takes effect within one tick
    and the queued chunk never plays (b2: same with the chunk already playing).
(c) Log consistency: every step Rust played belongs to a chunk Python sent,
    with a valid token at send, at step index = tick - start.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from common import start_rust, read_ticks, RESULTS  # noqa: E402
from rtvla.bridge import Bridge  # noqa: E402
from rtvla.services import Ctx  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 50


def line_chunk(ctx, token, node, start, n=30, dz=0.0):
    p = ctx.robot.get()["pose"]
    acts = [[p[0] + 0.001 * k, p[1], p[2] + dz, 0, 0, 0, 0.0] for k in range(n)]
    return {"token": token, "node": node, "version": 1, "run": 0, "owner": 1,
            "start": start, "built_on": 0, "actions": acts, "target": acts[-1][:3]}


def main():
    trial_s = 0.6
    log = "/tmp/t3_ticks.csv"
    rust = start_rust(N * 4 * trial_s + 10, log)
    ctx = Ctx({})
    br = Bridge(ctx)
    br.start()
    while ctx.robot.get() is None or br.next_id is None:
        time.sleep(0.01)
    cases = {"a1": [], "a2": [], "b1": [], "b2": []}
    for i in range(N):
        # ---- a1: reply after cancel, normal path
        tok = ctx.ownership.take(2, "vla")
        ctx.ownership.take(1, "approach")            # someone else takes over: tok cancelled
        tick = ctx.robot.get()["tick"]
        ok = ctx.inbox.put(line_chunk(ctx, tok, "vla", tick + 1))
        cases["a1"].append({"token": tok, "accepted_by_inbox": ok})
        time.sleep(trial_s / 2)
        # ---- a2: stale chunk forced into the inbox, bypassing put()
        tok2 = ctx.ownership.take(2, "vla")
        stale = line_chunk(ctx, tok2, "vla", ctx.robot.get()["tick"] + 1)
        ctx.ownership.take(1, "approach")            # cancels tok2
        with ctx.inbox.lock:
            ctx.inbox.item = stale                   # race: slipped in anyway
        cases["a2"].append({"token": tok2})
        time.sleep(trial_s / 2)
        # ---- b1: halt with a chunk queued (starts 15 ticks ahead)
        tok3 = ctx.ownership.take(1, "approach")
        ctx.inbox.put(line_chunk(ctx, tok3, "approach", ctx.robot.get()["tick"] + 15))
        time.sleep(0.1)                               # let the bridge send it
        ctx.revoke(tok3)                             # halt: Rust drops the token's chunks
        ctx.ownership.release(tok3)
        ctx.inbox.put_owner_none()                   # no driving node: owner none
        t_halt = time.monotonic()
        cases["b1"].append({"token": tok3, "t_halt": t_halt})
        time.sleep(trial_s)
        # ---- b2: halt while the chunk is playing
        tok4 = ctx.ownership.take(1, "approach")
        ctx.inbox.put(line_chunk(ctx, tok4, "approach", ctx.robot.get()["tick"] + 2, n=40))
        time.sleep(0.4)
        ctx.revoke(tok4)
        ctx.ownership.release(tok4)
        ctx.inbox.put_owner_none()
        cases["b2"].append({"token": tok4, "t_halt": time.monotonic()})
        time.sleep(trial_s)
    br.stop_flag = True
    time.sleep(0.1)
    br.quit_rust()
    rust.wait()
    rows = read_ticks(log)

    # ------------------------------------------------------------ checks
    played_tokens = {}
    for r in rows:
        if r["step"] != "-1":
            played_tokens.setdefault(int(r["token"]), 0)
            played_tokens[int(r["token"])] += 1
    res = {}
    res["a1_reply_after_cancel_never_plays"] = {
        "trials": N, "pass": sum(1 for c in cases["a1"] if played_tokens.get(c["token"], 0) == 0),
        "inbox_rejected": sum(1 for c in cases["a1"] if not c["accepted_by_inbox"])}
    res["a2_forced_stale_chunk_never_plays"] = {
        "trials": N, "pass": sum(1 for c in cases["a2"] if played_tokens.get(c["token"], 0) == 0)}

    # b cases: the chunk was really sent (queued/playing) before the halt; the
    # owner-none written after the halt is first seen by Rust at tick k, and
    # from k on the arm holds and the token never plays again.
    sent = br.sent_log
    sent_tokens = {x[2] for x in sent}
    on_sends = [x for x in sent if x[3] == "owner_none"]
    first_seen = {}
    for r in rows:
        first_seen.setdefault(int(r["seen"]), int(r["tick"]))
    for key, name in (("b1", "b1_halt_queued_chunk_never_plays"), ("b2", "b2_halt_playing_chunk_stops")):
        p, lat, played = 0, [], []
        for c in cases[key]:
            on = [x for x in on_sends if x[0] >= c["t_halt"] - 0.05]
            if not on or c["token"] not in sent_tokens:
                continue
            on_id, on_state_tick = on[0][1], on[0][6]
            k = first_seen.get(on_id)
            tok_ticks = [int(r["tick"]) for r in rows if int(r["token"]) == c["token"] and r["step"] != "-1"]
            held = rows[k]["reason"] in ("3", "6") if k is not None else False
            after = [t for t in tok_ticks if t >= k] if k is not None else [1]
            ok = held and not after and (key == "b2" and len(tok_ticks) > 0 or key == "b1" and not tok_ticks)
            p += ok
            if k is not None:
                lat.append(k - on_state_tick)
            played.append(len(tok_ticks))
        res[name] = {"trials": N, "pass": p, "ticks_from_write_to_hold": sorted(set(lat)),
                     "steps_played_per_trial": sorted(set(played))}

    # ------------------------------------------------------------ (c) log consistency
    sent_tbl = ctx.sent.all()
    bad = 0
    checked = 0
    for r in rows:
        if r["step"] == "-1":
            continue
        checked += 1
        rec = sent_tbl.get(int(r["chunk"]))
        if rec is None or rec["token"] != int(r["token"]) or int(r["tick"]) - rec["start"] != int(r["step"]):
            bad += 1
    res["c_log_matches_sent_chunks"] = {"rows_checked": checked, "mismatches": bad}
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(RESULTS, "t3.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
