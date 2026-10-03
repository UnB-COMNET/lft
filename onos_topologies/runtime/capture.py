# Brief: Packet captures: tcpdump on one veth end of the running topology, in the background
# (sessions.py), writing a pcap under results/

import shlex
import time

from onos_topologies.runtime import TopologyError, print_step, results, sessions, state

KIND = "captures"


# Brief: Starts a capture
# Params:
#   String iface: A veth end, e.g. s0s1 (captured in the namespace of the node that holds it)
#   int duration: Seconds; 0 runs until stop()
#   String out: pcap path (default results/pcap/<iface>-<time>.pcap)
#   String bpf: tcpdump filter, e.g. "host 192.168.0.2"
#   report: Progress output (see print_step)
# Return:
#   dict meta {id, iface, node, out, duration, filter, pids}
def start(iface: str, duration: int = 30, out: str = None, bpf: str = "", report=print_step) -> dict:
    live = state.containers()
    node = next((n for n in live if iface.startswith(n) and live[n]["state"] == "running" and iface in state.ifaces(n)), None)
    if not node:
        raise TopologyError(f"{iface} is not an interface of a running node")
    sid = sessions.new_id(KIND, "c")
    pcap = results.path(out or f"pcap/{iface}-{time.strftime('%Y%m%d-%H%M%S')}.pcap")
    pcap.parent.mkdir(parents=True, exist_ok=True)
    argv = ["ip", "netns", "exec", node, *(["timeout", "-s", "INT", str(duration)] if duration else []),
            "tcpdump", "-i", iface, "-nn", "-U", "-s", "0", "-Z", "root", "-w", str(pcap), *shlex.split(bpf)]
    report(1, 1, f"Capturing {iface} in {node}")
    pid = sessions.spawn(argv, sessions.home(KIND) / sid / "tcpdump.log")
    return sessions.save(KIND, {"id": sid, "iface": iface, "node": node, "out": str(pcap), "duration": duration,
                                "filter": bpf, "started": time.time(), "pids": [pid]})


def stop(sid: str) -> dict:
    return sessions.stop(KIND, sid)


def ls() -> list:
    return sessions.ls(KIND)
