# Optional: runs the real `lft` against a running topology (root and Docker needed). Bring one up first,
# with ONOS reactive forwarding on so the hosts reach each other:
#   sudo lft topology create --preset diamond-video --detach
#   sudo LFT_INTEGRATION=1 python3 -m pytest tests/test_integration.py
import json
import os
import subprocess
import time

import pytest
import requests

pytestmark = pytest.mark.skipif(os.geteuid() != 0 or not os.environ.get("LFT_INTEGRATION"),
                                reason="needs root, Docker and a running topology (LFT_INTEGRATION=1)")
ONOS = os.environ.get("ONOS_URL", "http://127.0.0.1:8181/onos/v1")


def lft(*args):
    out = subprocess.run(["lft", *args, "--json"], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    return json.loads(out.stdout)


def sh(*args) -> str:
    return subprocess.run(args, capture_output=True, text=True).stdout


def onos(path: str) -> dict:
    return requests.get(ONOS + path, auth=("onos", "rocks"), timeout=5).json()


def until(check, timeout_s=30) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if check():
            return True
        time.sleep(1)
    return False


def test_link_shaping_reaches_tc_and_goes_back():
    link = next(l for l in lft("topology", "sync")["links"] if not l["now"]["down"])
    a, b = link["a"], link["b"]
    state = lft("link", "set", a, b, "--rate", "7mbit", "--delay", "33ms", "--loss", "1")["state"]
    assert "delay 33ms" in sh("ip", "netns", "exec", b, "tc", "qdisc", "show", "dev", f"{b}{a}")
    now = next(l for l in state["links"] if l["id"] == link["id"])["now"]
    assert (now["rate"], now["delay"], now["loss"]) == (7.0, 33.0, 1.0)
    assert next(l for l in lft("link", "down", a, b)["state"]["links"] if l["id"] == link["id"])["now"]["down"]
    back = next(l for l in lft("link", "reset", a, b)["state"]["links"] if l["id"] == link["id"])
    assert back["now"] == {**back["base"], "down": False}


def test_host_lifecycle_is_seen_by_docker_and_onos():
    state = lft("host", "add", "cl9", "--switch", "s1", "--ip", "192.168.0.99", "--image", "lft-dash-client")["state"]
    host = next(n for n in state["nodes"] if n["id"] == "cl9")
    assert (host["sw"], host["ip"], host["role"]) == ("s1", "192.168.0.99", "client")
    assert until(lambda: any("192.168.0.99" in h["ipAddresses"] for h in onos("/hosts")["hosts"]))
    assert next(n for n in lft("host", "pause", "cl9")["state"]["nodes"] if n["id"] == "cl9")["paused"]
    lft("host", "unpause", "cl9")
    moved = lft("host", "set", "cl9", "--switch", "s2", "--ip", "192.168.0.98")["state"]
    assert next(n for n in moved["nodes"] if n["id"] == "cl9")["sw"] == "s2"
    assert "cl9" not in [n["id"] for n in lft("host", "rm", "cl9")["state"]["nodes"]]


def test_a_switch_turned_off_leaves_onos_and_comes_back():
    lft("switch", "add", "s9", "--desc", "BA", "--dpid", "0000000000000009", "--link", "s3:rate=20mbit,delay=5ms")
    device = "of:0000000000000009"
    assert until(lambda: onos(f"/devices/{device}").get("available"))
    link = next(l for l in lft("switch", "stop", "s9")["state"]["links"] if l["id"] == "s3-s9")
    assert link["now"]["down"]
    assert until(lambda: not onos(f"/devices/{device}").get("available"))
    state = lft("switch", "start", "s9")["state"]
    assert not next(n for n in state["nodes"] if n["id"] == "s9")["off"]
    assert until(lambda: onos(f"/devices/{device}").get("available"))
    assert "s9" not in [n["id"] for n in lft("switch", "rm", "s9")["state"]["nodes"]]


def test_traffic_and_capture_write_their_files(tmp_path):
    capture = lft("capture", "start", "--iface", "s0s1", "--duration", "4", "--out", str(tmp_path / "s0s1.pcap"))
    session = lft("traffic", "start", "--client", "cl0", "--server", "ds0", "--rate", "5M", "--duration", "3",
                  "--out", str(tmp_path / "iperf"))
    assert until(lambda: lft("traffic", "ls")[-1]["status"] != "running", 20)
    assert until(lambda: next(c for c in lft("capture", "ls") if c["id"] == capture["id"])["status"] != "running", 20)
    rows = open(session["file"]).read()
    assert "Mbits/sec" in rows and (tmp_path / "s0s1.pcap").stat().st_size > 0
