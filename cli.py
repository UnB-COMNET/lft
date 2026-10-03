#!/usr/bin/env python3
import warnings
warnings.filterwarnings("ignore")

import json
import os
import re
import sys
import shlex
import subprocess
import time
from contextlib import contextmanager
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
from onos_topologies.runtime import TopologyError, capture, hosts, links, print_step, results, shaping, state, switches, timeline, traffic

RUNNABLE = EXPERIMENTS
EXCLUDE       = {"__init__", "constants", "dependencies"}
TRAFFIC_TYPES = ("ping", "iperf", "ffmpeg")


# helpers

def docker_cleanup():
    # Only the topology's containers (label lft=1), stopped ones included, so a crashed run's leftovers
    # go and nothing else on the host is touched
    removed = state.clean()
    click.echo(f"*** removed {len(removed)} container(s)" if removed else "*** no topology containers")


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
    from onos_topologies.topologies import topology_file
    try:
        return topology_file.load(path)[1]
    except TopologyError as error:
        raise SystemExit(str(error))


# output of the commands on the running topology

# Brief: Prints a result: JSON with --json, else text (a string, or a function of the result)
def emit(data, as_json: bool, text):
    if as_json:
        click.echo(json.dumps(data, indent=1))
    else:
        click.echo(text(data) if callable(text) else text)


# Brief: Reports a failure ({"ok": false, "error"} on stdout with --json) and exits with 1
def fail(error, as_json: bool):
    if as_json:
        click.echo(json.dumps({"ok": False, "error": str(error)}))
    else:
        click.echo(f"*** {error}", err=True)
    sys.exit(1)


# Brief: Progress of an operation for programs: one JSON line per step on stderr, {"step", "of", "title"}
def json_step(step: int, steps: int, title: str) -> None:
    click.echo(json.dumps({"step": step, "of": steps, "title": title}), err=True)


# Brief: Sends what runs inside (Python and child processes alike) to stderr, so that with --json stdout
# holds only the JSON result. Line by line, as it happens: whoever reads it (the console) shows progress
@contextmanager
def stdout_to_stderr(active: bool):
    if not active:
        yield
        return
    sys.stdout.flush()
    saved = os.dup(1)
    os.dup2(2, 1)
    sys.stdout.reconfigure(line_buffering=True)
    try:
        yield
    finally:
        sys.stdout.flush()
        sys.stdout.reconfigure(line_buffering=False)
        os.dup2(saved, 1)
        os.close(saved)


# Brief: Runs an operation of onos_topologies.runtime with its progress (JSON lines on stderr with --json);
# on failure, prints the error and exits
# Params:
#   operation: e.g. links.shape, hosts.add
#   bool as_json: The --json flag
#   args, kwargs: Its arguments
# Return:
#   What the operation returns
def call(operation, as_json: bool, *args, **kwargs):
    try:
        with stdout_to_stderr(as_json):
            return operation(*args, **kwargs, report=json_step if as_json else print_step)
    except Exception as error:   # the primitives raise plain exceptions too; the state shows what changed
        state.sync()
        fail(error, as_json)


# Brief: After a change: saves the topology's state and prints it ({"ok": true, "state"})
def changed(as_json: bool):
    emit({"ok": True, "state": state.sync()}, as_json, "*** done")


def json_option(f):
    return click.option("--json", "as_json", is_flag=True, help="Print the result as JSON (progress as JSON lines on stderr)")(f)


# values of the shaping options

# Brief: "10mbit", "500kbit", "35M" (iperf3 style) or a number of Mb/s -> Mb/s
def parse_rate(value) -> float:
    text = str(value)
    if re.fullmatch(r"\d+(\.\d+)?", text):
        rate = float(text)
    elif re.fullmatch(r"\d+(\.\d+)?[KMG]", text):
        rate = float(text[:-1]) * {"K": 0.001, "M": 1, "G": 1000}[text[-1]]
    else:
        rate = shaping.mbit(text)
    if rate <= 0:
        raise ValueError(f"rate must be positive, not {value}")
    return rate


# Brief: "20ms", "1s" or a number of ms -> ms
def parse_ms(value) -> float:
    text = str(value)
    return float(text) if re.fullmatch(r"\d+(\.\d+)?", text) else shaping.ms(text)


# Brief: "0.5" or "0.5%" -> 0.5
def parse_loss(value) -> float:
    loss = float(str(value).rstrip("%"))
    if not 0 <= loss <= 100:
        raise ValueError(f"loss must be between 0 and 100%, not {value}")
    return loss


PARSE = {"rate": parse_rate, "delay": parse_ms, "jitter": parse_ms, "loss": parse_loss}


# Brief: The --rate, --delay, --jitter and --loss options, as numbers; None for the ones left out
def shaping_values(**options) -> dict:
    try:
        return {k: None if v is None else PARSE[k](v) for k, v in options.items()}
    except ValueError as error:
        raise click.UsageError(str(error))


def shaping_options(f):
    f = click.option("--loss", help="Packet loss in %, e.g. 0.5")(f)
    f = click.option("--jitter", help="Jitter: 1ms, or a number of ms")(f)
    f = click.option("--delay", help="One-way delay: 20ms, or a number of ms")(f)
    return click.option("--rate", help="Rate: 10mbit, 500kbit, or a number of Mb/s")(f)


# Brief: "s0:rate=50mbit,delay=8ms,loss=0" -> ("s0", {rate, delay, jitter, loss}) over the defaults
def parse_link(text: str, defaults: dict) -> tuple:
    other, _, options = text.partition(":")
    values = dict(defaults)
    for item in filter(None, options.split(",")):
        key, _, value = item.partition("=")
        if key not in PARSE:
            raise click.UsageError(f"unknown link option {key!r} (rate, delay, jitter, loss)")
        values.update(shaping_values(**{key: value}))
    return other, values


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
@click.option("--auto-start/--no-auto-start", default=None,
              help="Start deployer/supervisor automatically, or use the running ones (default: ask)")
@click.option("--hindering", type=click.Choice(["degrade", "take down"]))
@click.option("--clients", type=click.IntRange(1, 1000), help="dash-load: clients in the last window")
@click.option("--duration", type=click.IntRange(1, 86400), help="dash, dash-load: seconds per window")
@click.option("--yes", is_flag=True, help="dash, dash-load: answer yes to their questions")
@click.option("--json", "as_json", is_flag=True, help="Without a name: list the runners as JSON")
def experiment(name, mode, seed, run_name, auto_start, hindering, clients, duration, yes, as_json):
    """List or run available experiments"""
    experiments = discover_experiments()
    if name is None:
        if as_json:
            from onos_topologies.experiments.registry import describe
            emit(describe(), True, "")
            return
        width = max((len(n) for n in experiments), default=4)
        for n, path in experiments.items():
            click.echo(f"  {n:<{width}}  {path}")
        return
    if name not in experiments:
        raise SystemExit(f"experiment not found: {name}")
    if name in RUNNABLE:
        from onos_topologies.experiments.registry import load, mode_key
        from onos_topologies.experiments.runtime import finish
        scenario = name
        kwargs = {}
        if scenario in {"rnp", "diamond"}:
            if clients or duration or yes:
                raise click.UsageError("--clients, --duration and --yes apply to dash and dash-load")
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
        elif any((mode, seed is not None, run_name, auto_start is not None, hindering)):
            raise click.UsageError("--mode, --seed, --run-name, --auto-start and --hindering apply to rnp and diamond")
        else:
            if clients and scenario != "dash-load":
                raise click.UsageError("--clients is only supported by dash-load")
            kwargs = dict(yes=yes, duration=duration, **({"clients": clients} if clients else {}))
        before = os.environ.get("LFT_RESULTS")
        load(scenario).main(**kwargs)
        if os.environ.get("LFT_RESULTS") not in (None, before):   # the runner exported its run directory
            finish(Path(os.environ["LFT_RESULTS"]))
        return
    if any((mode, seed is not None, run_name, auto_start is not None, hindering)):
        raise click.UsageError("These options only apply to ONOS experiments")
    docker_cleanup()
    script = ROOT / experiments[name]
    result = subprocess.run(["python3", str(script)], cwd=script.parent)
    docker_cleanup()
    sys.exit(result.returncode)


@cli.group(cls=LftGroup)
def topology():
    """Create a topology and see what is running"""


PRESETS = ("diamond", "rnp", "dash", "dash-debug", "diamond-video")


def _preset(name: str) -> dict:
    from onos_topologies.topologies.configs import diamond, rnp, dash
    if name == "diamond-video":   # diamond with a DASH video server and player, access links unshaped
        return {**diamond.CONFIG, "server_image": "lft-dash-video", "client_image": "lft-dash-client",
                "apply_access_link_properties": False}
    return {"diamond": diamond.CONFIG, "rnp": rnp.CONFIG_RNP, "dash": dash.DEFAULT_CONFIG, "dash-debug": dash.DEBUG_CONFIG}[name]


@topology.command("create")
@click.option("--manual", is_flag=True, help="Open interactive REPL (empty topology)")
@click.option("--path", type=click.Path(exists=True), help="Load config from a constants.py and run")
@click.option("--preset", type=click.Choice(PRESETS))
@click.option("--detach", is_flag=True, help="Build, save the topology's state and exit (no REPL)")
@click.option("--disable-fwd", is_flag=True, help="Deactivate ONOS reactive forwarding")
@click.option("--json", "as_json", is_flag=True, help="With --detach: progress as JSON lines on stderr, the topology's state as JSON")
def topology_create(manual, path, preset, detach, disable_fwd, as_json):
    """Start ONOS and build a topology interactively or from a config file"""
    from onos_topologies.topologies import topology_file
    from onos_topologies.topologies.topology import Topology
    if sum((bool(manual), bool(path), bool(preset))) != 1:
        raise click.UsageError("Choose one of --manual, --path or --preset")
    if as_json and not detach:
        raise click.UsageError("--json needs --detach (the REPL is interactive)")

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
        return

    if preset:
        config, module, name = _preset(preset), None, preset
    else:
        try:
            module, config = topology_file.load(path)
        except TopologyError as error:
            fail(error, as_json)
        name = Path(path).stem.removesuffix("_topology")
    try:
        with stdout_to_stderr(as_json):
            docker_cleanup()
            topo = topology_file.build(config, name, module, disable_fwd, json_step if as_json else print_step)
    except Exception as error:
        fail(error, as_json)
    if detach:
        emit(state.load(), as_json, f"*** topology '{name}' is up; its state is in {state.STATE}")
    else:
        _run_repl(topo)


@topology.command("export")
@click.option("--path", default="-", show_default=True, help="Output file, or - for stdout")
def topology_export(path):
    """Write the running topology as a topology file (POPS, matrices, CONFIG, HOSTS, DOWN_LINKS)"""
    from onos_topologies.topologies import topology_file
    text = topology_file.export(state.load())
    if path == "-":
        click.echo(text, nl=False)
    else:
        Path(path).write_text(text)
        click.echo(f"*** wrote {path}")


# what is running

def shape_text(v: dict) -> str:
    rate = "-" if v.get("rate") is None else f"{v['rate']:g} Mb/s"
    return f"{rate}, {v['delay']:g} ms, jitter {v['jitter']:g} ms, loss {v['loss']:g}%"


def topology_text(current: dict) -> str:
    lines = [f"topology {current['name'] or '-'}   controller {current['controller'] or '-'}", "switches"]
    for s in state.switches(current):
        lines.append(f"  {s['id']:<6} {s['desc'] or '-':<6} {s['dpid'] or '-':<20} {'off' if s['off'] else 'on'}")
    lines.append("hosts")
    for h in state.hosts(current):
        paused = "  paused" if h["paused"] else ""
        lines.append(f"  {h['id']:<6} {h['role'] or '-':<7} {h['sw'] or '-':<6} {h['ip'] or '-':<15} {h['image']}{paused}")
    lines.append("links")
    for l in current["links"]:
        lines.append(f"  {l['id']:<8} {'down' if l['now']['down'] else shape_text(l['now'])}")
    return "\n".join(lines)


def status_text(st: dict) -> str:
    return "\n".join(f"  {c['name']:<8} {c['kind'] or '-':<11} {c['state']:<8} {c['image']}" for c in st["containers"]) or "  no topology running"


@topology.command("show")
@click.option("--json", "as_json", is_flag=True, help="Print the state as JSON")
def topology_show(as_json):
    """Print the saved state of the running topology: switches, hosts and links"""
    emit(state.load(), as_json, topology_text)


@topology.command("sync")
@click.option("--json", "as_json", is_flag=True, help="Print the state as JSON")
def topology_sync(as_json):
    """Read the running topology from docker, ovs-vsctl, ip and tc, and save its state"""
    emit(state.sync(), as_json, topology_text)


@topology.command("status")
@click.option("--json", "as_json", is_flag=True, help="Print the status as JSON")
def topology_status(as_json):
    """The topology's containers and the local images"""
    emit(state.status(), as_json, status_text)


# links

@cli.group(cls=LftGroup)
def link():
    """Shape the links between switches, take them down and back up"""


@link.command("set")
@click.argument("a")
@click.argument("b")
@shaping_options
@json_option
def link_set(a, b, rate, delay, jitter, loss, as_json):
    """Shape both ends of a link; options left out keep their value"""
    call(links.shape, as_json, a, b, **shaping_values(rate=rate, delay=delay, jitter=jitter, loss=loss))
    changed(as_json)


@link.command("down")
@click.argument("a")
@click.argument("b")
@json_option
def link_down(a, b, as_json):
    """Take a link down"""
    call(links.down, as_json, a, b)
    changed(as_json)


@link.command("up")
@click.argument("a")
@click.argument("b")
@json_option
def link_up(a, b, as_json):
    """Bring a link back up"""
    call(links.up, as_json, a, b)
    changed(as_json)


@link.command("reset")
@click.argument("a")
@click.argument("b")
@json_option
def link_reset(a, b, as_json):
    """Back to the shaping the link was built with, and up"""
    call(links.reset, as_json, a, b)
    changed(as_json)


def stats_text(st: dict) -> str:
    def rate(value):
        return "-" if value is None else f"{value:.2f}"
    lines = [f"  {lid:<8} {rate(s['ab']):>9} Mb/s ->  {rate(s['ba']):>9} Mb/s <-{'  down' if s['down'] else ''}"
             for lid, s in st["links"].items()]
    lines += [f"  {hid:<8} tx {rate(s['tx']):>9} Mb/s  rx {rate(s['rx']):>9} Mb/s" for hid, s in st["hosts"].items()]
    return "\n".join(lines)


@link.command("stats")
@click.option("--json", "as_json", is_flag=True, help="Print counters and rates as JSON")
def link_stats(as_json):
    """Counters of every veth end, and the rate since the previous call"""
    emit(state.link_stats(), as_json, stats_text)


# hosts

@cli.group(cls=LftGroup)
def host():
    """Create, change, remove and pause hosts"""


@host.command("add")
@click.argument("name")
@click.option("--switch", "sw", required=True, help="Switch the host hangs from, e.g. s2")
@click.option("--ip", required=True, help="Its address (/24)")
@click.option("--image", required=True, help="Docker image")
@click.option("--server", is_flag=True, help="Run the image's own command (a server) instead of idling (a client)")
@json_option
def host_add(name, sw, ip, image, server, as_json):
    """Create a host linked to a switch"""
    call(hosts.add, as_json, name, sw, ip, image, server)
    changed(as_json)


@host.command("set")
@click.argument("name")
@click.option("--name", "new_name", help="New name")
@click.option("--switch", "sw", help="Move it to another switch")
@click.option("--ip", help="New address")
@click.option("--image", help="New image")
@json_option
def host_set(name, new_name, sw, ip, image, as_json):
    """Change a host (it is created again with the new values)"""
    call(hosts.change, as_json, name, new_name, sw, ip, image)
    changed(as_json)


@host.command("rm")
@click.argument("name")
@json_option
def host_rm(name, as_json):
    """Remove a host"""
    call(hosts.rm, as_json, name)
    changed(as_json)


@host.command("pause")
@click.argument("name")
@json_option
def host_pause(name, as_json):
    """Freeze a host (docker pause): its traffic stops, its link stays"""
    call(hosts.pause, as_json, name, True)
    changed(as_json)


@host.command("unpause")
@click.argument("name")
@json_option
def host_unpause(name, as_json):
    """Resume a paused host"""
    call(hosts.pause, as_json, name, False)
    changed(as_json)


# switches

@cli.group(cls=LftGroup)
def switch():
    """Add, turn off and on, and remove Open vSwitch switches"""


@switch.command("add")
@click.argument("name")
@click.option("--desc", default="", help="Bridge description (dp-desc), shown by the controller")
@click.option("--dpid", default="", help="Datapath id, 16 hex digits (default: chosen by Open vSwitch)")
@click.option("--controller", help="e.g. tcp:172.17.0.2:6653 (default: the one the topology's switches use)")
@click.option("--link", "link_specs", multiple=True, help="Link to a switch: s0:rate=50mbit,delay=8ms,jitter=1ms,loss=0 (repeatable)")
@json_option
def switch_add(name, desc, dpid, controller, link_specs, as_json):
    """Create a switch connected to the controller, with its links"""
    defaults = state.load()["defaults"]
    call(switches.add, as_json, name, desc, [parse_link(text, defaults) for text in link_specs], dpid, controller)
    changed(as_json)


@switch.command("stop")
@click.argument("name")
@json_option
def switch_stop(name, as_json):
    """Turn a switch off: controller disconnected, its links down, container paused"""
    call(switches.stop, as_json, name)
    changed(as_json)


@switch.command("start")
@click.argument("name")
@json_option
def switch_start(name, as_json):
    """Turn a switch back on"""
    call(switches.start, as_json, name)
    changed(as_json)


@switch.command("rm")
@click.argument("name")
@click.option("--with-hosts", is_flag=True, help="Also remove the hosts on it")
@json_option
def switch_rm(name, with_hosts, as_json):
    """Remove a switch and its links"""
    call(switches.rm, as_json, name, with_hosts)
    changed(as_json)


# interfaces and captures

@cli.group(cls=LftGroup)
def iface():
    """Veth ends of the running topology"""


def iface_text(rows: list) -> str:
    lines = []
    for i in rows:
        shaped = shape_text(i["shaping"]) if i["shaping"] else "unshaped"
        lines.append(f"  {i['name']:<8} {i['node']:<6} -> {i['peer']:<8} {'up' if i['up'] else 'down':<5} {i['ip'] or '-':<17} "
                     f"{shaped:<44} rx {i['rx_bytes']} B  tx {i['tx_bytes']} B")
    return "\n".join(lines)


@iface.command("ls")
@click.option("--node", help="Only this node's interfaces")
@click.option("--json", "as_json", is_flag=True, help="Print the interfaces as JSON")
def iface_ls(node, as_json):
    """List the veth ends: peer, address, MAC, qdisc, shaping and counters"""
    emit(state.iface_ls(node), as_json, iface_text)


@cli.group("capture", cls=LftGroup)
def capture_group():
    """Packet captures (tcpdump) on the veth ends"""


def capture_text(rows) -> str:
    rows = rows if isinstance(rows, list) else [rows]
    return "\n".join(f"  {c['id']:<4} {c.get('status', 'running'):<8} {c['iface']:<8} {c['out']}" for c in rows) or "  no captures"


@capture_group.command("start")
@click.option("--iface", required=True, help="Interface, e.g. s0s1 (captured in s0)")
@click.option("--duration", default=30, show_default=True, type=click.IntRange(0, 86400), help="Seconds; 0 runs until capture stop")
@click.option("--out", help="pcap file (default results/pcap/<iface>-<time>.pcap)")
@click.option("--filter", "bpf", default="", help="tcpdump filter, e.g. 'host 192.168.0.2'")
@json_option
def capture_start(iface, duration, out, bpf, as_json):
    """Start a capture in the background and print its id"""
    emit(call(capture.start, as_json, iface, duration, out, bpf), as_json, capture_text)


@capture_group.command("stop")
@click.argument("capture_id")
@click.option("--json", "as_json", is_flag=True, help="Print the capture as JSON")
def capture_stop(capture_id, as_json):
    """Stop a capture (tcpdump writes what it has)"""
    try:
        emit(capture.stop(capture_id), as_json, capture_text)
    except KeyError as error:
        fail(error.args[0], as_json)


@capture_group.command("ls")
@click.option("--json", "as_json", is_flag=True, help="Print the captures as JSON")
def capture_ls(as_json):
    """List the captures and whether they still run"""
    emit(capture.ls(), as_json, capture_text)


# traffic

@cli.group("traffic", cls=LftGroup)
def traffic_group():
    """Traffic between hosts: iperf3, DASH and ping"""


def traffic_text(rows) -> str:
    rows = rows if isinstance(rows, list) else [rows]
    lines = []
    for t in rows:
        port = f":{t['port']}" if t["port"] else ""
        rate = "" if t.get("rate_mbps") is None else f"{t['rate_mbps']:.2f} Mb/s"
        lines.append(f"  {t['id']:<4} {t.get('status', 'running'):<8} {t['tool']:<6} {t['client']} -> {t['server']}{port:<6} {rate:>12}  {t['file']}")
    return "\n".join(lines) or "  no traffic"


@traffic_group.command("start")
@click.option("--tool", type=click.Choice(traffic.TOOLS), default="iperf3", show_default=True)
@click.option("--client", required=True, help="Client host, e.g. cl0")
@click.option("--server", required=True, help="Server host, e.g. ds0")
@click.option("--port", default=5201, show_default=True, type=click.IntRange(1024, 65535), help="iperf3 port (the next free one if taken)")
@click.option("--reverse", is_flag=True, help="iperf3 -R: the server sends")
@click.option("--proto", type=click.Choice(["tcp", "udp"]), default="tcp", show_default=True)
@click.option("--rate", default="35M", show_default=True, help="iperf3 target rate: 35M, 35mbit or Mb/s")
@click.option("--duration", default=0, type=click.IntRange(0, 86400), help="Seconds (0: until traffic stop)")
@click.option("--interval", default=1.0, show_default=True, type=click.FloatRange(0.2, 60), help="ping interval (s)")
@click.option("--out", help="Output directory (default results/iperf|dash/manual/<time>)")
@json_option
def traffic_start(tool, client, server, port, reverse, proto, rate, duration, interval, out, as_json):
    """Start traffic in the background and print its id"""
    meta = call(traffic.start, as_json, tool, client, server, port, reverse, proto, shaping_values(rate=rate)["rate"],
                duration, interval, out)
    emit(meta, as_json, traffic_text)


@traffic_group.command("ls")
@click.option("--json", "as_json", is_flag=True, help="Print the sessions as JSON")
def traffic_ls(as_json):
    """List the sessions, their state and last rate"""
    emit(traffic.ls(), as_json, traffic_text)


@traffic_group.command("stop")
@click.argument("session_id")
@click.option("--json", "as_json", is_flag=True, help="Print the session as JSON")
def traffic_stop(session_id, as_json):
    """Stop a session (the tool prints its summary)"""
    try:
        emit(traffic.stop(session_id), as_json, traffic_text)
    except KeyError as error:
        fail(error.args[0], as_json)


@traffic_group.command("logs")
@click.argument("session_id")
@click.option("--follow", is_flag=True, help="Keep printing until the session ends")
@click.option("--json", "as_json", is_flag=True, help="One JSON line per output line: {side, line}")
def traffic_logs(session_id, follow, as_json):
    """Print the client's output and the server's"""
    try:
        for side, line in traffic.logs(session_id, follow):
            click.echo(json.dumps({"side": side, "line": line}) if as_json else f"[{side}] {line}")
    except KeyError as error:
        fail(error.args[0], as_json)


# timelines and results

@cli.group("timeline", cls=LftGroup)
def timeline_group():
    """Link changes, traffic, captures and HTTP calls on a schedule"""


@timeline_group.command("run")
@click.argument("path", type=click.Path(exists=True))
def timeline_run(path):
    """Run a timeline file on the running topology (see onos_topologies/runtime/timeline.py)"""
    try:
        run_dir = timeline.run(path)
    except TopologyError as error:
        fail(error, False)
    click.echo(f"*** results in {run_dir}")


@cli.group("results", cls=LftGroup)
def results_group():
    """Runs and the files they wrote under results/"""


def runs_text(rows: list) -> str:
    lines = []
    for r in rows:
        started = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["started"]))
        lines.append(f"  {started}  {r['status']:<10} {r['windows']:>3} windows {r['files']:>5} files  {r['id']}")
    return "\n".join(lines)


@results_group.command("ls")
@click.option("--run", help="One run's files, e.g. iperf/diamond-first")
@click.option("--json", "as_json", is_flag=True, help="Print as JSON")
def results_ls(run, as_json):
    """List the runs (newest first), or the files of one run"""
    try:
        rows = results.ls(run)
    except KeyError as error:
        fail(error.args[0], as_json)
    if run:
        emit(rows, as_json, "\n".join(f"  {r['bytes']:>10}  {r['path']}" for r in rows))
    else:
        emit(rows, as_json, runs_text)


@cli.group(cls=LftGroup)
def utils():
    """Utility commands"""


@utils.command("clean")
@json_option
def utils_clean(as_json):
    """Remove the topology's containers (label lft=1); nothing else on the host"""
    with stdout_to_stderr(as_json):
        docker_cleanup()
    changed(as_json)


main = cli

if __name__ == "__main__":
    cli()
