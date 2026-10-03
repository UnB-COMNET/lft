# Brief: Traffic between two hosts of the running topology, in the background (sessions.py):
#   iperf3  a one-off server (iperf3 -s -1) on the server host, and the client with one report a second
#   dash    on the client, one JSON line per video segment: pydash-play (lft-pydash-client clients), neubot's
#           dash-client (neubot/dash servers), or dash-play (lft-dash-video, lft-dash-live, lft-pydash-server);
#           the server side is the web server's log
#   ping    from the client to the server
# The output goes under results/ (<out>/<client>-<server>.txt, <client>.jsonl, <client>-<server>.ping.txt).
# A session stops by itself after its duration, or with stop(): SIGINT, so the tools print their summary.

import json
import re
import subprocess
import time
from pathlib import Path

from onos_topologies.measurements.ping import _PING_RE as PING_LINE
from onos_topologies.runtime import TopologyError, print_step, results, run, sessions, state
from profissa_lft.host import Host

KIND = "traffic"
TOOLS = ("iperf3", "dash", "ping")


# Brief: Starts a session
# Params:
#   String tool: iperf3, dash or ping
#   String client, server: Hosts
#   int port: iperf3 port (the next free one when taken)
#   bool reverse: iperf3 -R (the server sends)
#   String proto: tcp or udp (iperf3)
#   float rate: iperf3 target rate (Mb/s)
#   int duration: Seconds; 0 runs until stop()
#   float interval: ping interval (s)
#   String out: Output directory (default results/<iperf|dash>/manual/<time>)
#   report: Progress output (see print_step)
# Return:
#   dict meta {id, tool, client, server, port, file, server_file, pids, ...}
def start(tool: str, client: str, server: str, port: int = 5201, reverse: bool = False, proto: str = "tcp",
          rate: float = 35.0, duration: int = 0, interval: float = 1.0, out: str = None, report=print_step) -> dict:
    if tool not in TOOLS:
        raise TopologyError(f"tool must be one of {', '.join(TOOLS)}")
    current, live = state.load(), state.containers()
    c, s = _running_host(current, live, client), _running_host(current, live, server)
    sid = sessions.new_id(KIND, "t")
    out_dir = results.path(out or f"{'dash' if tool == 'dash' else 'iperf'}/manual/{time.strftime('%Y%m%d-%H%M%S')}")
    meta = {"id": sid, "tool": tool, "client": client, "server": server, "client_ip": c["ip"], "server_ip": s["ip"],
            "port": None, "reverse": reverse, "proto": proto, "rate": rate, "duration": duration, "out": str(out_dir),
            "server_file": None, "pidfile": f"/tmp/lft-{sid}.pid", "started": time.time(), "pids": []}
    steps = 2 if tool == "iperf3" else 1

    if tool == "iperf3":
        meta["port"] = _free_port(server, port)
        meta["server_file"] = str(out_dir / f"{server}-{meta['port']}.log")
        report(1, steps, f"iperf3 server in {server}:{meta['port']}")
        meta["pids"].append(sessions.spawn(_exec(server, meta["pidfile"], f"iperf3 -s -1 -p {meta['port']} --forceflush"),
                                           Path(meta["server_file"])))
        command = (f"sleep 1; exec iperf3 -c {s['ip']} -p {meta['port']} -t {duration or 86400} -i 1 -b {rate:g}M"
                   " --connect-timeout 10000 --forceflush")   # without a path to the server it gives up
        command += " -R" if reverse else ""
        command += " -u" if proto == "udp" else f" --fq-rate {rate:g}M"
        meta["file"] = str(out_dir / f"{client}-{server}.txt")
    elif tool == "dash":
        if c["image"].startswith("lft-pydash-client"):
            command = f"exec pydash-play {s['ip']} {duration}"
        elif s["image"].startswith("neubot/dash"):
            command = f"exec dash-client -y -hostname {s['ip']} -scheme http"
        else:
            command = f"exec dash-play {s['ip']} {duration}"
        meta["file"] = str(out_dir / f"{client}.jsonl")
    else:
        command = f"exec ping -i {interval:g}{f' -w {duration}' if duration else ''} {s['ip']}"
        meta["file"] = str(out_dir / f"{client}-{server}.ping.txt")

    report(steps, steps, f"{tool} client in {client}")
    meta["pids"].append(sessions.spawn(_exec(client, meta["pidfile"], command), Path(meta["file"])))
    return sessions.save(KIND, meta)


# Brief: Stops a session: SIGINT to the tools inside the containers (they print their summary), then to
# the docker exec processes that followed them
def stop(sid: str) -> dict:
    meta = sessions.get(KIND, sid)
    if meta["status"] != "running":
        return meta
    for node in (meta["client"], meta["server"]) if meta["server_file"] else (meta["client"],):
        subprocess.run(["docker", "exec", node, "sh", "-c", f"kill -INT $(cat {meta['pidfile']})"], capture_output=True)
    return sessions.save(KIND, {**sessions.stop(KIND, sid), "status": "stopped"})


# Brief: The sessions, each with its last reported rate (Mb/s) and line, and the client's error if it
# failed. A session whose client ended is over: the one-off iperf3 server still waiting for it goes too
def ls() -> list:
    rows = []
    for meta in sessions.ls(KIND):
        if meta["status"] == "running" and not sessions.alive(meta["pids"][-1]):
            meta = sessions.save(KIND, {**stop(meta["id"]), "status": "done"})
        rows.append({**meta, **last(meta)})
    return rows


# Brief: The rate a session reports now (iperf3 "... 34.6 Mbits/sec", dash "speed_kbps"), or the error
# its client stopped with (e.g. iperf3 could not reach the server)
def last(meta: dict) -> dict:
    lines = _lines(meta["file"])
    error = next((line for line in reversed(lines) if line.startswith(("iperf3: error", "connect:", "ping:", "Traceback"))), None)
    if error:
        return {"rate_mbps": None, "last": error, "error": error}
    for line in reversed(lines[-5:]):
        m = re.search(r"([\d.]+) ([KMG]?)bits/sec", line)
        if m and "sender" not in line and "receiver" not in line:
            return {"rate_mbps": round(float(m.group(1)) * UNITS[m.group(2)], 3), "last": line}
        if line.startswith("{"):
            try:
                return {"rate_mbps": round(json.loads(line).get("speed_kbps", 0) / 1000, 3), "last": line}
            except ValueError:
                pass
    return {"rate_mbps": None, "last": None}


# Brief: A session's output, client and server side, as ("client"|"server", line); with follow it
# keeps reading until the session ends
def logs(sid: str, follow: bool = False):
    meta = sessions.get(KIND, sid)
    sent = {"client": 0, "server": 0}
    while True:
        sides = {"client": _lines(meta["file"]), "server": _server_lines(meta)}
        for side, lines in sides.items():
            for line in lines[sent[side]:]:
                yield side, line
            sent[side] = max(sent[side], len(lines))
        if not follow or sessions.get(KIND, sid)["status"] != "running":
            return
        time.sleep(1)


UNITS = {"K": 1e-3, "M": 1, "G": 1e3, "": 1e-6}
IPERF_LINE = re.compile(r"\[\s*\d+\]\s+([\d.]+)-([\d.]+)\s+sec\s+\S+\s+\S*Bytes\s+([\d.]+) ([KMG]?)bits/sec")


# Brief: A session's output as rows: one per iperf3 interval, video segment or echo reply
# Return:
#   list of {session, tool, client, server, t_s, mbps, rtt_ms, resolution, bitrate_kbps, buffer_s, stalls}
def rows(meta: dict) -> list:
    base = {"session": meta["id"], "tool": meta["tool"], "client": meta["client"], "server": meta["server"]}
    out = []
    for line in _lines(meta["file"]):
        if meta["tool"] == "iperf3":
            m = IPERF_LINE.search(line)
            if m and "sender" not in line and "receiver" not in line:
                out.append({**base, "t_s": float(m.group(2)), "mbps": round(float(m.group(3)) * UNITS[m.group(4)], 3)})
        elif meta["tool"] == "dash" and line.startswith("{"):
            try:
                seg = json.loads(line)
            except ValueError:
                continue
            out.append({**base, "t_s": seg.get("iteration"), "mbps": round(seg.get("speed_kbps", 0) / 1000, 3),
                        "resolution": seg.get("resolution"), "bitrate_kbps": seg.get("rate"), "buffer_s": seg.get("buffer"),
                        "stalls": seg.get("stalls")})
        elif meta["tool"] == "ping":
            m = PING_LINE.match(line)   # (timestamp, bytes, address, icmp_seq, ttl, time)
            if m:
                out.append({**base, "t_s": int(m.group(4)), "rtt_ms": float(m.group(6))})
    return out


def _exec(node: str, pidfile: str, command: str) -> list:
    return ["docker", "exec", node, "sh", "-c", f"echo $$ >{pidfile}; {command}"]


def _running_host(current: dict, live: dict, name: str) -> dict:
    host = state.node(current, name)
    if not host or host["kind"] != "host" or live.get(name, {}).get("state") != "running":
        raise TopologyError(f"{name} is not a running host")
    return host


# Brief: port, or the next one no process in the node listens on (from /proc/net/tcp, which every image has)
def _free_port(node: str, port: int) -> int:
    out = run(Host(node), "cat /proc/net/tcp /proc/net/tcp6")
    busy = {int(cols[1].split(":")[1], 16) for cols in (line.split() for line in out.splitlines()) if len(cols) > 3 and cols[3] == "0A"}
    while port in busy:
        port += 1
    return port


def _lines(path: str) -> list:
    try:
        with open(path, errors="replace") as f:
            return f.read().splitlines()
    except FileNotFoundError:
        return []


# Brief: The server side of a session: iperf3's report, or the web server's log lines for this client
def _server_lines(meta: dict) -> list:
    if meta["server_file"]:
        return _lines(meta["server_file"])
    if meta["tool"] == "dash":
        out = subprocess.run(["docker", "logs", "--since", str(int(meta["started"])), meta["server"]], capture_output=True, text=True)
        return [line for line in (out.stdout + out.stderr).splitlines() if meta["client_ip"] in line]
    return []
