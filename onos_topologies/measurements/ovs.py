import csv
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .csv_io import _merge_many_csvs


# Brief: Run a command and return its exit code, stdout and stderr
def _run(cmd: List[str]) -> Tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout or "", p.stderr or ""


# Brief: Query switch flows and ports; write parsed CSVs when parse_csv is enabled
def snapshot_ovs_state(
    switch_names: List[str],
    outdir: Path,
    of_version: str = "OpenFlow13",
    max_workers: int = 8,
    snapshot_idx: Optional[int] = None,
    parse_csv: bool = True, # keeps compatibility with your caller
) -> None:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    flows_out = outdir / "ovs_flows.csv"
    ports_out = outdir / "ovs_ports.csv"

    flows_lock = threading.Lock()
    ports_lock = threading.Lock()

    snap_val = "" if snapshot_idx is None else str(snapshot_idx)

    with flows_out.open("w", newline="", encoding="utf-8") as flows_f, ports_out.open("w", newline="", encoding="utf-8") as ports_f:
        flows_writer = csv.DictWriter(flows_f, fieldnames=OVS_FLOWS_FIELDS, extrasaction="ignore")
        ports_writer = csv.DictWriter(ports_f, fieldnames=OVS_PORTS_FIELDS, extrasaction="ignore")

        if parse_csv:
            flows_writer.writeheader()
            ports_writer.writeheader()

        def snap_one(sw: str) -> None:
            rc, flows_txt, err = _run(["docker", "exec", sw, "ovs-ofctl", "-O", of_version, "dump-flows", sw])
            if err:
                flows_txt += "\n" + err

            rc, ports_txt, err = _run(["docker", "exec", sw, "ovs-ofctl", "-O", of_version, "dump-ports", sw])
            if err:
                ports_txt += "\n" + err

            if not parse_csv:
                return

            # Write flows
            with flows_lock:
                for row in _iter_flows_rows(flows_txt):
                    out_row = {"snapshot": snap_val, "switch": sw, **row}
                    flows_writer.writerow(out_row)

            # Write ports
            with ports_lock:
                for row in _iter_ports_rows(ports_txt):
                    out_row = {"snapshot": snap_val, "switch": sw, **row}
                    ports_writer.writerow(out_row)

        with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(switch_names)))) as ex:
            futs = [ex.submit(snap_one, sw) for sw in switch_names]
            for f in as_completed(futs):
                f.result()


# Brief: Merges per-snapshot ovs_flows.csv and ovs_ports.csv into run-level files
def merge_all_snapshot_ovs_csvs(
    run_root: Path,
    delete_inputs: bool = False,
) -> Dict[str, Any]:
    run_root = Path(run_root)
    snaps_root = run_root / "snapshots"

    out_flows = run_root / "ovs_flows_all.csv"
    out_ports = run_root / "ovs_ports_all.csv"

    stats_flows = _merge_many_csvs(
        in_paths=sorted(snaps_root.glob("snapshot_*/ovs/ovs_flows.csv")),
        out_csv=out_flows,
        delete_inputs=delete_inputs,
    )
    stats_ports = _merge_many_csvs(
        in_paths=sorted(snaps_root.glob("snapshot_*/ovs/ovs_ports.csv")),
        out_csv=out_ports,
        delete_inputs=delete_inputs,
    )

    return {
        "flows": stats_flows,
        "ports": stats_ports,
    }


# Brief: Extracts the first capture group from a regex search
def _rx(text: str, pattern: str) -> str:
    m = re.search(pattern, text)
    return m.group(1) if m else ""


OVS_FLOWS_FIELDS: List[str] = [
    "snapshot",
    "switch",
    "cookie",
    "table",
    "priority",
    "duration_s",
    "n_packets",
    "n_bytes",
    "match_raw",
    "actions_raw",
    "flow_raw",
]

OVS_PORTS_FIELDS: List[str] = [
    "snapshot",
    "switch",
    "port_no",
    "rx_pkts",
    "rx_bytes",
    "rx_drop",
    "rx_errs",
    "tx_pkts",
    "tx_bytes",
    "tx_drop",
    "tx_errs",
]


# Brief: Parses ovs-ofctl dump-flows output and yields one dict per flow line
def _iter_flows_rows(dump_flows_text: str) -> Iterable[Dict[str, str]]:
    for line in dump_flows_text.splitlines():
        line = line.strip()
        if not line or line.startswith("OFPST_FLOW") or line.startswith("NXST_FLOW"):
            continue
        if "actions=" not in line:
            continue

        flow_raw = line
        left, actions_part = line.split("actions=", 1)
        actions_raw = actions_part.strip()

        cookie = _rx(left, r"cookie=([^, ]+)")
        duration_s = _rx(left, r"duration=([0-9.]+)s")
        table = _rx(left, r"table=([0-9]+)")
        n_packets = _rx(left, r"n_packets=([0-9]+)")
        n_bytes = _rx(left, r"n_bytes=([0-9]+)")
        priority = _rx(left, r"priority=([0-9]+)")

        if "priority=" in left:
            m = re.search(r"priority=[0-9]+,(.*)$", left)
            match_raw = m.group(1).strip().rstrip(",") if m else ""
        else:
            match_raw = left.strip().rstrip(",")

        yield {
            "cookie": cookie,
            "table": table,
            "priority": priority,
            "duration_s": duration_s,
            "n_packets": n_packets,
            "n_bytes": n_bytes,
            "match_raw": match_raw,
            "actions_raw": actions_raw,
            "flow_raw": flow_raw,
        }


# Brief: Parses ovs-ofctl dump-ports output and yields one dict per port
def _iter_ports_rows(dump_ports_text: str) -> Iterable[Dict[str, str]]:
    port_re = re.compile(r"^\s*port\s+(\d+):\s*(.*)$")
    rx_re = re.compile(r"rx\s+pkts=(\d+),\s*bytes=(\d+),\s*drop=(\d+),\s*errs=(\d+)")
    tx_re = re.compile(r"tx\s+pkts=(\d+),\s*bytes=(\d+),\s*drop=(\d+),\s*errs=(\d+)")

    current: Optional[Dict[str, str]] = None

    for line in dump_ports_text.splitlines():
        m = port_re.match(line)
        if m:
            if current:
                yield current

            port_no = m.group(1)
            current = {
                "port_no": port_no,
                "rx_pkts": "",
                "rx_bytes": "",
                "rx_drop": "",
                "rx_errs": "",
                "tx_pkts": "",
                "tx_bytes": "",
                "tx_drop": "",
                "tx_errs": "",
            }

            # Parse rx inline
            mrx = rx_re.search(m.group(2))
            if mrx:
                current.update(
                    {
                        "rx_pkts": mrx.group(1),
                        "rx_bytes": mrx.group(2),
                        "rx_drop": mrx.group(3),
                        "rx_errs": mrx.group(4),
                    }
                )
            continue

        if current:
            mrx = rx_re.search(line)
            if mrx:
                current.update(
                    {
                        "rx_pkts": mrx.group(1),
                        "rx_bytes": mrx.group(2),
                        "rx_drop": mrx.group(3),
                        "rx_errs": mrx.group(4),
                    }
                )

            mtx = tx_re.search(line)
            if mtx:
                current.update(
                    {
                        "tx_pkts": mtx.group(1),
                        "tx_bytes": mtx.group(2),
                        "tx_drop": mtx.group(3),
                        "tx_errs": mtx.group(4),
                    }
                )

    if current:
        yield current
