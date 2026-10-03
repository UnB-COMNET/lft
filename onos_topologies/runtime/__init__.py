# Brief: Procedures on a topology that is running. A topology is built once (`lft topology create`); these
# read what is up and change it while it runs, each from its own `lft` command, so nothing is kept in
# memory between them:
#   state     what is up (docker, ovs-vsctl, ip, tc), saved in /var/lib/lft/topology.json
#   links, hosts, switches
#             changes to it, made of what is already implemented: profissa_lft's nodes, the Switch and
#             the three tc bands of infrastructure/, the idle clients of traffic/
#   shaping   the bands applied to one end of a link, and what tc shows of a node
#   sessions  processes that outlive the command that starts them, used by traffic and capture
#   traffic, capture
#             iperf3, ping, DASH and tcpdump in the background
#   timeline  link changes, traffic, captures and HTTP calls on a schedule
#   results   the runs under results/ and their events
# Every procedure reports its progress through report(step, steps, title); print_step is the default.
# The nodes are the containers labelled lft=1 (profissa_lft's Node), told apart by lft.kind; links
# follow the veth names the topologies use, <node><peer> in node.


# Brief: A request the running topology cannot satisfy (unknown node, address in use...)
class TopologyError(Exception):
    pass


# Brief: Default progress output of a procedure, e.g. "[2/4] Linking cl3 to s2"
def print_step(step: int, steps: int, title: str) -> None:
    print(f"[{step}/{steps}] {title}", flush=True)


# Brief: Runs a command inside a node (profissa_lft's Node.run) and waits for it
# Params:
#   Node node: The node, e.g. Switch("s0")
#   String command: The command
#   bool check: Raise TopologyError when it fails
# Return:
#   String with what it printed
def run(node, command: str, check: bool = False) -> str:
    process = node.run(command)
    out = process.stdout.read()
    if process.wait() and check:
        raise TopologyError(f"{command!r} failed in {node.getNodeName()}")
    return out
