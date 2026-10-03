# Brief: What the running topology is, read from the live system (docker, ovs-vsctl, ip, tc) and saved in
# /var/lib/lft/topology.json (LFT_STATE), so every `lft` command sees the same picture:
#   name        topology name
#   controller  the switches' controller, e.g. "tcp:172.17.0.2:6653"
#   defaults    shaping for new links {rate, delay, jitter, loss}
#   nodes       switches {id, kind: "switch", dpid, desc, off} and hosts {id, kind: "host", role, sw, ip,
#               image, access, paused}; role is "server" or "client" for hosts made by `lft host add`
#   links       between two switches {id: "s0-s1", a, b, base, now}: base is the shaping the link was
#               first seen with, now what tc shows, plus down
# Rates are in Mb/s, delay and jitter in ms, loss in %. The nodes are the containers labelled lft=1,
# told apart by their lft.kind label; links follow profissa_lft's veth names (<node><peer> in node).

import json
import os
import re
import subprocess
import time
from pathlib import Path

from onos_topologies.infrastructure.switch import Switch
from onos_topologies.runtime import run, shaping

STATE = Path(os.environ.get("LFT_STATE", "/var/lib/lft/topology.json"))
STATS = STATE.with_name("stats.json")   # the previous counters, for the rates of link_stats()
DEFAULTS = {"rate": 35.0, "delay": 10.0, "jitter": 1.0, "loss": 0.0}
SHAPE = ("rate", "delay", "jitter", "loss")


def empty() -> dict:
    return {"name": None, "controller": None, "defaults": dict(DEFAULTS), "nodes": [], "links": [], "updated": None}


# Brief: The last saved state (empty when nothing was saved yet)
def load() -> dict:
    return {**empty(), **json.loads(STATE.read_text())} if STATE.exists() else empty()


# Brief: Writes the state atomically, so a reader never sees half a file
def save(state: dict) -> dict:
    state["updated"] = time.time()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(STATE)
    return state


def switches(state: dict) -> list:
    return [n for n in state["nodes"] if n["kind"] == "switch"]


def hosts(state: dict) -> list:
    return [n for n in state["nodes"] if n["kind"] == "host"]


def node(state: dict, name: str):
    return next((n for n in state["nodes"] if n["id"] == name), None)


def link(state: dict, a: str, b: str):
    return next((l for l in state["links"] if {l["a"], l["b"]} == {a, b}), None)


# Brief: Sort key that puts s2 before s10
def natural(name: str) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


# Brief: Link id with its ends in natural order: "s2-s10"
def link_id(a: str, b: str) -> str:
    return "-".join(sorted((a, b), key=natural))


# ------------------------------------------------------------------ the live system

def _out(argv: list) -> str:
    return subprocess.run(argv, capture_output=True, text=True).stdout


# Brief: The topology's containers (label lft=1), running or not
# Return:
#   {name: {state: running|paused|exited..., image, kind: switch|host|controller, role}}
def containers() -> dict:
    fmt = '{{.Names}}\t{{.State}}\t{{.Image}}\t{{.Label "lft.kind"}}\t{{.Label "lft.role"}}'
    found = {}
    for line in _out(["docker", "ps", "-a", "--filter", "label=lft=1", "--format", fmt]).splitlines():
        name, st, image, kind, role = line.split("\t")
        found[name] = {"state": st, "image": image.removesuffix(":latest"), "kind": kind or None, "role": role or None}
    return found


# Brief: The interfaces of a node by name, as `ip -s -j addr` reports them (flags, MAC, addresses, counters)
def ifaces(node: str) -> dict:
    return {i["ifname"]: i for i in json.loads(_out(["ip", "-n", node, "-s", "-j", "addr", "show"]) or "[]")}


# Brief: The node at the other end of a veth, from its name: s0s1 in s0 -> s1 (None for lo, eth0...)
def peer(node: str, iface: str, names) -> str:
    other = iface[len(node):]
    return other if iface.startswith(node) and other in names else None


def is_down(info: dict) -> bool:
    return "UP" not in info.get("flags", []) or info.get("operstate") in ("DOWN", "LOWERLAYERDOWN")


def ipv4(info: dict):
    return next((a["local"] for a in info.get("addr_info", []) if a["family"] == "inet"), None)


# Brief: Datapath id ("of:0000000000000001") and description (dp-desc) of a running switch's bridge
def _bridge(name: str) -> tuple:
    dpid = run(Switch(name), f"ovs-vsctl get bridge {name} datapath_id").strip().strip('"')
    desc = run(Switch(name), f"ovs-vsctl --if-exists get bridge {name} other-config:dp-desc").strip().strip('"')
    return (f"of:{dpid}" if dpid else None), (desc or None)


def _controller(name: str):
    return run(Switch(name), f"ovs-vsctl get-controller {name}").split("\n")[0].strip() or None


# Brief: A controller container's OpenFlow address, on the standard port: "tcp:172.17.0.2:6653"
def _controller_address(name: str):
    ip = _out(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", name]).strip()
    return f"tcp:{ip}:6653" if ip else None


# ------------------------------------------------------------------ building the state

# Brief: Rebuilds the state from the live system and saves it. What the live system cannot tell is
# kept from the saved state: each link's base shaping, and the dpid of a switch that is off.
# Params:
#   String name: Topology name (default: the saved one)
#   dict defaults: Shaping for new links (default: the saved one)
# Return:
#   dict state
def sync(name: str = None, defaults: dict = None) -> dict:
    old, live = load(), containers()
    old_nodes = {n["id"]: n for n in old["nodes"]}
    ends = {}   # (a, b) -> what the switches show of that link: its shaping and whether it is down
    names = sorted(live, key=natural)
    nodes, controller = [], None
    for c_name in (n for n in names if live[n]["kind"] == "switch"):
        nodes.append(_switch(c_name, live[c_name], old_nodes.get(c_name, {}), live, ends))
        if live[c_name]["state"] == "running":
            controller = _controller(c_name) or controller
    for c_name in (n for n in names if live[n]["kind"] == "controller" and live[n]["state"] == "running"):
        controller = controller or _controller_address(c_name)   # no switch yet: the controller's own
    for c_name in (n for n in names if live[n]["kind"] == "host"):
        nodes.append(_host(c_name, live[c_name], old_nodes.get(c_name, {}), live))
    defaults = defaults or old["defaults"]
    return save({"name": name or old["name"], "controller": controller, "defaults": defaults,
                 "nodes": nodes, "links": _links(old["links"], ends, live, defaults)})


# Brief: A switch, adding what it shows of its links to ends. A paused switch (lft switch stop)
# keeps its namespace, so its links are still read
def _switch(name: str, c: dict, old: dict, live: dict, ends: dict) -> dict:
    sw = {"id": name, "kind": "switch", "dpid": old.get("dpid"), "desc": old.get("desc"), "off": c["state"] != "running"}
    if c["state"] == "running":
        sw["dpid"], sw["desc"] = _bridge(name)
    if c["state"] in ("running", "paused"):
        tc = shaping.read(name)
        for iface, info in ifaces(name).items():
            other = peer(name, iface, live)
            if not other or live[other]["kind"] != "switch":
                continue
            end = ends.setdefault(tuple(sorted((name, other), key=natural)), {"down": False})
            end["down"] = end["down"] or is_down(info)
            for key, value in (tc.get(iface) or {}).items():   # the two ends may differ: keep the worse
                if value is not None:
                    end[key] = min(end.get(key, value), value) if key == "rate" else max(end.get(key, value), value)
    return sw


def _host(name: str, c: dict, old: dict, live: dict) -> dict:
    host = {"id": name, "kind": "host", "role": c["role"], "sw": old.get("sw"), "ip": old.get("ip"), "image": c["image"],
            "access": old.get("access"), "paused": c["state"] == "paused"}
    if c["state"] in ("running", "paused"):
        tc = shaping.read(name)
        for iface, info in ifaces(name).items():
            other = peer(name, iface, live)
            if other and live[other]["kind"] == "switch":
                host.update(sw=other, ip=ipv4(info) or host["ip"], access=tc.get(iface))
    return host


# Brief: The links between switches: the ones the switches show (a paused switch shows its own), and
# saved ones with an end whose container stopped, which took its veth pairs along. A new link's base is
# what tc shows the first time.
def _links(old_links: list, ends: dict, live: dict, defaults: dict) -> list:
    saved = {(l["a"], l["b"]): l for l in old_links}
    stopped = {name for name, c in live.items() if c["state"] not in ("running", "paused")}
    pairs = set(ends) | {pair for pair in saved if set(pair) <= set(live) and set(pair) & stopped}
    links = []
    for a, b in sorted(pairs, key=lambda pair: [natural(x) for x in pair]):
        seen, old = ends.get((a, b)), saved.get((a, b))
        base = old["base"] if old else {k: (seen or {}).get(k, defaults[k]) for k in SHAPE}
        now = {**base, "down": True} if seen is None else {**base, **seen}
        links.append({"id": link_id(a, b), "a": a, "b": b, "base": base, "now": now})
    return links


# ------------------------------------------------------------------ interfaces and counters

def _counters(info: dict) -> dict:
    st = info.get("stats64", {})
    return {f"{d}_{k}": st.get(d, {}).get(k, 0) for d in ("rx", "tx") for k in ("bytes", "packets", "dropped")}


# Brief: The veth ends of the running topology: node and peer, whether it joins two switches (link) or a host
# (access), address, MAC, state, root qdisc, shaping and counters
# Params:
#   String only: One node, or None for all
# Return:
#   list of dicts
def iface_ls(only: str = None) -> list:
    live = containers()
    rows = []
    for name in [only] if only else sorted(live, key=natural):
        if live.get(name, {}).get("state") not in ("running", "paused"):
            continue
        roots = {q["dev"]: q["kind"] for q in shaping.qdiscs(name) if q.get("root")}
        tc = shaping.read(name)
        for iface, info in ifaces(name).items():
            other = peer(name, iface, live)
            if not other:
                continue
            both = live[name]["kind"] == live[other]["kind"] == "switch"
            addr = next((f"{a['local']}/{a['prefixlen']}" for a in info.get("addr_info", []) if a["family"] == "inet"), None)
            rows.append({"name": iface, "node": name, "peer": f"{other}{name}", "peerNode": other,
                         "link": link_id(name, other) if both else None, "access": not both, "ip": addr,
                         "mac": info.get("address"), "up": not is_down(info), "mtu": info.get("mtu"),
                         "qdisc": roots.get(iface), "shaping": tc.get(iface), **_counters(info)})
    return rows


# Brief: Counters of every veth end, with the rate (Mb/s) each end sent since the previous call; the
# last sample is kept in stats.json next to the state
# Return:
#   dict {ts, links: {id: {ab, ba, down, a, b}}, hosts: {id: {tx, rx, counters...}}}
def link_stats() -> dict:
    now, state, live = time.time(), load(), containers()
    counters = {}
    for name in live:
        if live[name]["state"] != "running":
            continue
        drops = {q["dev"]: q.get("drops", 0) for q in shaping.qdiscs(name) if q.get("root")}
        for iface, info in ifaces(name).items():
            if peer(name, iface, live):
                counters[iface] = {**_counters(info), "qdisc_drops": drops.get(iface, 0)}
    prev = json.loads(STATS.read_text()) if STATS.exists() else {"ts": 0, "counters": {}}
    STATS.parent.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps({"ts": now, "counters": counters}))

    def rate(iface):
        before, after, dt = prev["counters"].get(iface), counters.get(iface), now - prev["ts"]
        if not before or not after or not 0 < dt < 60 or after["tx_bytes"] < before["tx_bytes"]:
            return None
        return round((after["tx_bytes"] - before["tx_bytes"]) * 8 / dt / 1e6, 3)

    links = {l["id"]: {"ab": rate(l["a"] + l["b"]), "ba": rate(l["b"] + l["a"]), "down": l["now"]["down"],
                       "a": counters.get(l["a"] + l["b"]), "b": counters.get(l["b"] + l["a"])} for l in state["links"]}
    access = {h["id"]: {"tx": rate(h["id"] + h["sw"]), "rx": rate(h["sw"] + h["id"]), **(counters.get(h["id"] + h["sw"]) or {})}
              for h in hosts(state) if h["sw"]}
    return {"ts": now, "links": links, "hosts": access}


# Brief: The topology's containers and the local images
def status() -> dict:
    live = containers()
    images = sorted(set(_out(["docker", "images", "--format", "{{.Repository}}"]).split()) - {"<none>"})
    return {"containers": [{"name": n, **live[n]} for n in sorted(live, key=natural)], "images": images}


# Brief: Removes the topology's containers (label lft=1) and their netns links; nothing else on the host
# Return:
#   list of the removed names
def clean() -> list:
    names = list(containers())
    if names:
        subprocess.run(["docker", "rm", "-f", *names], capture_output=True)
    for name in names:
        (Path("/var/run/netns") / name).unlink(missing_ok=True)
    return names
