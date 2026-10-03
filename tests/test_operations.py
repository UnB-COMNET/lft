from unittest.mock import MagicMock, patch

import pytest

from onos_topologies.runtime import TopologyError, hosts, links, state, switches

SHAPE = {"rate": 10.0, "delay": 5.0, "jitter": 1.0, "loss": 0.0}
SAVED = {
    "name": "t", "controller": "tcp:172.17.0.2:6653", "defaults": dict(state.DEFAULTS), "updated": 0,
    "nodes": [{"id": "s0", "kind": "switch", "dpid": "of:1", "desc": "SP", "off": False},
              {"id": "s1", "kind": "switch", "dpid": "of:2", "desc": "RJ", "off": False},
              {"id": "cl0", "kind": "host", "role": "client", "sw": "s0", "ip": "192.168.0.2", "image": "img",
               "access": None, "paused": False}],
    "links": [{"id": "s0-s1", "a": "s0", "b": "s1", "base": SHAPE, "now": {**SHAPE, "rate": 2.0, "down": False}}],
}
LIVE = {"s0": {"state": "running", "kind": "switch"}, "s1": {"state": "running", "kind": "switch"},
        "cl0": {"state": "running", "kind": "host"}}


@pytest.fixture(autouse=True)
def topology(monkeypatch):
    monkeypatch.setattr(state, "load", lambda: SAVED)
    monkeypatch.setattr(state, "containers", lambda: LIVE)


def quiet(step, steps, title):
    pass


def test_link_shape_keeps_the_values_left_out():
    with patch.object(links.shaping, "apply") as apply:
        links.shape("s1", "s0", delay=40, report=quiet)
    assert [c.args[:2] for c in apply.call_args_list] == [("s1", "s1s0"), ("s0", "s0s1")]
    assert apply.call_args.args[2] == {"rate": 2.0, "delay": 40, "jitter": 1.0, "loss": 0.0}


def test_link_reset_goes_back_to_the_base_and_up():
    with patch.object(links.shaping, "apply") as apply, patch.object(links.subprocess, "run") as run:
        links.reset("s0", "s1", report=quiet)
    assert apply.call_args.args[2] == SHAPE
    assert [c.args[0][-1] for c in run.call_args_list] == ["up", "up"]


def test_unknown_link_is_refused():
    with pytest.raises(TopologyError, match="no link"):
        links.down("s0", "s9", report=quiet)


# A client is the experiments' idle IperfClient, a server a Host running its image's command
@pytest.mark.parametrize("server, made, role", [(False, "IperfClient", "client"), (True, "Host", "server")])
def test_host_add_uses_what_the_topologies_are_built_with(server, made, role):
    host = MagicMock()
    with patch.object(hosts, made, return_value=host), patch.object(hosts, "Switch") as sw, patch.object(hosts, "run") as run:
        hosts.add("cl5", "s1", "192.168.0.5", "lft-dash-client", server, report=quiet)
    assert host.role == role
    host.instantiate.assert_called_once_with(dockerImage="lft-dash-client")
    host.connect.assert_called_once_with(sw.return_value, "cl5s1", "s1cl5")
    host.setIp.assert_called_once_with("192.168.0.5", 24, "cl5s1")
    assert run.call_args.args == (host, "ping -c 1 -W 1 192.168.0.254")   # announces it to the controller


@pytest.mark.parametrize("name, switch, ip, error", [
    ("cl0", "s1", "192.168.0.9", "already exists"),
    ("cl5", "s7", "192.168.0.9", "not a running switch"),
    ("cl5", "s1", "192.168.0.2", "already in use"),
    ("cl5", "s1", "192.168.0", "not an address"),
])
def test_host_add_refuses_bad_requests(name, switch, ip, error):
    with pytest.raises(TopologyError, match=error):
        hosts.add(name, switch, ip, "img", report=quiet)


def test_switch_stop_disconnects_downs_and_pauses():
    ifaces = {"s0s1": {}, "s0cl0": {}, "eth0": {}}
    with patch.object(state, "ifaces", return_value=ifaces), patch.object(switches.subprocess, "run") as run, \
         patch.object(switches, "run") as inside, patch.object(switches, "Switch"):
        switches.stop("s0", report=quiet)
    assert inside.call_args.args[1] == "ovs-vsctl del-controller s0" and inside.call_args.kwargs == {"check": True}
    commands = [" ".join(c.args[0]) for c in run.call_args_list]
    assert set(commands[:-1]) == {"ip -n s0 link set s0s1 down", "ip -n s1 link set s1s0 down",
                                   "ip -n s0 link set s0cl0 down", "ip -n cl0 link set cl0s0 down"}
    assert commands[-1] == "docker pause s0"


def test_switch_add_links_and_shapes_both_ends():
    sw = MagicMock()
    with patch.object(switches, "Switch", return_value=sw), patch.object(switches.shaping, "apply") as apply:
        switches.add("s2", "BA", [("s1", SHAPE)], report=quiet)
    assert sw.instantiate.call_args.kwargs == {"networkMode": "bridge", "datapath_id": None, "sw_desc": "BA"}
    sw.setController.assert_called_once_with("172.17.0.2", 6653)
    assert sw.connect.call_args.args[1:] == ("s2s1", "s1s2")
    assert [c.args[:2] for c in apply.call_args_list] == [("s2", "s2s1"), ("s1", "s1s2")]


def test_switch_rm_needs_with_hosts_when_hosts_hang_from_it():
    with pytest.raises(TopologyError, match="cl0"):
        switches.rm("s0", report=quiet)
