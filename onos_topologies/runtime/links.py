# Brief: Procedures on the links between switches of the running topology: shape them, take them down
# and bring them back. Both ends change, so the two directions stay alike.

import subprocess

from onos_topologies.runtime import TopologyError, print_step, shaping, state


# Brief: The saved link between a and b, with both switches on
def _get(a: str, b: str) -> dict:
    current = state.load()
    link = state.link(current, a, b)
    if not link:
        raise TopologyError(f"no link between {a} and {b}")
    for end in (a, b):
        if state.node(current, end)["off"]:
            raise TopologyError(f"switch {end} is off (lft switch start {end})")
    return link


# Brief: Shapes both ends of a link; values left out keep the current ones
# Params:
#   String a, b: The switches
#   float rate (Mb/s), delay, jitter (ms), loss (%)
#   report: Progress output (see print_step)
# Return:
#   None
def shape(a: str, b: str, rate=None, delay=None, jitter=None, loss=None, report=print_step) -> None:
    link = _get(a, b)
    values = {k: link["now"][k] for k in state.SHAPE}
    values.update({k: v for k, v in (("rate", rate), ("delay", delay), ("jitter", jitter), ("loss", loss)) if v is not None})
    report(1, 2, f"Shaping {a}{b} in {a}")
    shaping.apply(a, f"{a}{b}", values)
    report(2, 2, f"Shaping {b}{a} in {b}")
    shaping.apply(b, f"{b}{a}", values)


# Brief: Takes both ends of a link down (the controller sees the ports go)
def down(a: str, b: str, report=print_step) -> None:
    _get(a, b)
    _set(a, b, "down", report)


# Brief: Brings both ends of a link back up
def up(a: str, b: str, report=print_step) -> None:
    _get(a, b)
    _set(a, b, "up", report)


# Brief: Back to the shaping the link was built with, and up
def reset(a: str, b: str, report=print_step) -> None:
    shape(a, b, **_get(a, b)["base"], report=report)
    up(a, b, report)


def _set(a: str, b: str, word: str, report) -> None:
    report(1, 2, f"Setting {a}{b} {word} in {a}")
    subprocess.run(["ip", "-n", a, "link", "set", f"{a}{b}", word], check=True)
    report(2, 2, f"Setting {b}{a} {word} in {b}")
    subprocess.run(["ip", "-n", b, "link", "set", f"{b}{a}", word], check=True)
