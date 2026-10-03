<p align="center"><img src="logos/lft-github.png" width="450" alt="LFT Logo"></p>

# Lightweight Fog Testbed (LFT)

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python: 3.9+](https://img.shields.io/badge/python-3.9+-brightgreen.svg)](https://www.python.org/)
[![Wiki](https://img.shields.io/badge/docs-GitHub%20Wiki-orange.svg)](https://github.com/UnB-COMNET/lft/wiki)

## Description
LFT is a high-performance Python framework designed to orchestrate lightweight, containerized network emulation topologies with ease. Using Docker containers and Linux network namespaces, it allows researchers and engineers to construct arbitrary network topologies, emulate switches (Open vSwitch), SDN controllers (Ryu), cellular links (srsRAN 4G/LTE), and security attack scenarios with CICFlowMeter and perfSONAR integration.

The `onos_topologies/` package additionally builds ONOS experiments for **Intent-Based Networking (IBN)** research: a **Deployer**
receives, processes and applies **Nile intents** over the emulated topology,
and an iperf3-based track compares routing modes under network stress
(degradation or link failure):

- **CDN-QoE**: optimal path/server selection from real-time RTT and throughput.
- **LLM**: LLM-based decision-making via an external service.
- **Threshold**: historical `treshold` mode with `supervisor-quantization`.
- **Reactive Forwarding (fwd)**: standard SDN shortest-path routing.

RNP additionally provides a weighted-Dijkstra baseline and distinct
supervisor drift modes. Mode IDs differ between scenarios; see
[`onos_topologies/README.md`](onos_topologies/README.md).

## 1. Requirements
- **Operating System**: Ubuntu Desktop / Server 24.04 LTS (recommended) or macOS via OrbStack/Docker.
- **Kernel**: Linux 5.15+ with network namespaces, `veth`, and Open vSwitch support.
- **Python**: Python 3.9+ with `pip`.
- **Docker**: Docker Engine 24.0+.
- **Privileges**: root/sudo (the CLI and the containers it manages need it).
- **tmux**: recommended for persistent runs over SSH.

## 2. Installation

One script, one command, from a fresh clone to ready-to-run:

```bash
git clone https://github.com/UnB-COMNET/lft
cd lft
chmod +x dependencies.sh
sudo ./dependencies.sh
```

`dependencies.sh` does everything, in order, and is idempotent (safe to
rerun after a partial/failed run). The full output also goes to
`dependencies.log` (overwritten on every run):

1. OS packages: Docker CE + Compose plugin, Open vSwitch, iproute2/iptables,
   Python 3 + venv, firewalld (installed, not enabled), nfdump, git, tmux —
   pinned versions, falls back to latest with a warning if a pin is gone.
2. `.venv` + `pip install -e .` — installs this package with the versions
   pinned in `setup.py`'s `install_requires`.
3. Docker images the ONOS experiments need: pulls `onosproject/onos:2.5.0`,
   builds `alexandremitsurukaihara/lst2.0:openvswitch` and `lft-iperf` from
   `docker/`.

CDN-QoE/LLM/Threshold modes also need externally supplied `deployer` and
`supervisor` images — see [REIN's own setup](https://github.com/UnB-COMNET/REIN)
in `sistemas/REIN` if you're working inside the PIBIC project, or your own
build of those services otherwise. `dependencies.sh` does not build these;
they come from a different repository.

More images, built from `docker/`, give the topologies real video. Every server also runs `iperf3 -s`
and serves its manifest at `http://<ip>/manifest.mpd`, so `lft traffic start --tool dash` plays any of
them; a client picks the quality by the throughput it measures.

```bash
sudo docker build -t lft-dash-video docker/dash_video_server       # test video, 7 qualities, 60 s in a loop
sudo docker build -t lft-dash-live docker/dash_live_server         # live: ffmpeg encodes 5 qualities in real time
sudo docker build -t lft-pydash-server docker/pydash_server        # Big Buck Bunny, 6 qualities (DASH Dataset 2014)
sudo docker build -t lft-dash-client docker/dash_video_client      # dash-play, dash-client, iperf3, ping
sudo docker build -t lft-pydash-client docker/pydash_client        # pydash (pydash-play), iperf3, ping
```

`lft-pydash-server` fetches its ~720 MB of segments from the dataset at build time. `lft-pydash-client`
runs [pydash](https://github.com/mfcaetano/pydash) unchanged, with an `R2AThroughput` algorithm added to
its `r2a/`; it plays `lft-pydash-server` only, since pydash takes the segment length from the
manifest's `1sec/` folder.

To use LFT only as a Python library, without the CLI and the ONOS experiments, it is also on PyPI:

```bash
pip3 install profissa_lft
```

## 3. Quick Start
Run a simple Software-Defined Network topology:
```bash
cd examples
python3 simpleSDNTopology.py
```

## 4. CLI

After installing, use `sudo lft` to manage topologies interactively.

**Load a topology and open the REPL:**
```bash
sudo lft topology create --preset diamond
# or from a config file:
sudo lft topology create --path onos_topologies/topologies/configs/diamond.py
```

**Start an empty topology manually:**
```bash
sudo lft topology create --manual
```

**REPL commands:**
```
create host <name> <ip>            add a host (iperf3 client)
create server <name> <ip>          add a server (starts iperf3 -s)
create switch <name>               add a switch
connect <name1> <name2>            link two nodes
traffic <ping|iperf> <n1> <n2> [iperf3 flags...]
ls [hosts|switches]
quit / help
```

**Other commands:**
```bash
sudo lft experiment [--json]               # list available experiments
sudo lft experiment <name>                 # run an experiment
sudo lft utils clean                       # remove the topology's containers (label lft=1), nothing else
```

**Managing a running topology.** `onos_topologies/runtime/` reads what is running (docker, ovs-vsctl,
ip, tc) and changes it with what the topologies are built with; the state is saved in
`/var/lib/lft/topology.json`. Every command takes `--help` and `--json` (the result as JSON on
stdout, the progress as JSON lines on stderr), so other programs can drive LFT:
```bash
sudo lft topology create --preset diamond-video --detach   # build and exit (no REPL)
sudo lft topology export --path topo.py      # what is running as a topology file (builds again with --path)
sudo lft topology show | sync | status       # saved state, read it again from the system, containers
sudo lft link set s0 s1 --rate 10mbit --delay 20ms --loss 0.5
sudo lft link down | up | reset s0 s1        # and: sudo lft link stats (counters and rates)
sudo lft host add cl3 --switch s2 --ip 192.168.0.9 --image lft-dash-client [--server]
sudo lft host set | rm | pause | unpause cl3
sudo lft switch add s4 --desc BA --link s0:rate=50mbit,delay=8ms
sudo lft switch stop | start | rm s4 [--with-hosts]   # stop: no controller, links down, paused
sudo lft iface ls [--node s0]                # veth ends: peer, address, qdisc, shaping, counters
sudo lft capture start --iface s0s1 --duration 30     # and: capture ls | stop c1
sudo lft traffic start --tool iperf3|dash|ping --client cl0 --server ds0 [--duration 60]
sudo lft traffic ls | stop | logs t1 [--follow]
sudo lft timeline run plan.py                # link states, traffic, captures and HTTP calls on a schedule
sudo lft results ls [--run timeline/<run>]
```
The timeline file format is described at the top of `onos_topologies/runtime/timeline.py`.

---

## 5. ONOS experiments and results

The maintained entry points and directory guide are documented in
[onos_topologies/README.md](onos_topologies/README.md). Start with:

```bash
sudo lft experiment diamond --mode fwd --hindering degrade --run-name diamond-first
sudo lft experiment rnp --mode baseline --seed 1 --run-name rnp-first
```

Diamond runs six 60-second measurement windows. RNP runs twelve 60-second
windows with continuous traffic and seeded placement. Both degrade even-numbered
windows; setup and orchestration add time outside the measurement windows.

Results remain under `results/iperf/<run-name>/`. Diamond writes
`iperf_flow_all.csv` and `ping_flow_all.csv`; RNP writes `iperf_all.csv` and
`ping_all.csv`. Both retain OVS outputs. See
[onos_topologies/README.md](onos_topologies/README.md) for modes, external
services, batches and validation requirements.

## 6. Troubleshooting

If you face an issue running any LFT command:

1. Check that `dependencies.sh` ran to completion (`sudo lft` should print
   the banner, not an import error) — rerun it, it's idempotent.
2. Check for leftover containers from a previous run: `docker ps -a`. Remove
   them with `sudo lft utils clean` or `docker rm -f <name>`.
3. Verify the images this experiment needs exist locally (`docker images`) —
   see §2 and, for CDN-QoE/LLM/Threshold, the `deployer`/`supervisor`
   images from REIN.
4. ⚠️ Cleanup routines remove **all** Docker containers on the host. Use a
   dedicated machine, not your daily driver.
5. Consult the [Troubleshooting Guide](https://github.com/UnB-COMNET/lft/wiki/Troubleshooting) or [`docs/Troubleshooting.md`](docs/Troubleshooting.md).

## 7. Documentation
Complete, in-depth documentation is available across multiple formats:

- **Interactive GitHub Wiki**: **[UnB-COMNET/lft Wiki](https://github.com/UnB-COMNET/lft/wiki)** (with sidebar navigation, diagrams, and quick references).
- **Markdown Documentation**: Offline-browsable Markdown files in the [`docs/`](docs/) directory.
- **Native DokuWiki Syntax**: Pre-formatted `.txt` files in [`dokuwiki/`](dokuwiki/) ready to import into local lab or university DokuWiki servers.

### Documentation Index
- **[Installation & Requirements](docs/Installation.md)**
- **[LFT Core Architecture](docs/Architecture.md)**
- **[Full API Reference](docs/API-Reference.md)**
- **[SDN Topologies](docs/SDN-Topologies.md)**
- **[Code Examples Walkthrough](docs/Code-Examples.md)** (covers all 8 scripts in `examples/`)
- **[Experiments & Benchmarks](docs/Experiments-and-Benchmarks.md)** (deployment time, scalability, perfSONAR, wired and wireless benchmarks in `experiment/`)
- **[Security Scenario: UNBCA / CIDDS](docs/Security-Scenario-UNBCA.md)** (enterprise topology, benign behaviors, attacks, and flow datasets in `scenario/`)
- **[4G/LTE Cellular Emulation](docs/Wireless-4G-Emulation.md)** (srsRAN EPC, eNodeB, UEs, and ZMQ virtual radio)
- **[Docker Image Catalog](docs/Docker-Images.md)** (specifications for all 11 Docker images)
- **[Troubleshooting & Teardown](docs/Troubleshooting.md)**
- **[Complete Master Manual (All-in-One)](docs/Master-Manual.md)** &bull; [`dokuwiki/LFT_MASTER_MANUAL.txt`](dokuwiki/LFT_MASTER_MANUAL.txt)
