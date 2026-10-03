from onos_topologies.topologies.configs.rnp import CONFIG_RNP

MODES = {
    "1": {
        "name": "cdn-qoe",
        "desc": "drift by KPI thresholds",
        "onos": "2.5.0",
        "disable_fwd": True,
        "apps": ("proxyarp",),
        "use_deployer": True,
        "supervisor_mode": "threshold",
    },
    "2": {
        "name": "baseline",
        "desc": "weighted Dijkstra, pinned paths",
        "onos": "2.5.0",
        "disable_fwd": True,
        "apps": ("proxyarp",),
        "use_deployer": False,
        "onos_weighted": True,
    },
    "3": {
        "name": "fwd",
        "desc": "random server, reactive fwd, no adaptation",
        "onos": "2.5.0",
        "disable_fwd": False,
        "apps": (),
        "use_deployer": False,
    },
    "4": {
        "name": "cdn-qoe-best-path",
        "desc": "drift when the path isn't the solver's",
        "onos": "2.5.0",
        "disable_fwd": True,
        "apps": ("proxyarp",),
        "use_deployer": True,
        "supervisor_mode": "best-path",
        "service": "cdn-qoe",
    },
    "5": {
        "name": "llm",
        "desc": "drift evaluated by the LLM",
        "onos": "2.5.0",
        "disable_fwd": True,
        "apps": ("proxyarp",),
        "use_deployer": True,
        "supervisor_mode": "llm",
        "service": "cdn-qoe",
    },
}
MODE_MENU = "".join(f"\n[{k}] - {c['name']} ({c['desc']})" for k, c in MODES.items())
LLM_URL = "http://gpu.mfcaetano.lan:8000"


POPS = CONFIG_RNP["pops"]
base_url_deployer = "http://127.0.0.1:5000/deploy"
base_url_metrics = "http://127.0.0.1:5000/metrics"
base_url_supervisor = "http://127.0.0.1:5151"
ROTATE_S = 60 # seconds per snapshot
N_SNAPSHOTS = 12

IPERF_NOTIFY_PORT = 5152
MIN_RESTART_REMAINING_S = 5
IPERF_CONNECT_TIMEOUT_S = 60
IPERF_DURATION_MARGIN_S = N_SNAPSHOTS * 60
INTENT_TIMEOUT_S = 900
PATH_WARMUP_TIMEOUT_S = 90
DEMAND_RATE = "35M"
SUPERVISOR_CRITICAL_MBIT = 15.0
SEED = 1
HARD_DEGRADE = {"delay_factor": 10.0, "rate_factor": 0.1}
# Every odd/even pair measures the restored and degraded conditions.
SNAPSHOT_ACTIONS = {snap_idx: HARD_DEGRADE for snap_idx in range(2, N_SNAPSHOTS + 1, 2)}
