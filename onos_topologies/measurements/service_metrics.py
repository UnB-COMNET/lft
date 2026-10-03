import csv
from pathlib import Path
from typing import List

DEPLOYER_METRICS_FIELDS = [
    "snapshot_idx",
    "msgs_deployer_to_controller",
    "msgs_controller_to_network",
    "msgs_observer_to_deployer",
    "msgs_deployer_to_observer",
    "solve_time_s",
    "deploy_time_s",
    "total_recalculate_time_s",
    "solve_time_s_count", "solve_time_s_sum",
    "deploy_time_s_count", "deploy_time_s_sum",
    "total_recalculate_time_s_count", "total_recalculate_time_s_sum",
]

# Supervisor drift-detection metrics
SUPERVISOR_METRICS_FIELDS = [
    "snapshot_idx",
    "msgs_onos_to_observer",
    "msgs_observer_to_deployer",
    "drift_detected",
    "detection_time_s",
    "degrade_ts",
]


# Baseline records route-application message counts and degradation-to-apply time locally
BASELINE_METRICS_FIELDS = [
    "snapshot_idx",
    "msgs_to_controller",
    "msgs_controller_to_network",
    "degrade_ts",
    "degrade_to_apply_s",
]


# Brief: Append one already-computed metrics dict as a CSV row under run_root
#  Writes the header on first call. For in-process metrics (no HTTP endpoint)
def append_metrics_row(run_root: Path, snapshot_idx: int, metrics: dict,
                       out_csv_name: str, fields: List[str]) -> None:
    out_csv = Path(run_root) / out_csv_name
    write_header = not out_csv.exists()
    with out_csv.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow({"snapshot_idx": snapshot_idx, **metrics})


# Brief: Collect service metrics and append a CSV row using the selected fields
# reset_after uses POST /metrics/reset; collection failures then raise
def append_deployer_metrics(run_root: Path, snapshot_idx: int, url: str,
                             out_csv_name: str = "deployer_metrics.csv", timeout: float = 5,
                             fields: List[str] = None, reset_after: bool = False) -> None:
    import requests
    fields = fields or DEPLOYER_METRICS_FIELDS
    try:
        if reset_after:
            reset_url = url.rstrip("/") + "/reset"
            response = requests.post(reset_url, timeout=timeout)
        else:
            response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        metrics = response.json()
    except Exception as e:
        if reset_after:
            raise RuntimeError(f"Metrics collection failed for {url}") from e
        print(f" [WARNING] Could not fetch metrics from {url}: {e}")
        return

    append_metrics_row(run_root, snapshot_idx, metrics, out_csv_name, fields)
