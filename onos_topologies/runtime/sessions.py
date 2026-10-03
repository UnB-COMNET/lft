# Brief: Background sessions (traffic, captures): processes that outlive the `lft` call that starts
# them. Each one keeps its meta in /var/lib/lft/<kind>/<id>/meta.json (what it runs, its pids, where
# its output goes), so a later call, from another process, finds it and stops it.

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from onos_topologies.runtime import state


def home(kind: str) -> Path:
    return state.STATE.parent / kind


# Brief: The next free id of a kind: t1, t2... for traffic, c1, c2... for captures
def new_id(kind: str, prefix: str) -> str:
    used = [int(p.name[len(prefix):]) for p in home(kind).glob(f"{prefix}*") if p.name[len(prefix):].isdigit()]
    return f"{prefix}{max(used, default=0) + 1}"


# Brief: Starts a command in its own process group, detached from lft, its output going to a file
# Return:
#   int pid (also the process group id)
def spawn(argv: list, log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        return subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True).pid


def alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1][0] not in "ZX"
    except (OSError, IndexError):   # gone, or going while it is read
        return False


def save(kind: str, meta: dict) -> dict:
    path = home(kind) / meta["id"] / "meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=1))
    return meta


# Brief: A session's meta with its status: running while any of its processes is, else how it ended
def get(kind: str, sid: str) -> dict:
    path = home(kind) / sid / "meta.json"
    if not path.exists():
        raise KeyError(f"{sid} not found")
    meta = json.loads(path.read_text())
    running = any(alive(pid) for pid in meta["pids"])
    return {**meta, "status": "running" if running else meta.get("status", "done")}


def ls(kind: str) -> list:
    return [get(kind, p.parent.name) for p in sorted(home(kind).glob("*/meta.json"), key=lambda p: p.stat().st_mtime)]


# Brief: Stops a session: SIGINT to each process group (tcpdump and iperf3 then write what they have),
# SIGKILL to whatever is left after grace_s
def stop(kind: str, sid: str, grace_s: float = 5) -> dict:
    meta = get(kind, sid)
    if meta["status"] != "running":
        return meta
    for sig in (signal.SIGINT, signal.SIGKILL):
        for pid in meta["pids"]:
            try:
                os.killpg(pid, sig)
            except ProcessLookupError:
                pass
        deadline = time.time() + grace_s
        while time.time() < deadline and any(alive(pid) for pid in meta["pids"]):
            time.sleep(0.2)
        if not any(alive(pid) for pid in meta["pids"]):
            break
    return save(kind, {**meta, "status": "stopped", "stopped": time.time()})
