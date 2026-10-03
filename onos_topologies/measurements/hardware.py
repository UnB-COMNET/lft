import csv
import re
import time
from pathlib import Path
from typing import List, Tuple

HW_FIELDS = [
    "snapshot_idx",
    "ts_epoch",
    "cpu_pct",
    "ram_used_bytes",
    "disk_read_bytes",
    "disk_write_bytes",
]

_DISK_RE = re.compile(r"^(sd[a-z]+\d*|vd[a-z]+\d*|nvme\d+n\d+p?\d*)$")


def _cpu_stat() -> Tuple[int, int]:
    with open("/proc/stat", "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("cpu "):
                v = [int(x) for x in line.split()[1:]]
                idle = (v[3] if len(v) > 3 else 0) + (v[4] if len(v) > 4 else 0)
                total = sum(v[:8]) if len(v) >= 8 else sum(v)
                return idle, total
    return 0, 0


def _ram_used_bytes() -> int:
    mem_total = 0
    mem_avail = 0
    with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                mem_avail = int(line.split()[1]) * 1024
    return max(0, mem_total - mem_avail)


def _disk_rw_bytes() -> Tuple[int, int]:
    r_sec = 0
    w_sec = 0
    with open("/proc/diskstats", "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            p = line.split()
            if len(p) < 14:
                continue
            name = p[2]
            if not _DISK_RE.match(name):
                continue
            r_sec += int(p[5])
            w_sec += int(p[9])
    return r_sec * 512, w_sec * 512


def hw_state() -> Tuple[int, int, int, int]:
    idle, total = _cpu_stat()
    dr, dw = _disk_rw_bytes()
    return idle, total, dr, dw


def hw_sample(csv_path: Path, snapshot_idx: int, state: List[int]) -> None:
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    idle0, total0, dr0, dw0 = state
    idle1, total1 = _cpu_stat()
    dr1, dw1 = _disk_rw_bytes()

    idle_d = max(0, idle1 - idle0)
    total_d = max(0, total1 - total0)
    cpu_pct = (100.0 * (1.0 - (idle_d / total_d))) if total_d > 0 else 0.0

    row = {
        "snapshot_idx": str(snapshot_idx),
        "ts_epoch": str(time.time()),
        "cpu_pct": f"{cpu_pct:.3f}",
        "ram_used_bytes": str(_ram_used_bytes()),
        "disk_read_bytes": str(max(0, dr1 - dr0)),
        "disk_write_bytes": str(max(0, dw1 - dw0)),
    }

    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HW_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow(row)

    # update state
    state[0], state[1], state[2], state[3] = idle1, total1, dr1, dw1
