import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


# Brief: Concatenates a list of CSVs (same schema) into one output file
def _merge_many_csvs(in_paths, out_csv: Path, delete_inputs: bool) -> Dict[str, Any]:
    in_paths = [Path(p) for p in in_paths if Path(p).exists()]
    if not in_paths:
        return {"files": 0, "rows": 0, "out": str(out_csv)}

    rows_written = 0
    files_used = 0

    with in_paths[0].open("r", newline="", encoding="utf-8") as f0:
        r0 = csv.DictReader(f0)
        fieldnames = list(r0.fieldnames or [])

    with out_csv.open("w", newline="", encoding="utf-8") as fo:
        w = csv.DictWriter(fo, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()

        for p in in_paths:
            files_used += 1
            with p.open("r", newline="", encoding="utf-8") as fi:
                reader = csv.DictReader(fi)
                for row in reader:
                    w.writerow(row)
                    rows_written += 1
            if delete_inputs:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass

    return {"files": files_used, "rows": rows_written, "out": str(out_csv)}


def _extract_snapshot_number_from_path(p: Path) -> int:
    # Expected: .../snapshots/snapshot_12/tcpdump/packet_flow.csv
    m = re.search(r"snapshot_(\d+)", str(p))
    return int(m.group(1)) if m else 10**9


# Brief: Merge all per-snapshot packet_flow.csv into a single CSV at run_root/out_csv_name
#  Returns stats dict:
#   - files: number of input CSVs found
#   - rows: total rows written (excluding header)
def merge_all_snapshot_csvs(
    run_root: Path,
    out_csv_name: str = "packet_flow_all.csv",
    glob_pattern: str = "snapshots/snapshot_*/tcpdump/packet_flow.csv",
    delete_inputs: bool = False,
) -> Dict[str, int]:
    run_root = Path(run_root)
    out_csv = run_root / out_csv_name

    inputs: List[Path] = sorted(
        run_root.glob(glob_pattern),
        key=_extract_snapshot_number_from_path,
    )

    if not inputs:
        return {"files": 0, "rows": 0}

    total_rows = 0
    expected_fields: Optional[List[str]] = None

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f_out:
        writer: Optional[csv.DictWriter] = None

        for in_path in inputs:
            with in_path.open("r", newline="", encoding="utf-8") as f_in:
                reader = csv.DictReader(f_in)
                if reader.fieldnames is None:
                    continue # empty file

                # initialize schema from the first file
                if expected_fields is None:
                    expected_fields = list(reader.fieldnames)
                    writer = csv.DictWriter(f_out, fieldnames=expected_fields)
                    writer.writeheader()

                # if schema differs, fail fast
                if list(reader.fieldnames) != expected_fields:
                    raise ValueError(
                        f"Schema mismatch in {in_path}. "
                        f"Expected {expected_fields}, got {reader.fieldnames}"
                    )

                # append rows
                assert writer is not None
                for row in reader:
                    # skip completely empty rows if any
                    if not row or all((v is None or str(v).strip() == "") for v in row.values()):
                        continue
                    writer.writerow(row)
                    total_rows += 1

            if delete_inputs:
                try:
                    in_path.unlink(missing_ok=True)
                except Exception:
                    pass

    return {"files": len(inputs), "rows": total_rows}
