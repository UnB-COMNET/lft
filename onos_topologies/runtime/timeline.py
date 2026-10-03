# Brief: Runs a timeline on the running topology: windows of link states, traffic flows, captures, host
# pauses and HTTP calls, each at its time. The timeline is a .py file of constants:
#   NAME = "degrade-s1"                      run name
#   RESULTS = "results/timeline/degrade-s1"  where it writes (default: results/timeline/<NAME>)
#   WINDOW_S = 60                            length of each window (s)
#   WARMUP_S = 30                            wait before the first window (s)
#   DEGRADE = {"rate": 0.1, "delay": 10, "loss": 0}   factors over a link's base for "degrade"
#   HOSTS = [("cl5", "s1", "lft-dash-client", "192.168.0.5", False)]   (name, switch, image, ip, server),
#                                            created for the run and removed after it
#   WINDOWS = [{}, {"s0-s1": "degrade"}, {"s1-s3": "down"}]   link states per window; absent = normal
#   FLOWS = [{"tool": "iperf3", "client": "cl0", "server": "ds0", "start": 0, "duration": 120}]
#                                            plus any option of traffic.start (rate, proto, port...)
#   EVENTS = [{"at": 30, "kind": "capture", "iface": "s0s1", "duration": 20},
#             {"at": 60, "kind": "pause", "host": "cl0", "duration": 10},
#             {"at": 90, "kind": "http", "url": "http://127.0.0.1:5000/deploy", "json": {...}}]
#   BEFORE = ["..."], AFTER = ["..."]        shell commands run before the warm-up and at the end
# Times count from the end of the warm-up. The run writes meta.json, the timeline, flows/ and pcap/,
# iperf_all.csv, dash_all.csv and ping_all.csv, and its events (results.py). On the way out (the end, or
# Ctrl+C) the flows stop, the paused hosts resume, the run's hosts go and the links return to their base.

import csv
import json
import subprocess
import threading
import time
import types
from pathlib import Path

import requests

from onos_topologies.runtime import TopologyError, capture, hosts, links, results, sessions, state, traffic

DEFAULTS = {"RESULTS": None, "WINDOW_S": 60, "WARMUP_S": 30, "DEGRADE": {"rate": 0.1, "delay": 10, "loss": 0},
            "HOSTS": [], "WINDOWS": [{}], "FLOWS": [], "EVENTS": [], "BEFORE": [], "AFTER": []}
FLOW_OPTIONS = ("tool", "client", "server", "port", "reverse", "proto", "rate", "duration", "interval")
TICK_S = 0.5


# Brief: The timeline's constants over DEFAULTS
def load(path: str) -> dict:
    module = types.ModuleType("timeline")   # executed in place, so no __pycache__ lands next to the file
    exec(compile(Path(path).read_text(), str(path), "exec"), module.__dict__)
    plan = {**DEFAULTS, **{k: v for k, v in vars(module).items() if k.isupper()}}
    if not plan.get("NAME"):
        raise TopologyError(f"{path} has no NAME")
    return plan


# Brief: Runs a timeline
# Params:
#   String path: The timeline .py
# Return:
#   Path of the run's directory
def run(path: str) -> Path:
    plan = load(path)
    run_dir = results.path(plan["RESULTS"] or f"timeline/{plan['NAME']}")
    if run_dir.exists() and any(run_dir.iterdir()):
        run_dir = run_dir.with_name(f"{run_dir.name}_{time.strftime('%Y%m%d-%H%M%S')}")
    run_dir.mkdir(parents=True)
    (run_dir / "timeline.py").write_text(Path(path).read_text())
    (run_dir / "meta.json").write_text(json.dumps({
        "name": plan["NAME"], "window_s": plan["WINDOW_S"], "windows": len(plan["WINDOWS"]), "degrade": plan["DEGRADE"],
        "hosts": [h[0] for h in plan["HOSTS"]], "flows": len(plan["FLOWS"]), "events": len(plan["EVENTS"]),
        "start_ts": int(time.time())}, indent=2))
    results.event(run_dir, type="run", state="start")

    flows = [{**f, "id": f"f{i}", "sid": None, "done": False} for i, f in enumerate(plan["FLOWS"], 1)]
    events = [{**e, "id": f"e{i}", "fired": False, "ended": False} for i, e in enumerate(plan["EVENTS"], 1)]
    captures, created, now, base = [], [], {}, {}
    try:
        results.event(run_dir, type="phase", name="hosts", text=f"Hosts: {', '.join(h[0] for h in plan['HOSTS']) or 'none'}")
        for name, switch, image, ip, server in plan["HOSTS"]:
            hosts.add(name, switch, ip, image, server)
            created.append(name)
            state.sync()
        results.event(run_dir, type="phase", name="before", text=f"{len(plan['BEFORE'])} commands")
        for command in plan["BEFORE"]:
            subprocess.run(command, shell=True, check=True)
        results.event(run_dir, type="phase", name="warmup", text=f"Waiting {plan['WARMUP_S']} s")
        time.sleep(plan["WARMUP_S"])

        base = {l["id"]: l for l in state.sync()["links"]}
        t0 = time.time()
        for k, window in enumerate(plan["WINDOWS"], 1):
            _set_links(window, now, base, plan["DEGRADE"])
            results.event(run_dir, type="window", index=k, state="start")
            results.event(run_dir, type="links", index=k, of=len(plan["WINDOWS"]),
                          states={lid: now.get(lid, "normal") for lid in base})
            while time.time() < t0 + k * plan["WINDOW_S"]:
                _tick(time.time() - t0, flows, events, captures, run_dir)
                time.sleep(TICK_S)
            results.event(run_dir, type="window", index=k, state="end")
    except KeyboardInterrupt:
        print("*** stop requested; keeping what was measured", flush=True)
    finally:
        results.event(run_dir, type="run", state="end")
        _close(flows, events, captures, run_dir)
        _merge(flows, run_dir)
        for name in created:
            hosts.rm(name)
        if base:
            _set_links({}, now, base, plan["DEGRADE"])
        for command in plan["AFTER"]:
            subprocess.run(command, shell=True)
        state.sync()
        results.event(run_dir, type="files", files=results.files(run_dir))
        results.event(run_dir, type="run", state="done")
    return run_dir


# Brief: Puts every link in the state the window asks for (normal, degrade or down), from the state it is in
def _set_links(window: dict, now: dict, base: dict, degrade: dict) -> None:
    for lid, link in base.items():
        want = window.get(lid, "normal")
        if want == now.get(lid, "normal"):
            continue
        a, b, values = link["a"], link["b"], link["base"]
        if want == "degrade":
            links.shape(a, b, rate=values["rate"] * degrade["rate"], delay=values["delay"] * degrade["delay"],
                        loss=degrade.get("loss", 0))
            links.up(a, b)
        elif want == "down":
            links.down(a, b)
        else:
            links.reset(a, b)
        now[lid] = want
        state.sync()


# Brief: Starts and stops what is due at t seconds
def _tick(t: float, flows: list, events: list, captures: list, run_dir: Path) -> None:
    for f in flows:
        if f["sid"] is None and not f["done"] and t >= f["start"]:
            try:
                meta = traffic.start(**{k: f[k] for k in FLOW_OPTIONS if k in f}, out=str(run_dir / "flows" / f["id"]))
                f["sid"] = meta["id"]
                results.event(run_dir, type="flow", id=f["id"], state="start", session=meta["id"], tool=f["tool"],
                              client=f["client"], server=f["server"], file=str(Path(meta["file"]).relative_to(run_dir)))
            except TopologyError as error:
                f["done"] = True
                results.event(run_dir, type="log", text=f"flow {f['id']} not started: {error}")
        elif f["sid"] and not f["done"] and t >= f["start"] + f["duration"]:
            _end_flow(f, run_dir)
    for e in events:
        if not e["fired"] and t >= e["at"]:
            e["fired"] = True
            _fire(e, captures, run_dir)
        elif e["fired"] and not e["ended"] and e["kind"] == "pause" and t >= e["at"] + e["duration"]:
            e["ended"] = True
            hosts.pause(e["host"], False)
            results.event(run_dir, type="event", id=e["id"], kind="pause", state="end", host=e["host"])


def _end_flow(f: dict, run_dir: Path) -> None:
    traffic.stop(f["sid"])
    f["done"] = True
    results.event(run_dir, type="flow", id=f["id"], state="end", session=f["sid"])


def _fire(e: dict, captures: list, run_dir: Path) -> None:
    fields = {k: e[k] for k in ("host", "iface", "url", "duration") if k in e}
    if e["kind"] == "capture":
        out = run_dir / "pcap" / f"{e['iface']}-{e['at']}.pcap"
        captures.append(capture.start(e["iface"], e["duration"], str(out))["id"])
        fields["file"] = str(out.relative_to(run_dir))
    elif e["kind"] == "pause":
        hosts.pause(e["host"], True)
    elif e["kind"] == "http":
        threading.Thread(target=_http, args=(e, run_dir), daemon=True).start()
    results.event(run_dir, type="event", id=e["id"], kind=e["kind"], state="start", **fields)


# Brief: One HTTP call of the timeline; its answer goes to the run's events
def _http(e: dict, run_dir: Path) -> None:
    try:
        r = requests.request(e.get("method", "POST"), e["url"], json=e.get("json"), timeout=180)
        results.event(run_dir, type="log", text=f"{e['id']} {e['url']} -> {r.status_code} {r.text[:300]}")
    except requests.RequestException as error:
        results.event(run_dir, type="log", text=f"{e['id']} {e['url']} failed: {error}")


# Brief: Stops whatever still runs: flows, captures, paused hosts
def _close(flows: list, events: list, captures: list, run_dir: Path) -> None:
    for f in flows:
        if f["sid"] and not f["done"]:
            _end_flow(f, run_dir)
    for sid in captures:
        capture.stop(sid)
    for e in events:
        if e["kind"] == "pause" and e["fired"] and not e["ended"]:
            e["ended"] = True
            hosts.pause(e["host"], False)


# Brief: One CSV per tool (iperf_all.csv, dash_all.csv, ping_all.csv) from the flows' outputs
def _merge(flows: list, run_dir: Path) -> None:
    by_tool = {}
    for f in flows:
        if f["sid"]:
            for row in traffic.rows(sessions.get(traffic.KIND, f["sid"])):
                by_tool.setdefault(f["tool"], []).append({"flow": f["id"], **row})
    for tool, rows in by_tool.items():
        with (run_dir / f"{'iperf' if tool == 'iperf3' else tool}_all.csv").open("w", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
            writer.writeheader()
            writer.writerows(rows)
