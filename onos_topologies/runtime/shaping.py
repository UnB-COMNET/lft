# Brief: The runtime side of link shaping. The three netem bands of a link (probes and LLDP, ICMP, data)
# are built by infrastructure/traffic_control; this applies them to one end of a link, reads what tc
# shows of a node's interfaces, and converts between tc's strings and the state's numbers: rate in
# Mb/s, delay and jitter in ms, loss in %.

import json
import re
import subprocess

from onos_topologies.infrastructure import traffic_control

DATA_BAND = traffic_control.NETEM_BANDS[-1][1]   # "30:", the band with the rate limit


# Brief: Shapes one end of a link: the three bands when the interface has none, else a change of
# their values (the filters stay)
# Params:
#   String node: The switch that holds iface
#   String iface: e.g. "s0s1"
#   dict values: {rate, delay, jitter, loss}
# Return:
#   None
def apply(node: str, iface: str, values: dict) -> None:
    rate, delay, jitter = rate_str(values["rate"]), f"{values['delay']:g}ms", f"{values['jitter']:g}ms"
    if any(q["dev"] == iface and q["kind"] == "prio" for q in qdiscs(node)):
        traffic_control.update_prio_netem(node, iface, delay, jitter, rate, values["loss"])
    else:
        traffic_control.create_prio_netem(node, {iface: (rate, delay, jitter)}, (), values["loss"])


# Brief: The shaping of each interface of a node, read from tc: the data band of the three bands, or
# a plain root netem (profissa_lft's setInterfaceProperties)
# Return:
#   {iface: {rate, delay, jitter, loss}}; rate is None when netem has no rate
def read(node: str) -> dict:
    found = {}
    for q in qdiscs(node):
        if q["kind"] != "netem" or not (q.get("root") or q.get("handle") == DATA_BAND):
            continue
        options = q.get("options", {})
        delay = options.get("delay", {})
        rate = options.get("rate", {}).get("rate")
        found[q["dev"]] = {"rate": round(rate * 8 / 1e6, 6) if rate else None,
                           "delay": round(delay.get("delay", 0) * 1000, 3),
                           "jitter": round(delay.get("jitter", 0) * 1000, 3),
                           "loss": round(options.get("loss-random", {}).get("loss", 0) * 100, 3)}
    return found


# Brief: The qdiscs of a node, as `tc -j qdisc show` reports them in its namespace (a paused node's too)
def qdiscs(node: str) -> list:
    out = subprocess.run(["ip", "netns", "exec", node, "tc", "-j", "qdisc", "show"], capture_output=True, text=True).stdout
    return json.loads(out or "[]")


# Brief: "35mbit" -> 35.0 (Mb/s)
def mbit(rate) -> float:
    return round(traffic_control.rate_to_kbit(rate) / 1000, 6)


# Brief: "10ms" -> 10.0, "500us" -> 0.5, "1s" -> 1000.0 (ms)
def ms(value) -> float:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(us|ms|s)\s*", str(value))
    if not match:
        raise ValueError(f"Invalid time or unsupported unit: {value!r}")
    return round(float(match.group(1)) * {"us": 0.001, "ms": 1.0, "s": 1000.0}[match.group(2)], 6)


# Brief: 35 -> "35mbit", 0.2 -> "200kbit", 1000 -> "1gbit"
def rate_str(mbps: float) -> str:
    if mbps >= 1000 and mbps % 1000 == 0:
        return f"{mbps / 1000:g}gbit"
    if mbps < 1:
        return f"{round(mbps * 1000)}kbit"
    return f"{round(mbps, 2):g}mbit"
