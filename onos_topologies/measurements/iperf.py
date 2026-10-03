import copy
import csv
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

IPERF_FIELDS = ["snapshot_idx", "client", "event_time", "interval_start", "interval_end", "seconds", "bytes", "bits_per_second", "retransmits"]

IPERF_ALL_FIELDS = [
    "snapshot_idx", "client", "event_time",
    "interval_start", "interval_end", "seconds",
    "bytes", "bits_per_second", "retransmits", "rtt_ms",
]


# Brief: Export per-client snapshot JSONs to CSV, including mean stream RTT in ms
# event_time uses the snapshot start plus interval offset; falls back to file mtime
def merge_all_iperf_jsons_to_csv(
    run_root: Path,
    out_csv_name: str = "iperf_all.csv",
    glob_pattern: str = "snapshots/snapshot_*/iperf/*.json",
    snap_start_times: Optional[Dict[int, float]] = None,
) -> Dict[str, Any]:
    run_root = Path(run_root)
    out_csv  = run_root / out_csv_name
    jsons    = sorted(run_root.glob(glob_pattern))
    snap_start_times = snap_start_times or {}

    total_rows = 0
    with out_csv.open("w", newline="", encoding="utf-8") as f_out:
        w = csv.DictWriter(f_out, fieldnames=IPERF_ALL_FIELDS)
        w.writeheader()

        for jf in jsons:
            snap_idx, client = _parse_client_snapshot_from_name(jf)
            if not client:
                client = jf.stem
            snap_val = snap_idx if snap_idx is not None else ""
            base_ts  = snap_start_times.get(snap_idx, os.path.getmtime(jf))

            try:
                text = jf.read_text(encoding="utf-8", errors="ignore").strip()
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    text = text.rstrip().rstrip(",")
                    if '"intervals"' in text:
                        text += "]}"
                    data = json.loads(text)
            except Exception as e:
                print(f" [WARNING] iperf_all: skipping {jf.name}: {e}")
                continue

            for interval in data.get("intervals", []):
                s       = interval.get("sum", {})
                streams = interval.get("streams", [])
                rtts    = [st["rtt"] for st in streams if "rtt" in st]
                rtt_ms  = round((sum(rtts) / len(rtts)) / 1000, 3) if rtts else ""
                i_start = s.get("start", 0.0)
                i_end   = s.get("end",   0.0)
                w.writerow({
                    "snapshot_idx":    str(snap_val),
                    "client":          str(client),
                    "event_time":      str(base_ts + i_start),
                    "interval_start":  str(round(i_start, 3)),
                    "interval_end":    str(round(i_end,   3)),
                    "seconds":         str(round(i_end - i_start, 3)),
                    "bytes":           str(s.get("bytes", 0)),
                    "bits_per_second": str(round(s.get("bits_per_second", 0.0), 2)),
                    "retransmits":     str(s.get("retransmits", "")) if s.get("retransmits", "") != "" else "",
                    "rtt_ms":          str(rtt_ms) if rtt_ms != "" else "",
                })
                total_rows += 1

    return {"files": len(jsons), "rows": total_rows, "out": str(out_csv)}


# Brief: Expected filename: <client>%<snapshot_idx>.<ext>
#  Example: cl0%3.txt
def _parse_client_snapshot_from_name(p: Path) -> Tuple[Optional[int], str]:
    stem = p.stem # cl0%3
    if "%" not in stem:
        return None, ""
    client, snap = stem.split("%", 1)
    try:
        return int(snap), client
    except Exception:
        return None, client


# Brief: Create zero-throughput iPerf intervals for a missing measurement period
def make_zero_iperf_json(start_ts: float, duration_s: float) -> Dict[str, Any]:
    n = max(1, round(duration_s))
    intervals = []
    for i in range(n):
        intervals.append({
            "streams": [{
                "socket": 5, "start": float(i), "end": float(i + 1),
                "seconds": 1.0, "bytes": 0, "bits_per_second": 0.0,
                "retransmits": 0, "snd_cwnd": 0, "snd_mss": 0,
                "rtt": 0, "rttvar": 0, "pmtu": 0,
                "omitted": False, "sender": True,
            }],
            "sum": {
                "start": float(i), "end": float(i + 1), "seconds": 1.0,
                "bytes": 0, "bits_per_second": 0.0,
                "retransmits": 0, "omitted": False, "sender": True,
            },
        })
    return {
        "start": {
            "connected": [],
            "version": "iperf 3.0 (zero-fill)",
            "system_info": "",
            "timestamp": {
                "time": time.strftime('%a, %d %b %Y %H:%M:%S %Z', time.localtime(start_ts)),
                "timesecs": int(start_ts),
            },
            "test_start": {
                "protocol": "TCP", "num_streams": 1, "blksize": 131072,
                "omit": 0, "duration": n, "bytes": 0, "blocks": 0,
                "reverse": 0, "tos": 0, "interval": 1,
            },
        },
        "intervals": intervals,
        "end": {
            "streams": [{"sender": {
                "socket": 5, "start": 0.0, "end": float(n), "seconds": float(n),
                "bytes": 0, "bits_per_second": 0.0, "retransmits": 0,
                "omitted": False, "sender": True,
            }}],
            "sum_sent": {
                "start": 0.0, "end": float(n), "seconds": float(n),
                "bytes": 0, "bits_per_second": 0.0,
                "retransmits": 0, "omitted": False, "sender": True,
            },
            "sum_received": {
                "start": 0.0, "end": float(n), "seconds": float(n),
                "bytes": 0, "bits_per_second": 0.0,
                "omitted": False, "sender": False,
            },
            "cpu_utilization_percent": {
                "host_total": 0.0, "host_user": 0.0, "host_system": 0.0,
                "remote_total": 0.0, "remote_user": 0.0, "remote_system": 0.0,
            },
            "sender_tcp_congestion": "cubic",
        },
    }


# Brief: Preserve raw input and repair truncated JSON; zero-fill only without valid intervals
def zero_fill_if_empty(part_path: Path, anchor_ts: float, client_name: str) -> None:
    existing = None
    if part_path.exists():
        raw_path = part_path.with_suffix(".raw")
        if not raw_path.exists():
            raw_path.write_bytes(part_path.read_bytes())
    try:
        text = part_path.read_text(encoding="utf-8", errors="ignore")
        try:
            existing = json.loads(text)
        except json.JSONDecodeError:
            repaired = text.rstrip().rstrip(",")
            if '"intervals"' in repaired:
                repaired += "]}"
            existing = json.loads(repaired) # still invalid -> falls to except below
            part_path.write_text(json.dumps(existing), encoding="utf-8")
    except Exception:
        existing = None

    if existing and existing.get("intervals"):
        return

    gap_s = time.time() - anchor_ts
    if gap_s <= 0:
        return
    print(f" [IPERF] {client_name}: zero-filling {gap_s:.0f}s gap in {part_path.name}")
    try:
        zero = make_zero_iperf_json(anchor_ts, gap_s)
        with open(part_path, "w", encoding="utf-8") as f:
            json.dump(zero, f)
    except Exception as ze:
        print(f" [WARN] zero-fill failed for {part_path.name}: {ze}")


# Brief: Stitch iPerf parts using session timestamps, preserving restart gaps and raw files
def stitch_iperf_parts(part_paths: List[Path], out_path: Path) -> None:
    combined_intervals = []
    first_start_block = None

    for pp in part_paths:
        try:
            text = pp.read_text(encoding="utf-8", errors="ignore").strip()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                text = text.rstrip().rstrip(",")
                if '"intervals"' in text:
                    text += "]}"
                data = json.loads(text)
        except Exception as e:
            print(f" [WARNING] stitch_iperf_parts: skipping {pp.name}: {e}")
            continue

        if first_start_block is None:
            first_start_block = data.get("start")

        offset = (float(data["start"]["timestamp"]["timesecs"])
                  - float(first_start_block["timestamp"]["timesecs"]))
        for interval in data.get("intervals", []):
            s = interval.get("sum", {})
            i_start = s.get("start", 0.0)
            i_end   = s.get("end",   0.0)
            s["start"] = round(i_start + offset, 6)
            s["end"]   = round(i_end   + offset, 6)
            for st in interval.get("streams", []):
                if "start" in st:
                    st["start"] = round(st["start"] + offset, 6)
                if "end" in st:
                    st["end"] = round(st["end"] + offset, 6)
            combined_intervals.append(interval)


    out = {"intervals": combined_intervals}
    if first_start_block is not None:
        out["start"] = first_start_block

    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


# Brief: Clip continuous iPerf intervals to actual snapshot windows
# Write snapshots/snapshot_{idx}/iperf/{client}%{idx}.json
def slice_iperf_json_to_snapshots(
    run_root: Path,
    client_name: str,
    continuous_json_path: Path,
    run_t0: float,
    snap_start_times: Dict[int, float],
    delete_input: bool = False,
    max_end_ts: Optional[float] = None,
    snap_end_times: Optional[Dict[int, float]] = None,
) -> Dict[str, Any]:
    run_root = Path(run_root)
    continuous_json_path = Path(continuous_json_path)

    if not snap_start_times:
        return {"snapshots": 0, "intervals": 0}

    try:
        text = continuous_json_path.read_text(encoding="utf-8", errors="ignore").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            text = text.rstrip().rstrip(",")
            if '"intervals"' in text:
                text += "]}"
            data = json.loads(text)
    except Exception as e:
        print(f" [WARNING] slice_iperf_json_to_snapshots: could not parse {continuous_json_path.name}: {e}")
        data = {"intervals": []}

    start_block = data.get("start")
    session_t0 = float((start_block or {}).get("timestamp", {}).get("timesecs", run_t0))
    boundaries = sorted(snap_start_times.items(), key=lambda item: item[1])
    buckets: Dict[int, list] = {idx: [] for idx in snap_start_times}

    dropped = 0
    for interval in data.get("intervals", []):
        summary = interval.get("sum", {}) or {}
        abs_start = session_t0 + summary.get("start", 0.0)
        abs_end = session_t0 + summary.get("end", 0.0)
        assigned = False
        for pos, (idx, window_start) in enumerate(boundaries):
            next_start = boundaries[pos + 1][1] if pos + 1 < len(boundaries) else float("inf")
            window_end = min((snap_end_times or {}).get(idx, next_start),
                             max_end_ts if max_end_ts is not None else float("inf"))
            left, right = max(abs_start, window_start), min(abs_end, window_end)
            if right <= left:
                continue
            clipped = copy.deepcopy(interval)
            for sample in [clipped.get("sum", {})] + clipped.get("streams", []):
                sample_start = session_t0 + sample.get("start", summary.get("start", 0.0))
                sample_end = session_t0 + sample.get("end", summary.get("end", 0.0))
                start, end = max(sample_start, left), min(sample_end, right)
                duration = max(0.0, end - start)
                fraction = duration / (sample_end - sample_start) if sample_end > sample_start else 0.0
                sample.update(start=round(max(start, left) - window_start, 6),
                              end=round(max(start, end) - window_start, 6), seconds=duration)
                # Partial seconds estimate volume at the interval's average rate.
                if fraction < 1:
                    if "bytes" in sample:
                        sample["bytes"] = round(sample["bytes"] * fraction)
                    sample.pop("retransmits", None) # events cannot be apportioned in time
            buckets[idx].append(clipped)
            assigned = True
        if not assigned:
            dropped += 1

    written, total_intervals = 0, 0
    for idx, intervals in buckets.items():
        out_dir = run_root / "snapshots" / f"snapshot_{idx}" / "iperf"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{client_name}%{idx}.json"
        out_data: Dict[str, Any] = {"intervals": intervals}
        if start_block is not None:
            out_data["start"] = start_block
        out_path.write_text(json.dumps(out_data, ensure_ascii=False), encoding="utf-8")
        written += 1
        total_intervals += len(intervals)

    if delete_input:
        try:
            continuous_json_path.unlink()
        except Exception:
            pass

    return {"snapshots": written, "intervals": total_intervals, "dropped": dropped}


# Brief: Export snapshot iPerf JSON intervals to CSV with client and snapshot IDs
def snapshot_iperf_jsons_to_single_csv(
    iperf_dir: Path,
    out_csv: Path,
    snap_start_ts: Optional[float] = None,
) -> Dict[str, int]:
    iperf_dir = Path(iperf_dir)
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    jsons = sorted(iperf_dir.glob("*.json"))

    total_rows = 0

    with out_csv.open("w", newline="", encoding="utf-8") as f_out:
        w = csv.DictWriter(f_out, fieldnames=IPERF_FIELDS)
        w.writeheader()

        for jf in jsons:
            snap_idx, client = _parse_client_snapshot_from_name(jf)
            snap_val = snap_idx if snap_idx is not None else ""

            try:
                data = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
            except Exception as e:
                print(f" [WARNING] Failed to parse {jf.name}: {e}")
                continue

            if "intervals" not in data:
                print(f" [WARNING] iperf output sem intervalos ({jf.name})")
                continue

            base_ts = snap_start_ts if snap_start_ts is not None else os.path.getmtime(jf)

            for interval in data["intervals"]:
                s       = interval.get("sum", {})
                i_start = s.get("start", 0.0)
                i_end   = s.get("end", 0.0)
                retr    = s.get("retransmits", "")
                w.writerow({
                    "snapshot_idx":    str(snap_val),
                    "client":          str(client),
                    "event_time":      str(base_ts + i_start),
                    "interval_start":  str(i_start),
                    "interval_end":    str(i_end),
                    "seconds":         str(round(i_end - i_start, 3)),
                    "bytes":           str(s.get("bytes", 0)),
                    "bits_per_second": str(s.get("bits_per_second", 0.0)),
                    "retransmits":     str(retr) if retr != "" else "",
                })
                total_rows += 1

    return {"jsons": len(jsons), "rows": total_rows}
