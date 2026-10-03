# Brief: Topology files, the .py configs of onos_topologies (constants.py style): POPS, the ADJACENCY,
# THROUGHPUT, RTT and LOSS matrices and CONFIG, plus two optional lists:
#   HOSTS = (("cl0", "PoP-SP", "client", "lft-dash-client", "192.168.0.2"), ...)   the hosts to create,
#           instead of the counts in POPS
#   DOWN_LINKS = ("s0-s1", ...)   links taken down once built
# load() reads one, build() starts it with ONOS, export() writes the running topology as one.

import time
import types
from pathlib import Path

from onos_topologies.topologies.topology import Topology
from onos_topologies.runtime import TopologyError, hosts, links, print_step, shaping, state

CONFIG_NAMES = ("CONFIG", "CONFIG_RNP", "DEFAULT_CONFIG", "DEBUG_CONFIG")


# Brief: Loads a topology file and its config (CONFIG, CONFIG_RNP, DEFAULT_CONFIG or DEBUG_CONFIG)
# Return:
#   (module, config)
def load(path) -> tuple:
    module = types.ModuleType("topology")   # executed in place, so no __pycache__ lands next to the file
    exec(compile(Path(path).read_text(), str(path), "exec"), module.__dict__)
    for name in CONFIG_NAMES:
        config = getattr(module, name, None)
        if isinstance(config, dict) and "pops" in config:
            return module, config
    raise TopologyError(f"no config in {path}: expected one of {', '.join(CONFIG_NAMES)}")


# Brief: Builds a topology with ONOS: switches and links (LFT's Topology), the three bands on every link
# with the loss of LOSS_MATRIX, the file's HOSTS and DOWN_LINKS; then saves the topology's state
# Params:
#   dict config: The topology config
#   String name: Topology name, kept in the state
#   module: The loaded file, for HOSTS and DOWN_LINKS (None for a preset)
#   bool disable_fwd: Deactivate ONOS reactive forwarding
#   report: Progress output of the operations (see print_step)
# Return:
#   Topology
def build(config: dict, name: str, module=None, disable_fwd: bool = False, report=print_step) -> Topology:
    listed = getattr(module, "HOSTS", ())
    if listed:  # the file lists its hosts: LFT builds only the switches and their links
        config = {**config, "pops": tuple((pop[0], 0, 0) for pop in config["pops"])}
    topo = Topology(config=config)
    report(1, 1, "Starting ONOS, the switches and their links")   # the slow part: ONOS takes about 40 s
    topo.run(run_discovery=True, disable_fwd=disable_fwd)
    defaults = {"rate": shaping.mbit(config.get("throughput", "35mbit")), "delay": shaping.ms(config.get("delay", "10ms")),
                "jitter": shaping.ms(config.get("jitter", "1ms")), "loss": 0.0}
    state.save(state.empty())   # a new topology: nothing of the previous one's state carries over
    built = state.sync(name, defaults)

    loss = {}
    for i, row in enumerate(config.get("loss_matrix") or ()):
        for j, value in enumerate(row):
            if value:
                loss[state.link_id(f"s{i}", f"s{j}")] = float(str(value).rstrip("%"))
    for link in built["links"]:
        links.shape(link["a"], link["b"], loss=loss.get(link["id"], 0), report=report)
    for host, pop, role, image, ip in listed:
        hosts.add(host, topo.pop_to_sname.get(pop, pop), ip, image, role == "server", report)
        state.sync()
    for lid in getattr(module, "DOWN_LINKS", ()):
        links.down(*lid.split("-"), report=report)
    state.sync()
    return topo


# Brief: The running topology as a topology file; `lft topology create --path <file>` builds it again
def export(current: dict) -> str:
    sws, hs, d = state.switches(current), state.hosts(current), current["defaults"]
    index = {s["id"]: i for i, s in enumerate(sws)}
    n = len(sws)
    adjacency, throughput, rtt, loss = ([[0] * n for _ in range(n)] for _ in range(4))
    down = []
    for link in current["links"]:
        i, j = index.get(link["a"]), index.get(link["b"])
        if i is None or j is None:
            continue
        adjacency[i][j] = adjacency[j][i] = 1
        values = link["base"] if link["now"]["down"] else link["now"]
        if link["now"]["down"]:
            down.append(link["id"])
        if abs(values["rate"] - d["rate"]) > 1e-9:
            throughput[i][j] = throughput[j][i] = shaping.rate_str(values["rate"])
        if abs(values["delay"] - d["delay"]) > 1e-9:
            rtt[i][j] = rtt[j][i] = f"{round(values['delay'] * 2, 2):g}ms"
        if values["loss"] > 0:
            loss[i][j] = loss[j][i] = f"{round(values['loss'], 2):g}%"

    pop_of = {s["id"]: f"PoP-{s['desc'] or s['id'].upper()}" for s in sws}
    role = {h["id"]: h["role"] or ("server" if h["id"].startswith("ds") else "client") for h in hs}
    pops = [(pop_of[s["id"]], sum(h["sw"] == s["id"] and role[h["id"]] == "client" for h in hs),
             sum(h["sw"] == s["id"] and role[h["id"]] == "server" for h in hs)) for s in sws]

    lines = [f"# Topology exported by lft, {time.strftime('%d/%m/%Y %H:%M')}. Build it with:",
             f"#   sudo lft topology create --path {current['name'] or 'lft'}_topology.py", "",
             '# ("PoP-Name", num_clients, num_servers)', "POPS = ("]
    lines += [f'    ("{p}", {c}, {s}),' for p, c, s in pops] + [")", ""]
    lines += _matrix("ADJACENCY_MATRIX", adjacency, sws)
    matrices = [("THROUGHPUT_MATRIX", "throughput_matrix", throughput, 'Per-link throughput; 0 falls back to CONFIG["throughput"]'),
                ("RTT_MATRIX", "rtt_matrix", rtt, 'Per-link RTT, applied as half one-way delay; 0 falls back to CONFIG["delay"]'),
                ("LOSS_MATRIX", "loss_matrix", loss, "Per-link packet loss")]
    used = [(const, key) for const, key, m, comment in matrices if any(map(any, m))]
    for const, key, m, comment in matrices:
        if (const, key) in used:
            lines += [f"# {comment}"] + _matrix(const, m, sws)
    lines += ["CONFIG = {", '    "adjacency_matrix": ADJACENCY_MATRIX,']
    lines += [f'    "{key}": {const},' for const, key in used]
    lines += ['    "pops": POPS,', '    "apply_link_properties": True,', '    "randomize_link_properties": False,',
              f'    "throughput": "{shaping.rate_str(d["rate"])}",', f'    "delay": "{round(d["delay"], 2):g}ms",',
              f'    "jitter": "{round(d["jitter"], 2):g}ms",', "}", "", "# (name, PoP, role, image, ip)", "HOSTS = ("]
    lines += [f'    ("{h["id"]}", "{pop_of.get(h["sw"], h["sw"])}", "{role[h["id"]]}", "{h["image"]}", "{h["ip"]}"),' for h in hs]
    lines += [")"]
    if down:
        lines += ["DOWN_LINKS = (" + ", ".join(f'"{x}"' for x in down) + ",)"]
    return "\n".join(lines) + "\n"


def _matrix(name: str, m: list, sws: list) -> list:
    width = max([1] + [len(_cell(v)) for row in m for v in row])
    rows = [f"    ( {', '.join(_cell(v).ljust(width) for v in row)} ),  # {sws[i]['id']}" for i, row in enumerate(m)]
    return [f"{name} = (", *rows, ")", ""]


def _cell(value) -> str:
    return f'"{value}"' if isinstance(value, str) else str(value)
