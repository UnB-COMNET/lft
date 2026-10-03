import json
from unittest.mock import patch

import pytest

from onos_topologies.runtime import state


def iface(name, up=True, ip=None):
    info = {"ifname": name, "flags": ["UP"] if up else [], "operstate": "UP" if up else "DOWN", "addr_info": []}
    if ip:
        info["addr_info"] = [{"family": "inet", "local": ip, "prefixlen": 24}]
    return info


LIVE = {
    "c1": {"state": "running", "image": "onosproject/onos:2.5.0", "kind": "controller", "role": None},
    "s0": {"state": "running", "image": "ovs", "kind": "switch", "role": None},
    "s1": {"state": "running", "image": "ovs", "kind": "switch", "role": None},
    "s10": {"state": "paused", "image": "ovs", "kind": "switch", "role": None},
    "cl0": {"state": "running", "image": "lft-dash-client", "kind": "host", "role": "client"},
}
IFACES = {
    "s0": {"s0s1": iface("s0s1"), "s0cl0": iface("s0cl0"), "eth0": iface("eth0")},
    "s1": {"s1s0": iface("s1s0"), "s1s10": iface("s1s10", up=False)},
    "s10": {"s10s1": iface("s10s1", up=False)},
    "cl0": {"cl0s0": iface("cl0s0", ip="192.168.0.2")},
}
TC = {"s0": {"s0s1": {"rate": 10.0, "delay": 5.0, "jitter": 1.0, "loss": 0.0}},
      "s1": {"s1s0": {"rate": 8.0, "delay": 5.0, "jitter": 1.0, "loss": 1.0}}}


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE", tmp_path / "topology.json")
    monkeypatch.setattr(state, "containers", lambda: LIVE)
    monkeypatch.setattr(state, "ifaces", lambda node: IFACES[node])
    monkeypatch.setattr(state.shaping, "read", lambda node: TC.get(node, {}))
    monkeypatch.setattr(state, "_bridge", lambda name: (f"of:{int(name[1:]) + 1:016x}", "SP"))
    monkeypatch.setattr(state, "_controller", lambda name: "tcp:172.17.0.2:6653")


def test_sync_reads_nodes_and_links_from_the_live_system(live):
    s = state.sync("diamond")
    assert s["name"] == "diamond" and s["controller"] == "tcp:172.17.0.2:6653"
    assert [n["id"] for n in s["nodes"]] == ["s0", "s1", "s10", "cl0"]   # the controller is not a node
    assert state.node(s, "s10")["off"] and not state.node(s, "s1")["off"]
    assert state.node(s, "cl0") == {"id": "cl0", "kind": "host", "role": "client", "sw": "s0", "ip": "192.168.0.2",
                                    "image": "lft-dash-client", "access": None, "paused": False}
    s0s1, s1s10 = s["links"]
    assert (s0s1["id"], s1s10["id"]) == ("s0-s1", "s1-s10")
    # the two ends differ: the lower rate and the higher loss win
    assert s0s1["now"] == {"rate": 8.0, "delay": 5.0, "jitter": 1.0, "loss": 1.0, "down": False}
    assert s1s10["now"]["down"]


def test_sync_keeps_the_base_a_link_was_first_seen_with(live):
    state.sync()
    TC["s0"]["s0s1"]["rate"] = TC["s1"]["s1s0"]["rate"] = 1.0
    try:
        link = state.link(state.sync(), "s1", "s0")
    finally:
        TC["s0"]["s0s1"]["rate"], TC["s1"]["s1s0"]["rate"] = 10.0, 8.0
    assert (link["base"]["rate"], link["now"]["rate"]) == (8.0, 1.0)


def test_containers_come_from_the_lft_labels():
    out = "s0\trunning\tovs:latest\tswitch\t\ncl0\tpaused\tlft-dash-client\thost\tclient\n"
    with patch.object(state, "_out", return_value=out) as run:
        found = state.containers()
    assert "label=lft=1" in run.call_args.args[0]
    assert found == {"s0": {"state": "running", "image": "ovs", "kind": "switch", "role": None},
                     "cl0": {"state": "paused", "image": "lft-dash-client", "kind": "host", "role": "client"}}


def test_peer_and_link_id_follow_the_veth_names():
    assert state.peer("s1", "s1s10", {"s1", "s10"}) == "s10"
    assert state.peer("s1", "eth0", {"s1", "s10"}) is None
    assert state.link_id("s10", "s2") == "s2-s10"


def test_clean_removes_only_the_labelled_containers(tmp_path):
    with patch.object(state, "containers", return_value={"s0": {}, "cl0": {}}), \
         patch.object(state.subprocess, "run") as run, patch.object(state, "Path", return_value=tmp_path):
        assert state.clean() == ["s0", "cl0"]
    assert run.call_args.args[0] == ["docker", "rm", "-f", "s0", "cl0"]


def test_state_file_is_written_whole(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE", tmp_path / "topology.json")
    state.save(state.empty())
    assert json.loads((tmp_path / "topology.json").read_text())["nodes"] == []
    assert not (tmp_path / "topology.tmp").exists()


def test_a_saved_link_no_switch_shows_is_gone(live, tmp_path):
    ghost = {"id": "s0-s10", "a": "s0", "b": "s10", "base": dict(state.DEFAULTS), "now": {**state.DEFAULTS, "down": False}}
    state.save({**state.empty(), "links": [ghost]})   # e.g. left by the previous topology
    assert "s0-s10" not in [l["id"] for l in state.sync()["links"]]
