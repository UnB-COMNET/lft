"""Explicit entry points for the CLI and batch runner"""

from importlib import import_module

EXPERIMENTS = {
    "rnp": "onos_topologies.experiments.rnp.run",
    "diamond": "onos_topologies.experiments.diamond.run",
    "dash": "onos_topologies.experiments.dash.run",
    "dash-load": "onos_topologies.experiments.dash.load_test",
}

# What each runner does, for `lft experiment --json`: its windows (0: continuous until stopped), the
# impaired ones, the options it takes without prompting, and what it writes
INFO = {
    "diamond": {"config": "topologies/configs/diamond.py", "dir": "results/iperf", "windows": 6, "window_s": 60,
                "impaired": [2, 4, 6], "impairment": "s0-s1 degraded (3 Mbit/s, 130 ms) or taken down",
                "options": ["mode", "hindering", "run-name", "auto-start"],
                "outputs": ["iperf_flow_all.csv", "ping_flow_all.csv", "ovs_flows_all.csv", "ovs_ports_all.csv"]},
    "rnp": {"config": "topologies/configs/rnp.py", "dir": "results/iperf", "windows": 12, "window_s": 300,
            "impaired": [2, 4, 6, 8, 10, 12], "impairment": "HARD_DEGRADE on the chosen links (rate x0.1, delay x10)",
            "options": ["mode", "seed", "run-name", "auto-start"],
            "outputs": ["iperf_all.csv", "ping_all.csv", "ovs_flows_all.csv", "ovs_ports_all.csv"]},
    "dash": {"config": "topologies/configs/dash.py", "dir": "results/dash", "windows": 0, "window_s": 120,
             "impaired": [], "impairment": None, "options": ["duration", "yes"],
             "outputs": ["packet_flow_all.csv", "ovs_flows_all.csv", "ovs_ports_all.csv", "hw.csv"]},
    "dash-load": {"config": "topologies/configs/dash.py", "dir": "results/dash", "windows": 4, "window_s": 300,
                  "impaired": [], "impairment": None, "options": ["clients", "duration", "yes"],
                  "outputs": ["packet_flow_all.csv", "ovs_flows_all.csv", "ovs_ports_all.csv", "hw.csv"]},
}


# Brief: The runners with their modes and INFO, for `lft experiment --json`
def describe() -> list:
    out = []
    for name in EXPERIMENTS:
        modes = getattr(load(name), "MODES", {}) if name in ("rnp", "diamond") else {}
        out.append({"name": name, "module": EXPERIMENTS[name], "modes": [m["name"] for m in modes.values()], **INFO[name]})
    return out


def load(name):
    # Lazy imports keep listing experiments independent of runtime dependencies
    if name not in EXPERIMENTS:
        raise ValueError(f"Unknown experiment: {name}")
    module_path = EXPERIMENTS[name]
    return import_module(module_path)


def mode_key(experiment, mode):
    """Translate a mode name or numeric ID using the runner's mode table"""
    if experiment not in {"rnp", "diamond"}:
        raise ValueError(f"{experiment} does not have routing modes")
    runner = load(experiment)
    modes = runner.MODES
    if mode in modes:
        return mode
    for key, config in modes.items():
        if config["name"] == mode:
            return key
    choices = ", ".join(config["name"] for config in modes.values())
    raise ValueError(f"Unknown mode {mode!r} for {experiment}; choose {choices}")
