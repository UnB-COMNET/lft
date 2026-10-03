"""Explicit entry points for the CLI and batch runner"""

from importlib import import_module

EXPERIMENTS = {
    "rnp": "onos_topologies.experiments.rnp.run",
    "diamond": "onos_topologies.experiments.diamond.run",
    "dash": "onos_topologies.experiments.dash.run",
    "dash-load": "onos_topologies.experiments.dash.load_test",
}


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
