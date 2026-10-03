# ONOS topologies and experiments

This package builds Docker-based networks using `profissa_lft` and runs ONOS
experiments. Runtime requires Linux, Docker, `iproute2` and root privileges.
Importing its modules does not create containers or start measurements.

## Directory guide

| Directory | Responsibility |
| --- | --- |
| `infrastructure/` | ONOS REST/SSH, containers, OVS switches and traffic control |
| `topologies/` | Network construction; `configs/` contains network definitions |
| `traffic/` | iPerf and DASH client/server containers |
| `experiments/` | Runners, batch plans and shared execution helpers |
| `experiments/rnp/` | RNP settings, baseline decisions, traffic sessions and callbacks |
| `measurements/` | OVS, PCAP, iPerf, ping, hardware and service metrics; CSV processing |
| `runtime/` | Procedures on a running topology: its state, link, host and switch changes, traffic, captures and timelines |
| `assets/` | ONOS application archives, DASH certificates and Power BI dashboard |

`demo/` and `dataset/` retain their experimental logic; their imports now use
these directories. The old `dash_topology/`, `iperf_experiment/` and root-level
compatibility modules have been removed. Use `Topology` from
`onos_topologies.topologies.topology` when constructing networks.

Traffic clients and servers share one module per protocol (`traffic/iperf.py`
and `traffic/dash.py`). RNP's path selection lives in `baseline.py`; its traffic
lifecycle and callback endpoint live together in `session.py`. ONOS REST remains
in `infrastructure/onos_client.py`, while Linux traffic control belongs solely to
`infrastructure/traffic_control.py`.

## Installation and first run

Install from the repository root:

```bash
python3 -m pip install -e .
sudo docker pull onosproject/onos:2.5.0
sudo docker build -t alexandremitsurukaihara/lst2.0:openvswitch docker/openswitch
sudo docker build -t lft-iperf docker/iperf
```

List experiments or create the small diamond network interactively:

```bash
sudo lft experiment
sudo lft topology create --preset diamond
```

The topology REPL supports `ls`, `create`, `connect`, `traffic` and `quit`.
Use `help` inside the REPL for syntax. To run the existing six-window diamond
experiment with reactive forwarding:

```bash
sudo lft experiment diamond --mode fwd --hindering degrade --run-name diamond-first
```

Each measurement window is 60 seconds; controller startup, discovery and
stabilization add time. The existing cleanup routines remove **all Docker
containers**; run experiments on a dedicated test host. Choosing an existing run
name can overwrite outputs or append to existing logs. Use a fresh name unless
intentionally repeating the historical overwrite behavior.

## Experiments and services

| Runner | Modes (historical numeric IDs) | Measurement policy |
| --- | --- | --- |
| `diamond` | 1 `cdn-qoe`, 2 `llm`, 3 `treshold`, 4 `fwd` | Six 60-second windows; impairment on 2, 4 and 6; new iPerf process per window |
| `rnp` | 1 `cdn-qoe`, 2 `baseline`, 3 `fwd`, 4 `cdn-qoe-best-path`, 5 `llm` | Twelve 60-second windows; impairment on even windows; continuous iPerf and server changes |
| `dash` | Interactive topology/capture options | Continuous capture loop |
| `dash-load` | Existing cumulative client plan | Four 300-second windows, capped by available clients |

The spelling `treshold` is retained because it is an existing mode identifier.
Numeric IDs are scenario-specific: `3` means `treshold` in diamond and `fwd` in RNP.
Prefer mode names in CLI and batch commands.

- iPerf runners need ONOS and OVS images shown above.
- CDN-QoE/LLM modes also require externally supplied `deployer` and `supervisor`
  images/services. Their source is not included in this package. Diamond's
  threshold mode uses `supervisor-quantization`.
- RNP services use localhost ports 5000 and 5151; the server-change callback
  listens on 5152. RNP LLM mode accepts `LLM_URL` through the environment.
- Diamond's LLM warmup URL is currently configured in `experiments/diamond/run.py`.
- DASH needs images built/tagged as `neubot/dash-client:latest` and
  `neubot/dash:latest` from `docker/dash_client` and `docker/dash_server`.
  PCAP conversion needs `tshark` on the host.

With services available:

```bash
sudo lft experiment rnp --mode cdn-qoe --seed 1 --auto-start --run-name rnp-cdn-seed1
sudo lft experiment rnp --mode baseline --seed 1 --run-name rnp-baseline-seed1
```

Without `--auto-start`, modes that use external services ask how to start them.
Omitted mode, RNP seed or run name retains the runner's interactive prompts.
Use the canonical CLI names `rnp` and `diamond`; historical aliases were removed.

## Batches and individual reruns

```bash
sudo python3 -m onos_topologies.experiments.batch rnp --modes baseline fwd --seeds 1 2 3
sudo python3 -m onos_topologies.experiments.batch rnp --modes fwd --seeds 10
sudo python3 -m onos_topologies.experiments.batch diamond --modes fwd --seeds 1 2 --hindering degrade
```

Batch defaults to seeds/repetitions 1–10, automatic service startup and a
15-second pause between runs. `--manual-services` retains interactive service
startup. For diamond, `--seeds` supplies repetition numbers only; its experiment
does not implement seeded placement. Failures are reported, later runs continue,
and the batch command exits nonzero if any run fails.

RNP names remain `<mode>-degrade-seed<N>`; diamond names remain
`<mode>-<hindering>-<NN>`. The former `batch_temp.py` rerun is the second command
above. The old batch scripts were removed. Use the batch command above with explicit
modes and seeds. After installation, use `python3 -m ...` rather than depending
on the script's working directory.

## Configuration and adding a topology

Network definitions live in `topologies/configs/`: `diamond.py`, `rnp.py` and
`dash.py`. These remain Python dictionaries; no new configuration dependency is
required. RNP and DASH matrices are different and intentionally remain separate.
RNP host placement is reset before each run and uses its configured seed.

To add a network, copy a small configuration such as `diamond.CONFIG`, preserve
the order shared by `pops` and `adjacency_matrix`, and set link properties.
An optional throughput matrix supplies bandwidth; an RTT matrix is converted to
per-direction delay by the existing builder. Load it with:

```bash
sudo lft topology create --path path/to/network.py
```

The loader accepts `CONFIG`, `CONFIG_RNP`, `DEFAULT_CONFIG` or `DEBUG_CONFIG`.
`--preset dash-debug` selects the existing smaller DASH network definition.
Topology creation preserves the existing iPerf default. To construct DASH
hosts through the Python API, pass `iperf=False` explicitly.

Experiment policies belong in `experiments/<scenario>/`, not in the topology
builder. Add a runner to `experiments/registry.py` for CLI discovery. Reuse the
infrastructure and measurement functions rather than copying a complete runner.

## Results and preservation boundaries

Existing source-checkout defaults remain `results/iperf/` and `results/dash/`.
Runs contain `meta.json`, `events.log` and per-snapshot subdirectories.

| Scenario | Run-level outputs |
| --- | --- |
| RNP | `iperf_all.csv`, `ping_all.csv`, `ovs_flows_all.csv`, `ovs_ports_all.csv`; mode-specific service/baseline metrics |
| Diamond | `iperf_flow_all.csv`, `ping_flow_all.csv`, `ovs_flows_all.csv`, `ovs_ports_all.csv` |
| DASH capture | `packet_flow_all.csv`, OVS CSVs and hardware samples |

RNP retains raw iPerf parts, restart gaps and clipping to actual measurement
windows; ping excludes duplicate replies and samples outside those windows.
Diamond's CSV schema and per-window process behavior are intentionally separate.
The refactor does not standardize their timestamps, routing policy, durations,
rounding, zero filling, cleanup scope or output naming. Without `LFT_RESULTS`,
DASH server data now defaults to `results/dash/datadir` rather than recreating
the removed source directory.

DASH runner constructors still omit `iperf=False`. This pre-existing behavior
needs dedicated runtime investigation and Linux smoke validation before these
entries can be presented as verified first-run examples.

## Verification

```bash
python3 -m compileall -q onos_topologies
python3 -m onos_topologies.experiments.batch --help
```

These checks do not establish Docker/ONOS availability or real network behavior. Before merging, run each
supported scenario on the Linux test host, compare outputs against its prior
version, and exercise two consecutive RNP runs to check teardown and callbacks.


## Manual topology launcher

Edit `MODE`, `TRAFFIC` and `RESULTS_DIR` at the top of
`create_n_run.py`, then run from the repository root (or after package installation):

```bash
sudo python3 -m onos_topologies.create_n_run
```

Direct execution from `onos_topologies/` also works:

```bash
sudo python3 create_n_run.py
```

`MODE = None` opens the Diamond mode menu; set `MODE = "fwd"` to skip it.
`TRAFFIC = "dash"` selects DASH clients and servers; `"iperf"` selects iPerf.
Change the `CONFIG` import to select another network definition.
`RESULTS_DIR` is relative to the working directory.

You can also call the launcher directly from Python:

```python
from onos_topologies.create_n_run import main

main(mode="fwd", config=my_config)
```

The launcher configures telemetry and leaves containers running for manual use.
It does not run measurements or start the external deployer/supervisor services;
for modes requiring them, it prints their startup commands. Remove conflicting
containers from previous runs before launching; it performs no global cleanup.



The experiment entry points also support direct execution from their own directory
or by path from the repository root: `experiments/batch.py`, `experiments/rnp/run.py`,
`experiments/diamond/run.py`, `experiments/dash/run.py` and `experiments/dash/load_test.py`.
They resolve imports from the checkout; existing `python3 -m ...` commands still work.
