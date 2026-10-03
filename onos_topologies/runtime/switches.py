# Brief: Procedures on the switches of the running topology. A switch is an Open vSwitch container
# (infrastructure's Switch) on the docker bridge, where it reaches its controller. Turning a switch off
# disconnects it from the controller, takes its veth pairs down and pauses the container; turning it
# on undoes that. Its ports are never recreated, so they keep their OpenFlow numbers and the flows
# the controller installed stay valid.

import subprocess
from pathlib import Path

from onos_topologies.infrastructure.switch import Switch
from onos_topologies.runtime import TopologyError, hosts, print_step, run, shaping, state


# Brief: Creates a switch, connects it to the controller and links it to other switches
# Params:
#   String name: Container and bridge name
#   String desc: Bridge description (dp-desc), shown by the controller
#   list links: [(switch, {rate, delay, jitter, loss})]
#   String dpid: 16 hex digits (default: chosen by Open vSwitch)
#   String controller: e.g. "tcp:172.17.0.2:6653" (default: the one the topology's switches use)
#   report: Progress output (see print_step)
# Return:
#   None
def add(name: str, desc: str = "", links=(), dpid: str = "", controller: str = None, report=print_step) -> None:
    current, live = state.load(), state.containers()
    if name in live:
        raise TopologyError(f"{name} already exists")
    for other, _ in links:
        _get(other, on=True)
    controller = controller or current["controller"]
    steps = 2 + len(links)

    report(1, steps, f"Starting {name}")
    sw = Switch(name)
    sw.instantiate(networkMode="bridge", datapath_id=dpid or None, sw_desc=desc or None)
    report(2, steps, f"Connecting {name} to {controller}" if controller else f"{name} has no controller")
    if controller:
        _, ip, port = controller.split(":")
        sw.setController(ip, int(port))
    for step, (other, values) in enumerate(links, 3):
        report(step, steps, f"Linking {name} to {other}")
        sw.connect(Switch(other), f"{name}{other}", f"{other}{name}")
        shaping.apply(name, f"{name}{other}", values)
        shaping.apply(other, f"{other}{name}", values)


# Brief: Turns a switch off: no controller, its links and its hosts' access links down, container paused
def stop(name: str, report=print_step) -> None:
    _get(name, on=True)
    ends = _veth_ends(name)
    report(1, 3, f"Disconnecting {name} from its controller")
    run(Switch(name), f"ovs-vsctl del-controller {name}", check=True)
    report(2, 3, f"Taking its {len(ends) // 2} veth pairs down")
    for node, iface in ends:
        subprocess.run(["ip", "-n", node, "link", "set", iface, "down"], check=True)
    report(3, 3, f"Pausing {name}")
    subprocess.run(["docker", "pause", name], check=True)


# Brief: Turns a switch back on: container resumed, its veth pairs up, controller connected again
def start(name: str, report=print_step) -> None:
    _get(name, on=False)
    if state.containers()[name]["state"] != "paused":
        raise TopologyError(f"{name} was not turned off by lft switch stop; remove it and add it again")
    controller = state.load()["controller"]
    report(1, 3, f"Resuming {name}")
    subprocess.run(["docker", "unpause", name], check=True)
    ends = _veth_ends(name)
    report(2, 3, f"Bringing its {len(ends) // 2} veth pairs up")
    for node, iface in ends:
        subprocess.run(["ip", "-n", node, "link", "set", iface, "up"], check=True)
    report(3, 3, f"Connecting {name} to {controller}")
    if controller:
        _, ip, port = controller.split(":")
        Switch(name).setController(ip, int(port))


# Brief: Removes a switch: its hosts (with_hosts), its ports on the other switches and its container
def rm(name: str, with_hosts: bool = False, report=print_step) -> None:
    sw, current, live = _get(name), state.load(), state.containers()
    attached = [h["id"] for h in state.hosts(current) if h["sw"] == name]
    if attached and not with_hosts:
        raise TopologyError(f"{name} still has {', '.join(attached)} (use --with-hosts)")
    for host in attached:
        hosts.rm(host, report)
    neighbors = [l["b"] if l["a"] == name else l["a"] for l in current["links"] if name in (l["a"], l["b"])]
    report(1, 2, f"Removing its ports from {', '.join(neighbors) or 'no other switch'}")
    for other in neighbors:
        if live.get(other, {}).get("state") == "running":
            run(Switch(other), f"ovs-vsctl --if-exists del-port {other} {other}{name}")
    report(2, 2, f"Removing {name}")
    if sw["off"]:
        subprocess.run(["docker", "unpause", name], capture_output=True)
    Switch(name).delete()
    (Path("/var/run/netns") / name).unlink(missing_ok=True)


# Brief: Both ends of every veth pair of a switch, as (node, interface)
def _veth_ends(name: str) -> list:
    live = state.containers()
    ends = []
    for iface in state.ifaces(name):
        other = state.peer(name, iface, live)
        if other:
            ends += [(name, iface), (other, f"{other}{name}")]
    return ends


# Brief: The saved switch, on or off as required (None: either)
def _get(name: str, on: bool = None) -> dict:
    sw = state.node(state.load(), name)
    if not sw or sw["kind"] != "switch":
        raise TopologyError(f"unknown switch {name}")
    if on is True and sw["off"]:
        raise TopologyError(f"switch {name} is off (lft switch start {name})")
    if on is False and not sw["off"]:
        raise TopologyError(f"switch {name} is already on")
    return sw
