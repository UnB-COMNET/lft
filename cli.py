#!/usr/bin/env python3
import warnings
warnings.filterwarnings("ignore")

import os
import sys
import shlex
import subprocess
from pathlib import Path

import click
from rich.align import Align
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()

NAME = "lft"
SUBTITLE = "Lightweight network topology emulation tool"

# lft palette: blue + purple
BLUE = "#2e7bff"
PURPLE = "#7c4dff"
BLUE_RGB = (46, 123, 255)
PURPLE_RGB = (124, 77, 255)

BANNER = r"""
                    ___
                   /\__\
                  /:/ _/_         ___
                 /:/ /\__\       /\__\
  ___     ___   /:/ /:/  /      /:/  /
 /\  \   /\__\ /:/_/:/  /      /:/__/
 \:\  \ /:/  / \:\/:/  /      /::\  \
  \:\  /:/  /   \::/__/      /:/\:\  \
   \:\/:/  /     \:\  \      \/__\:\  \
    \::/  /       \:\__\          \:\__\
     \/__/         \/__/           \/__/
"""


def _blend(start, end, p):
    """Interpolate two RGB colors (p from 0.0 to 1.0) into a hex string"""
    r, g, b = (round(start[i] + (end[i] - start[i]) * p) for i in range(3))
    return f"#{r:02x}{g:02x}{b:02x}"


def _gradient_v(lines, start, end):
    """Vertical gradient: each line gets a color between `start` and `end`"""
    text = Text(no_wrap=True)
    n = max(len(lines) - 1, 1)
    for i, line in enumerate(lines):
        text.append(line + "\n", style=f"bold {_blend(start, end, i / n)}")
    return text


def _gradient_h(s, start, end):
    """Horizontal gradient: each character gets a color between `start` and `end`"""
    text = Text(no_wrap=True)
    n = max(len(s) - 1, 1)
    for i, ch in enumerate(s):
        text.append(ch, style=f"bold {_blend(start, end, i / n)}")
    return text


class LftGroup(click.Group):
    """Click group that keeps the same header (banner + commands) across all menus"""

    def list_commands(self, ctx):
        # Preserve definition order instead of click's default alphabetical order
        return list(self.commands)

    def _banner(self):
        # Art lines without trailing whitespace (so centering lines up correctly).
        lines = [l.rstrip() for l in BANNER.splitlines() if l.strip()]
        width = max((len(l) for l in lines), default=0)

        # If the banner doesn't fit the current window, fall back to a compact title
        if console.size.width < width:
            return _gradient_h(NAME, BLUE_RGB, PURPLE_RGB), len(NAME)

        return _gradient_v(lines, BLUE_RGB, PURPLE_RGB), width

    def format_help(self, ctx, formatter):
        # At the root, use the global subtitle; in subgroups, the group's own docstring
        subtitle = SUBTITLE if ctx.parent is None else (self.help or "").strip()

        banner, width = self._banner()
        rule = "─" * min(width, console.size.width)

        console.print(Align.center(banner))
        console.print(Align.center(_gradient_h(rule, BLUE_RGB, PURPLE_RGB)))
        if subtitle:
            console.print(Align.center(Text(subtitle, style="italic dim")))
        console.print()

        # Commands in a bordered table, centered as a block
        table = Table(
            box=box.ROUNDED,
            show_header=False,
            border_style=PURPLE,
            padding=(0, 2),
            title="Commands",
            title_style=f"bold {BLUE}",
        )
        table.add_column(style=f"bold {BLUE}", no_wrap=True)
        table.add_column(style="white")
        for name in self.list_commands(ctx):
            table.add_row(name, self.get_command(ctx, name).get_short_help_str())
        console.print(Align.center(table))
        console.print()

        # Usage hint
        hint = Text(no_wrap=True)
        hint.append("Use ", style="dim")
        hint.append(f"{ctx.command_path} <command> --help", style=BLUE)
        hint.append(" to see the options.", style="dim")
        console.print(Align.center(hint))
        console.print()


ROOT = Path(__file__).resolve().parent

from onos_topologies.experiments.registry import EXPERIMENTS

RUNNABLE = EXPERIMENTS
EXCLUDE       = {"__init__", "constants", "dependencies"}
TRAFFIC_TYPES = ("ping", "iperf", "ffmpeg")


# helpers

def docker_cleanup():
    # -a so stale exited containers (e.g. from a crashed/interrupted run) get removed too,
    # otherwise the next run's `docker run --name=...` silently fails on the name conflict.
    ids = subprocess.run(["docker", "ps", "-aq"], capture_output=True, text=True).stdout.strip()
    if ids:
        containers = ids.splitlines()
        subprocess.run(["docker", "rm", "-f"] + containers)
        click.echo(f"*** removed {len(containers)} container(s)")
    else:
        click.echo("*** no containers running")


def discover_experiments():
    found = {}
    exp_dir = ROOT / "experiment"
    if exp_dir.is_dir():
        for f in sorted(exp_dir.glob("*.py")):
            if f.stem not in EXCLUDE:
                found[f.stem] = f.relative_to(ROOT)
    for name, module in RUNNABLE.items():
        found[name] = (ROOT / Path(*module.split(".")).with_suffix(".py")).relative_to(ROOT)
    return found


# topology helpers

def _load_config(path: Path) -> dict:
    import importlib.util
    spec = importlib.util.spec_from_file_location("_cfg", path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("CONFIG", "CONFIG_RNP", "DEFAULT_CONFIG", "DEBUG_CONFIG"):
        cfg = getattr(mod, name, None)
        if isinstance(cfg, dict) and "pops" in cfg:
            return cfg
    raise SystemExit(f"no valid config found in {path} - expected CONFIG, CONFIG_RNP, DEFAULT_CONFIG or DEBUG_CONFIG")


# topology repl

REPL_HELP = """\
commands:
  create host <name> <ip>      add a host (iperf3 client)
  create server <name> <ip>    add a server (starts iperf3 -s)
  create switch <name>         add a switch
  connect <name1> <name2>      link two nodes
  traffic <ping|iperf> <n1> <n2> [iperf3 flags...]   (e.g. traffic iperf h0 h1 -t 30 -b 100M)
  ls [hosts|switches]
  quit / help"""


def _run_repl(topo):
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break
        if not line:
            continue
        if line in ("quit", "exit"):
            docker_cleanup()
            break
        if line in ("help", "?"):
            click.echo(REPL_HELP)
            continue
        try:
            cmd, *rest = shlex.split(line)
        except ValueError as e:
            click.echo(f"parse error: {e}")
            continue

        if cmd == "create":
            if rest[:1] == ["switch"] and len(rest) == 2:
                name = rest[1]
                if name in topo.switches:
                    click.echo(f"error: switch '{name}' already exists")
                else:
                    topo.create_switch(name)
            elif rest[:1] == ["host"] and len(rest) == 3:
                name, ip = rest[1], rest[2]
                if name in topo._host_ips:
                    click.echo(f"error: host '{name}' already exists")
                elif ip in topo._host_ips.values():
                    click.echo(f"error: IP {ip} already in use")
                else:
                    topo.create_host(name, ip)
            elif rest[:1] == ["server"] and len(rest) == 3:
                name, ip = rest[1], rest[2]
                if name in topo._host_ips:
                    click.echo(f"error: host '{name}' already exists")
                elif ip in topo._host_ips.values():
                    click.echo(f"error: IP {ip} already in use")
                else:
                    topo.create_server(name, ip)
            else:
                click.echo("usage: create switch <name>  |  create host <name> <ip>  |  create server <name> <ip>")

        elif cmd == "connect" and len(rest) == 2:
            try:
                topo.connect_nodes(rest[0], rest[1])
            except ValueError as e:
                click.echo(f"error: {e}")

        elif cmd == "traffic" and len(rest) >= 3:
            ttype, n1, n2, *extra = rest
            ip2 = topo._host_ips.get(n2)
            if not ip2:
                click.echo(f"unknown host: {n2}")
                continue
            if ttype == "iperf":
                click.echo(f"*** iperf {n1} -> {n2} ({ip2})")
                node2 = topo.clients.get(n2) or topo.servers.get(n2)
                node2.startServer(port=5201)
                # extra is forwarded as-is to iperf3 (e.g. -t 30 -b 100M), overriding the -t 10 default
                subprocess.run(["docker", "exec", n1, "iperf3", "-c", ip2, "-p", "5201", "-t", "10", *extra])
            elif ttype == "ping":
                subprocess.run(["docker", "exec", n1, "ping", "-c", "4", ip2])
            else:
                click.echo(f"unknown traffic type: {ttype}")

        elif cmd == "ls":
            kind = rest[0] if rest else "all"
            if kind in ("all", "host", "hosts"):
                for name, ip in getattr(topo, "_host_ips", {}).items():
                    click.echo(f"  host    {name}  {ip}")
            if kind in ("all", "switch", "switches"):
                for name in topo.switches:
                    click.echo(f"  switch  {name}")

        else:
            click.echo(f"unknown command: {cmd}  (type 'help')")


# cli

@click.group(cls=LftGroup)
def cli():
    """LFT - Network Emulation Tool"""
    if os.geteuid() != 0:
        raise SystemExit("*** lft must be run as root: sudo lft ...")


@cli.command()
@click.argument("name", required=False)
@click.option("--mode", help="Mode name or historical numeric ID")
@click.option("--seed", type=int, help="RNP placement/degradation seed")
@click.option("--run-name", help="Results directory name")
@click.option("--auto-start", is_flag=True, help="Start deployer/supervisor automatically")
@click.option("--hindering", type=click.Choice(["degrade", "take down"]))
def experiment(name, mode, seed, run_name, auto_start, hindering):
    """List or run available experiments"""
    experiments = discover_experiments()
    if name is None:
        width = max((len(n) for n in experiments), default=4)
        for n, path in experiments.items():
            click.echo(f"  {n:<{width}}  {path}")
        return
    if name not in experiments:
        raise SystemExit(f"experiment not found: {name}")
    if name in RUNNABLE:
        from onos_topologies.experiments.registry import load, mode_key
        scenario = name
        kwargs = {}
        if scenario in {"rnp", "diamond"}:
            try:
                kwargs = dict(algorithm=mode_key(scenario, mode) if mode else None,
                              run_name=run_name, auto_start=auto_start)
            except ValueError as error:
                raise click.UsageError(str(error)) from error
            if scenario == "rnp":
                if hindering is not None:
                    raise click.UsageError("--hindering is only supported by diamond")
                kwargs["seed"] = seed
            else:
                if seed is not None:
                    raise click.UsageError("--seed is only supported by rnp")
                kwargs["hindering"] = hindering
        elif any((mode, seed is not None, run_name, auto_start, hindering)):
            raise click.UsageError("DASH runners use their interactive configuration")
        load(scenario).main(**kwargs)
        return
    if any((mode, seed is not None, run_name, auto_start, hindering)):
        raise click.UsageError("These options only apply to ONOS experiments")
    docker_cleanup()
    script = ROOT / experiments[name]
    result = subprocess.run(["python3", str(script)], cwd=script.parent)
    docker_cleanup()
    sys.exit(result.returncode)


@cli.group(cls=LftGroup)
def topology():
    """Create a network topology"""


@topology.command("create")
@click.option("--manual", is_flag=True, help="Open interactive REPL (empty topology)")
@click.option("--path", type=click.Path(exists=True), help="Load config from a constants.py and run")
@click.option("--preset", type=click.Choice(["diamond", "rnp", "dash", "dash-debug"]))
def topology_create(manual, path, preset):
    """Start ONOS and build a topology interactively or from a config file"""
    from onos_topologies.topologies.topology import Topology
    if sum((bool(manual), bool(path), bool(preset))) != 1:
        raise click.UsageError("Choose one of --manual, --path or --preset")

    if manual:
        docker_cleanup()
        topo = Topology(config={
            "pops": (), "adjacency_matrix": (),
            "apply_link_properties": False, "randomize_link_properties": False,
            "throughput": "300mbit", "delay": "10ms", "jitter": "5ms",
        })
        print("*** Starting ONOS controller (waiting ~30s)...", flush=True)
        topo.start_controller()
        print(f"*** ONOS ready - IP: {topo.onos_ip}", flush=True)
        _run_repl(topo)
    elif path or preset:
        if preset:
            from onos_topologies.topologies.configs import diamond, rnp, dash
            config = {"diamond": diamond.CONFIG, "rnp": rnp.CONFIG_RNP,
                      "dash": dash.DEFAULT_CONFIG, "dash-debug": dash.DEBUG_CONFIG}[preset]
        else:
            config = _load_config(Path(path))
        docker_cleanup()
        topo = Topology(config=config)
        topo.run(run_discovery=True, disable_fwd=False)
        _run_repl(topo)
    else:
        raise SystemExit("use --manual for interactive mode or --path <constants.py>")


@cli.group(cls=LftGroup)
def utils():
    """Utility commands"""


@utils.command("clean")
def utils_clean():
    """Remove all running Docker containers"""
    docker_cleanup()


main = cli

if __name__ == "__main__":
    cli()
