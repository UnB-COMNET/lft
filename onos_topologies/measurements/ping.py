import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .iperf import _parse_client_snapshot_from_name

PING_FIELDS = [
    "snapshot_idx",
    "client",
    "timestamp",
    "bytes",
    "target_ip",
    "icmp_seq",
    "ttl",
    "time_ms",
]

# Brief: Parses standard ping and ping -D (timestamped) output lines
# Example 1: 64 bytes from 192.168.0.1: icmp_seq=1 ttl=64 time=10.5 ms
# Example 2: [1708726543.123456] 64 bytes from 192.168.0.1: icmp_seq=2 ttl=64 time=11.2 ms
_PING_RE = re.compile(
    r"^(?:\[([\d\.]+)\]\s+)?(\d+)\s+bytes\s+from\s+([a-fA-F0-9\.:]+):\s+icmp_seq=(\d+)\s+ttl=(\d+)\s+time=([\d\.]+)\s*ms"
)

# Brief: Export ping replies to CSV with client and snapshot IDs
# Exclude duplicate replies and samples outside supplied measurement windows
def snapshot_pings_to_single_csv(
    ping_dir: Path,
    out_csv: Path,
    snap_boundaries: Optional[List[Tuple[int, float]]] = None,
    snap_end_times: Optional[Dict[int, float]] = None,
) -> Dict[str, int]:
    ping_dir = Path(ping_dir)
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    txt_files = sorted(ping_dir.glob("*.txt"))
    total_rows = 0
    dropped = 0

    with out_csv.open("w", newline="", encoding="utf-8") as f_out:
        w = csv.DictWriter(f_out, fieldnames=PING_FIELDS)
        w.writeheader()

        for txt in txt_files:
            snap_idx, client = _parse_client_snapshot_from_name(txt)
            snap_val = snap_idx if snap_idx is not None else ""

            # Fallback if filename is just "client.txt" without %
            if not client:
                client = txt.stem

            try:
                with txt.open("r", encoding="utf-8", errors="ignore") as f_in:
                    for line in f_in:
                        line = line.strip()
                        # "(DUP!)" marks an echo reply the kernel already saw for
                        # this seq -- the same probe answered again because the
                        # network duplicated it (reactive forwarding flooding a
                        # cyclic topology). Not an independent RTT sample, and
                        # _PING_RE isn't anchored so it would otherwise match:
                        # measured 15360 duplicates against 1098 real replies,
                        # dragging a client's median RTT from 53ms to 2664ms.
                        if line.endswith("(DUP!)"):
                            continue
                        m = _PING_RE.match(line)
                        if m:
                            if snap_val == "" and snap_boundaries and m.group(1):
                                ts = float(m.group(1))
                                for idx, start_ts in reversed(snap_boundaries):
                                    if ts >= start_ts:
                                        # Past a window's close the run is busy
                                        # restoring links and rerouting, so the
                                        # sample describes no measured condition.
                                        if snap_end_times and idx in snap_end_times \
                                                and ts >= snap_end_times[idx]:
                                            snap_val_line = ""
                                        else:
                                            snap_val_line = str(idx)
                                        break
                                else:
                                    snap_val_line = "" # before the first window
                                # Ping runs free while the orchestrator works
                                # between windows, so ~10-18% of its samples land
                                # in those gaps. slice_iperf_json_to_snapshots
                                # already drops the equivalent intervals; keeping
                                # them here left the two series inconsistent and
                                # put unlabelled points on every RTT chart.
                                if not snap_val_line:
                                    dropped += 1
                                    continue
                            else:
                                snap_val_line = str(snap_val)

                            row = {
                                "snapshot_idx": snap_val_line,
                                "client":       str(client),
                                "timestamp":    m.group(1) if m.group(1) else "",
                                "bytes":        m.group(2),
                                "target_ip":    m.group(3),
                                "icmp_seq":     m.group(4),
                                "ttl":          m.group(5),
                                "time_ms":      m.group(6),
                            }
                            w.writerow(row)
                            total_rows += 1
            except Exception:
                continue

    return {"files": len(txt_files), "rows": total_rows, "dropped": dropped}
