import os
import re
import subprocess
import time
from pathlib import Path

from onos_topologies.runtime import results


# Brief: Restores terminal formatting after Docker commands leave output misaligned
def restore_tty() -> None:
    if not os.isatty(1):
        return
    subprocess.run("stty sane", shell=True, stderr=subprocess.DEVNULL)


# Brief: Displays a countdown timer and pauses execution
def sleep_countdown(t=10) -> None:
    for i in range(t, 0, -1):
        print(f"  {i} seconds remaining ...", end="\r")
        time.sleep(1)
    print("                           ") # clears the line


# Brief: Prints an art banner for the experiment
def print_banner() -> None:
    art = r"""

      .oooooo.   oooooooooo.   ooooo     ooo 
     d8P'  `Y8b  `888'   `Y8b  `888b.     `8' 
    888           888      888  8 `88b.    8  
    888           888      888  8   `88b.  8  
    888           888      888  8     `88b.8  
    `88b    ooo   888     d88'  8       `888  
     `Y8bood8P'  o888bood8P'   o8o        `8  

    ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
    
             DASH TOPOLOGY EXPERIMENT
    """
    print(art)


# Brief: Appends a line to events.log, and its structured form to events.jsonl (onos_topologies.runtime.results):
# the runners' markers become typed events, any other line a "log" event
def append_event(rep_dir: Path, line: str) -> None:
    rep_dir.mkdir(parents=True, exist_ok=True)
    with (rep_dir / "events.log").open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")
    results.event(rep_dir, **_typed(rep_dir, line.strip()))


# SNAPSHOT_<n>_START/END -> window; CONTINUOUS_, EXPERIMENT_ and RUN_ START/STOP/END -> run; PHASE <ts> <label>
MARKERS = (
    (re.compile(r"^SNAPSHOT_(\d+)_(START|END)\b"), lambda m: {"type": "window", "index": int(m[1]), "state": m[2].lower()}),
    (re.compile(r"^(?:CONTINUOUS|EXPERIMENT|RUN)_(START|STOP|END)\b"), lambda m: {"type": "run", "state": "start" if m[1] == "START" else "end"}),
    (re.compile(r"^PHASE [\d.]+ (.+)"), lambda m: {"type": "phase", "name": m[1], "text": m[1]}),
)


def _typed(rep_dir: Path, line: str) -> dict:
    for pattern, typed in MARKERS:
        m = pattern.match(line)
        if m:
            fields = typed(m)
            if fields["type"] == "window" and fields["state"] == "end":  # what the window wrote
                found = sorted(rep_dir.glob(f"**/snapshot_{fields['index']}"))
                fields["files"] = results.files(rep_dir, str(found[0].relative_to(rep_dir))) if found else []
            return fields
    return {"type": "log", "text": line}


# Brief: A phase of the run (cleanup, onos, apps, topology, hosts, discovery, rein), written to the run
# that exported LFT_RESULTS; does nothing outside a runner (e.g. lft topology create)
def phase(name: str, text: str) -> None:
    if os.environ.get("LFT_RESULTS"):
        results.event(Path(os.environ["LFT_RESULTS"]), type="phase", name=name, text=text)


# Brief: Marks the end of a run in events.jsonl with the files it left at the top of its directory
def finish(rep_dir: Path, status: str = "done") -> None:
    results.event(rep_dir, type="files", files=results.files(rep_dir))
    results.event(rep_dir, type="run", state=status)
