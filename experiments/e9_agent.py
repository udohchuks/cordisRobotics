"""E9: a real LLM agent repairs a node while the robot keeps running.

The runtime starts with a buggy `approach` plugin. After two failed
episodes, the agent (DeepSeek-V4.1-Flash, called in a worker thread) gets
the plugin source, the plugin API, and a failure report built only from
what the robot can observe (hand pose, seen cube pose, gripper events,
errors). Its reply is loaded as a Cordis swap with a 3-episode trial:
kept if all three succeed, else rolled back and the agent is told why
(up to 3 attempts). Episodes keep running the whole time.

usage: e9_agent.py <bug> <run>     bug: aim_x height swap_xy sign_y
needs DEEPSEEK_API_KEY in the environment.
"""
import asyncio
import json
import os
import re
import ssl
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("RTVLA_EP_TIMEOUT", "15")
from common import start_rust, read_ticks, RESULTS, pin_python  # noqa: E402
from rtvla.runtime import Runtime, NODES  # noqa: E402

MODEL = "deepseek-flash"   # DeepSeek-V4.1-Flash
URL = "https://api.deepseek.com/chat/completions"
MAX_ATTEMPTS = 3

SYSTEM = ("You repair one plugin of a robot program while the robot keeps running. "
          "You get the current source of the `approach` plugin, the plugin API, and a failure "
          "report from the robot. Reply with the complete new plugin file in one ```python block.")

API = """Plugin API (Python):
- A plugin file defines apply(ctx, config), a generator; `yield ctx.registry.register("approach", VERSION, Cls)` registers the node class.
- `from basics import MoveTo` gives a code node that drives the hand in straight lines. Subclass it and implement waypoints(self, snap) returning a list of [x, y, z] points in metres (robot base frame). The node succeeds when the hand is within tolerance of the last point.
- self.ctx.blackboard.get("cube_seen") returns [x, y, z] of the cube centre as seen by the camera (z = 0.02 when on the table).
- self.s is this node's settings dict: {"handoff_height": 0.05, "tol": 0.004, "retarget": 0.005, "speed": 0.2}.
- Tree: perceive -> approach -> vla_grasp -> carry -> place -> retreat. The approach node must bring the open gripper to the hand-off point for the grasp. vla_grasp (a learned policy) then moves straight down 5 cm from where approach stopped and closes the gripper. A grasp works only if the gripper closes within 1.5 cm of the cube centre.
"""


def call_llm(messages):
    ctx = ssl.create_default_context(cafile="/root/.ccr/ca-bundle.crt") \
        if os.path.exists("/root/.ccr/ca-bundle.crt") else ssl.create_default_context()
    body = json.dumps({"model": MODEL, "messages": messages, "max_tokens": 32000}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300, context=ctx) as r:
        out = json.load(r)
    return out["choices"][0]["message"]["content"], out.get("usage", {})


def extract_code(text):
    m = re.findall(r"```(?:python)?\n(.*?)```", text, re.S)
    return m[-1] if m else text


def fmt(v):
    return "(" + ", ".join(f"{x:.3f}" for x in v[:3]) + ")"


class Observer:
    """Per-episode record of what the robot observed (for the failure report)."""

    def __init__(self):
        self.ep = {}
        self.prev_grip = 0.0
        self.ev_i = 0

    def __call__(self, rt):
        n = len(rt.episodes)
        rec = self.ep.setdefault(n, {"approach_end": [], "closes": [], "errors": []})
        st = rt.ctx.robot.get()
        evs = rt.ctx.events
        for e in evs[self.ev_i:]:
            if e[2] == "approach" and e[1] == "success":
                rec["approach_end"].append((list(st["pose"][:3]), list(rt.ctx.blackboard.get("cube_seen"))))
            if e[1] == "error":
                rec["errors"].append(f"{e[2]}: {str(e[4]).strip().splitlines()[-1]}")
        self.ev_i = len(evs)
        g = st["last_cmd"][6]
        if g >= 0.5 > self.prev_grip:
            rec["closes"].append({"hand": list(st["pose"][:3]), "cube": list(st["cube"]), "tick": st["tick"]})
        for c in rec["closes"]:
            if "grasped" not in c and st["tick"] - c["tick"] >= 3:
                c["grasped"] = bool(st["cube_attached"])
        self.prev_grip = g

    def report(self, rt, idx):
        lines = []
        for i in idx:
            e, rec = rt.episodes[i], self.ep.get(i, {})
            lines.append(f"Episode {i}: {'succeeded' if e['ok'] else 'FAILED'}.")
            if os.environ.get("RTVLA_REPORT") == "minimal":   # no poses: only outcome, grasp result, errors
                for c in rec.get("closes", [])[:2]:
                    lines.append(f"  gripper closed; {'grasped' if c.get('grasped') else 'cube not grasped'}.")
                for err in rec.get("errors", [])[:3]:
                    lines.append(f"  error: {err}")
                continue
            for hand, cube in rec.get("approach_end", [])[:2]:
                lines.append(f"  approach finished with the hand at {fmt(hand)}; cube seen at {fmt(cube)}.")
            for c in rec.get("closes", [])[:2]:
                lines.append(f"  gripper closed with the hand at {fmt(c['hand'])}; cube at {fmt(c['cube'])}; "
                             f"{'grasped' if c.get('grasped') else 'not grasped'}.")
            for err in rec.get("errors", [])[:3]:
                lines.append(f"  error: {err}")
        return "\n".join(lines)


MESSAGES = {}


async def session(rt, bug, obs, log):
    # wait for two failed episodes (the bug may be intermittent)
    def failed():
        return [i for i, e in enumerate(rt.episodes) if not e["ok"]]
    while len(failed()) < 2:
        await asyncio.sleep(0.05)
    live_path = os.path.join(NODES, f"approach_bug_{bug}.py")
    report = obs.report(rt, failed()[:2])
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"{API}\nCurrent approach plugin:\n```python\n{open(live_path).read()}```\n\n"
                                            f"Failure report:\n{report}\n\nWrite the repaired plugin file."}]
    MESSAGES["m"] = messages
    log["t_first_report"] = time.monotonic()
    for k in range(MAX_ATTEMPTS):
        t0 = time.monotonic()
        eps_before = len(rt.episodes)
        tick_llm0 = rt.ctx.robot.get()["tick"]
        text, usage = await asyncio.to_thread(call_llm, messages)
        t_llm = time.monotonic() - t0
        eps_during = len(rt.episodes) - eps_before
        code = extract_code(text)
        path = f"/tmp/e9_{bug}_{log['run']}_{k}.py"
        with open(path, "w") as f:
            f.write(code)
        sw = {}
        await rt.swap("approach", path, trial_k=3, log=sw)
        att = {"attempt": k, "llm_s": round(t_llm, 1), "usage": usage, "episodes_during_llm": eps_during,
               "load_state": sw.get("load_state"), "error": sw.get("error"), "result": sw.get("result", sw.get("load_state")),
               "trial": sw.get("trial"), "identical_after": sw["fingerprint_before"] == sw["fingerprint_after"],
               "code": code, "tick_llm_start": tick_llm0,
               "t_llm_start": t0, "t_llm_end": t0 + t_llm,
               "t_live": sw.get("t_live"), "t_done": sw.get("t_done")}
        log["attempts"].append(att)
        messages.append({"role": "assistant", "content": text})
        if att["result"] == "kept":
            log["fixed"] = True
            log["t_fixed"] = time.monotonic()
            break
        if att["load_state"] != "ACTIVE":
            why = f"Your file failed to load and was rejected: {sw.get('error')}"
        else:
            n_trial = len(sw.get("trial") or [])
            idx = list(range(len(rt.episodes) - n_trial, len(rt.episodes)))
            why = "Your version was tried and rolled back. Trial:\n" + obs.report(rt, idx)
        messages.append({"role": "user", "content": why + "\n\nWrite the repaired plugin file again."})
    n0 = len(rt.episodes)
    while len(rt.episodes) < n0 + 3:
        await asyncio.sleep(0.05)
    log["after_ok"] = [e["ok"] for e in rt.episodes[n0:n0 + 3]]
    rt.stop = True


def main(bug, run):
    logf = f"/tmp/e9_{bug}_{run}.csv"
    rust = start_rust(900, logf)
    rust_t0 = time.monotonic() - 0.3   # start_rust sleeps 0.3 s after launch (approximate tick-0 time)
    pin_python()
    rt = Runtime(approach_path=os.path.join(NODES, f"approach_bug_{bug}.py"), seed=run)
    obs = Observer()
    rt.hooks.append(obs)
    log = {"bug": bug, "run": run, "model": MODEL, "attempts": [], "fixed": False}

    async def go():
        t = asyncio.create_task(rt.run(seconds=880))
        await session(rt, bug, obs, log)
        await t
    t_start = time.monotonic()
    asyncio.run(go())
    log["episode_times"] = [(e["start"], e["end"], e["ok"], e["approach_version"]) for e in rt.episodes]
    log["t_rust0"] = rust_t0
    rt.bridge.quit_rust()
    rust.wait()
    rows = read_ticks(logf)
    w = [int(x["write_us"]) for x in rows]
    log.update({"ticks": len(rows), "late": sum(1 for x in rows if int(x["late_us"]) > 33000),
                "max_gap_ms": max(b - a for a, b in zip(w, w[1:])) / 1000,
                "dead_token_steps": sum(1 for x in rows if x["step"] != "-1" and int(x["token"]) != 0
                                        and int(x["token"]) <= int(x["halt_floor"])),
                "s_report_to_fix": round(log["t_fixed"] - log["t_first_report"], 1) if log["fixed"] else None,
                "episodes": [e["ok"] for e in rt.episodes], "s_total": round(time.monotonic() - t_start, 1)})
    log.pop("t_first_report", None)
    log.pop("t_fixed", None)
    os.makedirs(os.path.join(RESULTS, "e9_transcripts"), exist_ok=True)
    log["report_mode"] = os.environ.get("RTVLA_REPORT", "full")
    log["messages"] = MESSAGES.get("m")
    with open(os.path.join(RESULTS, "e9_transcripts", f"{bug}_{run}_{log['report_mode']}.json"), "w") as f:
        json.dump(log, f, indent=1)
    short = {k: v for k, v in log.items() if k not in ("attempts", "messages")}
    short["attempts"] = [{k: v for k, v in a.items() if k != "code"} for a in log["attempts"]]
    log["report_mode"] = os.environ.get("RTVLA_REPORT", "full")
    short["report_mode"] = log["report_mode"]
    with open(os.path.join(RESULTS, "e9.jsonl"), "a") as f:
        f.write(json.dumps(short) + "\n")
    print(json.dumps(short), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
