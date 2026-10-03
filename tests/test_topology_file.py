from onos_topologies.topologies import topology_file

SHAPE = {"rate": 35.0, "delay": 10.0, "jitter": 1.0, "loss": 0.0}
STATE = {
    "name": "lab", "controller": "tcp:172.17.0.2:6653", "defaults": SHAPE,
    "nodes": [{"id": "s0", "kind": "switch", "dpid": "of:1", "desc": "ES", "off": False},
              {"id": "s1", "kind": "switch", "dpid": "of:2", "desc": "SP", "off": False},
              {"id": "ds0", "kind": "host", "role": None, "sw": "s0", "ip": "192.168.0.1", "image": "lft-dash-video",
               "access": None, "paused": False},
              {"id": "cl0", "kind": "host", "role": "client", "sw": "s1", "ip": "192.168.0.2", "image": "lft-dash-client",
               "access": None, "paused": False}],
    "links": [{"id": "s0-s1", "a": "s0", "b": "s1", "base": {**SHAPE, "rate": 10.0},
               "now": {**SHAPE, "rate": 10.0, "loss": 1.0, "down": False}}],
}


def test_export_loads_back(tmp_path):
    path = tmp_path / "lab_topology.py"
    path.write_text(topology_file.export(STATE))
    module, config = topology_file.load(path)
    assert config["pops"] == (("PoP-ES", 0, 1), ("PoP-SP", 1, 0))
    assert config["adjacency_matrix"] == ((0, 1), (1, 0))
    assert config["throughput_matrix"][0][1] == "10mbit" and config["loss_matrix"][1][0] == "1%"
    assert "rtt_matrix" not in config and config["throughput"] == "35mbit"
    assert module.HOSTS == (("ds0", "PoP-ES", "server", "lft-dash-video", "192.168.0.1"),
                            ("cl0", "PoP-SP", "client", "lft-dash-client", "192.168.0.2"))
    assert not hasattr(module, "DOWN_LINKS")


def test_a_down_link_is_exported_with_its_base():
    down = {**STATE, "links": [{**STATE["links"][0], "now": {**SHAPE, "rate": 1.0, "down": True}}]}
    text = topology_file.export(down)
    assert 'DOWN_LINKS = ("s0-s1",)' in text and '"10mbit"' in text
