# Brief: Procedures on the hosts of the running topology, made of what the topologies are built with: a
# host is a container linked to a switch by a veth pair (Node.connect adds the switch's port) with an
# address on its end. A server is a Host, running its image's own command; a client is an IperfClient,
# which idles for the commands it is given. The role is kept in the container's lft.role label.

import ipaddress
import subprocess
from pathlib import Path

from onos_topologies.infrastructure.switch import Switch
from onos_topologies.runtime import TopologyError, print_step, run, state
from onos_topologies.traffic.iperf import IperfClient
from profissa_lft.host import Host

PREFIX = 24


# Brief: Creates a host linked to a switch
# Params:
#   String name: Container name
#   String switch: The switch it hangs from
#   String ip: Its address (/24)
#   String image: Docker image
#   bool server: Run the image's own command (a server) instead of idling (a client)
#   report: Progress output (see print_step)
# Return:
#   None
def add(name: str, switch: str, ip: str, image: str, server: bool = False, report=print_step) -> None:
    current, live = state.load(), state.containers()
    if name in live:
        raise TopologyError(f"{name} already exists")
    sw = state.node(current, switch)
    if not sw or sw["kind"] != "switch" or sw["off"]:
        raise TopologyError(f"{switch} is not a running switch")
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise TopologyError(f"{ip!r} is not an address")
    if any(h["ip"] == ip for h in state.hosts(current)):
        raise TopologyError(f"{ip} is already in use")

    report(1, 4, f"Starting {name} from {image}")
    host = Host(name) if server else IperfClient(name)
    host.role = "server" if server else "client"
    host.instantiate(dockerImage=image)
    report(2, 4, f"Linking {name} to {switch}")
    host.connect(Switch(switch), f"{name}{switch}", f"{switch}{name}")
    report(3, 4, f"Address {ip}/{PREFIX} on {name}{switch}")
    host.setIp(ip, PREFIX, f"{name}{switch}")
    # the controller learns a host from its first packet: one ARP request for an unused address
    report(4, 4, f"Announcing {name} to the controller")
    network = ipaddress.ip_interface(f"{ip}/{PREFIX}").network
    probe = str(network[-2] if str(network[-2]) != ip else network[-3])
    run(host, f"ping -c 1 -W 1 {probe}")


# Brief: Removes a host: its port on the switch, its container and its netns link
def rm(name: str, report=print_step) -> None:
    host, live = _get(name), state.containers()
    report(1, 2, f"Removing port {host['sw']}{name} from {host['sw']}")
    if host["sw"] in live and live[host["sw"]]["state"] == "running":
        run(Switch(host["sw"]), f"ovs-vsctl --if-exists del-port {host['sw']} {host['sw']}{name}")
    report(2, 2, f"Removing {name}")
    if host["paused"]:
        subprocess.run(["docker", "unpause", name], capture_output=True)
    Host(name).delete()
    (Path("/var/run/netns") / name).unlink(missing_ok=True)


# Brief: Changes a host by creating it again with the new values (None keeps the current one). On the
# same switch it keeps its OpenFlow port number, so the flows installed for it stay valid
def change(name: str, new_name: str = None, switch: str = None, ip: str = None, image: str = None, report=print_step) -> None:
    host = _get(name)
    switch, new_name = switch or host["sw"], new_name or name
    port = None
    if switch == host["sw"]:
        out = run(Switch(switch), f"ovs-vsctl get interface {switch}{name} ofport").strip()
        port = int(out) if out.isdigit() else None
    rm(name, report)
    state.sync()   # its name and address are free again
    add(new_name, switch, ip or host["ip"], image or host["image"], host["role"] == "server", report)
    if port:
        run(Switch(switch), f"ovs-vsctl set interface {switch}{new_name} ofport_request={port}", check=True)


# Brief: Freezes a host (docker pause) or resumes it: its traffic stops, its link stays
def pause(name: str, paused: bool, report=print_step) -> None:
    _get(name)
    word = "pause" if paused else "unpause"
    report(1, 1, f"{word.capitalize()} {name}")
    subprocess.run(["docker", word, name], check=True)


def _get(name: str) -> dict:
    host = state.node(state.load(), name)
    if not host or host["kind"] != "host":
        raise TopologyError(f"unknown host {name}")
    return host
