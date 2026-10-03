# Brief: Where runs write (results/, or LFT_RESULTS_ROOT) and the events they leave there. A run is a
# directory with meta.json or events.log; its events.jsonl holds one JSON object per line,
# {"t": epoch, "type": ...}, which programs can follow while it runs:
#   run {state: start, end, done}, phase {name, text}, window {index, state, files},
#   links {index, of, states}, flow {id, state, ...}, event {id, kind, state, ...}, files {files}, log {text}

import json
import os
import time
from pathlib import Path

ROOT = Path(os.environ.get("LFT_RESULTS_ROOT", Path(__file__).resolve().parents[2] / "results"))


# Brief: Where an output path lands: absolute paths stay, relative ones go under the results root
# (a leading "results/" is accepted)
def path(value) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    return ROOT / (p.relative_to("results") if p.parts[:1] == ("results",) else p)


# Brief: Appends one event to <run_dir>/events.jsonl
def event(run_dir: Path, **fields) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(time.time(), 3), **fields}) + "\n")


# Brief: The files under run_dir (or one of its subdirectories), relative to run_dir
def files(run_dir: Path, under: str = "") -> list:
    base = run_dir / under if under else run_dir
    found = base.rglob("*") if under else base.glob("*")
    return sorted(str(p.relative_to(run_dir)) for p in found if p.is_file() and p.name not in ("events.log", "events.jsonl"))


# Brief: The runs, newest first, with their status (from events.jsonl) and number of windows; or the
# files of one run
# Params:
#   String run: A run id as listed (e.g. "iperf/diamond-first"), or None for all runs
# Return:
#   list of runs {id, dir, started, status, windows, files}, or of files {path, bytes, modified}
def ls(run: str = None) -> list:
    if run:
        root = (ROOT / run).resolve()
        if ROOT.resolve() not in root.parents or not root.is_dir():
            raise KeyError(f"no run {run} under {ROOT}")
        return [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "modified": p.stat().st_mtime}
                for p in sorted(root.rglob("*")) if p.is_file()]
    runs = []
    for root in {p.parent for pattern in ("*/*/meta.json", "*/*/events.log") for p in ROOT.glob(pattern)}:
        events = []
        if (root / "events.jsonl").exists():
            events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
        last = next((e["state"] for e in reversed(events) if e["type"] == "run"), None)
        meta = json.loads((root / "meta.json").read_text()) if (root / "meta.json").exists() else {}
        runs.append({"id": str(root.relative_to(ROOT)), "dir": str(root), "started": meta.get("start_ts") or root.stat().st_mtime,
                     "status": {"start": "running", "end": "collecting"}.get(last, last or "unknown"),
                     "windows": max((e["index"] for e in events if e["type"] == "window"), default=0),
                     "files": sum(1 for p in root.rglob("*") if p.is_file())})
    return sorted(runs, key=lambda r: -r["started"])
