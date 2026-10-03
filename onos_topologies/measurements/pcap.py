import csv
import io
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PCAP_FIELDS: List[str] = [
    "frame.time_epoch",
    "frame.len",
    "ip.src",
    "ip.dst",
    "ipv6.src",
    "ipv6.dst",
    "_ws.col.Protocol",
    "tcp.srcport",
    "tcp.dstport",
    "tcp.flags",
    "tcp.stream",
    "icmp.type",
    "icmp.code",
    "icmpv6.type",
    "icmpv6.code",
]


# Brief: Expected parsing:
# - "3%eth0"          -> snapshot_idx=3, interface="eth0"
# - "snapshot_3%eth0" -> snapshot_idx=3, interface="eth0"
def _parse_snapshot_iface_from_name(pcap_path: Path) -> Tuple[Optional[int], str]:
    stem = pcap_path.stem # no ".pcap"
    if "%" not in stem:
        return None, ""

    left, iface = stem.split("%", 1)
    m = re.search(r"(\d+)", left)
    snap = int(m.group(1)) if m else None
    return snap, iface

# Obs: Display Filter é um filtro de protocolo PÓS-CAPTURA. O BPF filter do tcpdump filtra em tempo de execução!!
def _tshark_cmd(pcap_path: Path, display_filter: Optional[str]) -> List[str]:
    cmd = ["tshark", "-r", str(pcap_path)]
    if display_filter:
        cmd += ["-Y", display_filter]

    cmd += [
        "-T", "fields",
        "-E", "header=y",
        "-E", "separator=,",
        "-E", "quote=d",
        "-E", "occurrence=f",
    ]
    for f in PCAP_FIELDS:
        cmd += ["-e", f]
    return cmd


# Brief: Convert PCAPs to one CSV with snapshot and interface IDs
# Return file and row counts; optionally delete source captures
def snapshot_pcaps_to_single_csv(
    tcpdump_dir: Path,
    out_csv: Path,
    display_filter: Optional[str] = None,
    delete_pcaps: bool = False,
) -> Dict[str, int]:
    tcpdump_dir = Path(tcpdump_dir)
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    pcaps = sorted(tcpdump_dir.glob("*.pcap"))
    total_rows = 0

    out_fields = ["snapshot_idx", "interface"] + PCAP_FIELDS

    with out_csv.open("w", newline="", encoding="utf-8") as f_out:
        w = csv.DictWriter(f_out, fieldnames=out_fields)
        w.writeheader()

        for pcap in pcaps:
            snap_idx, iface = _parse_snapshot_iface_from_name(pcap)

            # If parsing failed, still keep something
            snap_val = snap_idx if snap_idx is not None else ""

            cmd = _tshark_cmd(pcap, display_filter)
            proc = subprocess.run(cmd, capture_output=True, text=True)

            # only rely on stdout
            if not proc.stdout.strip():
                if delete_pcaps:
                    try:
                        pcap.unlink(missing_ok=True)
                    except Exception:
                        pass
                continue

            reader = csv.DictReader(io.StringIO(proc.stdout))
            for row in reader:
                out_row: Dict[str, str] = {
                    "snapshot_idx": str(snap_val),
                    "interface": iface,
                }
                for k in PCAP_FIELDS:
                    out_row[k] = row.get(k, "") if row else ""
                w.writerow(out_row)
                total_rows += 1

            if delete_pcaps:
                try:
                    pcap.unlink(missing_ok=True)
                except Exception:
                    pass

    return {"pcaps": len(pcaps), "rows": total_rows}
