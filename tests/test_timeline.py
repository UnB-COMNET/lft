from unittest.mock import patch

import pytest

from onos_topologies.runtime import TopologyError, timeline

BASE = {"s0-s1": {"id": "s0-s1", "a": "s0", "b": "s1", "base": {"rate": 10.0, "delay": 20.0, "jitter": 1.0, "loss": 0.0}},
        "s1-s2": {"id": "s1-s2", "a": "s1", "b": "s2", "base": {"rate": 5.0, "delay": 10.0, "jitter": 1.0, "loss": 0.0}}}
DEGRADE = {"rate": 0.1, "delay": 10, "loss": 2}


def test_links_follow_the_windows():
    now = {}
    with patch.object(timeline, "links") as links, patch.object(timeline.state, "sync"):
        timeline._set_links({"s0-s1": "degrade"}, now, BASE, DEGRADE)
        links.shape.assert_called_once_with("s0", "s1", rate=1.0, delay=200.0, loss=2)
        timeline._set_links({"s0-s1": "degrade", "s1-s2": "down"}, now, BASE, DEGRADE)
        links.down.assert_called_once_with("s1", "s2")
        assert links.shape.call_count == 1   # s0-s1 was already degraded
        timeline._set_links({}, now, BASE, DEGRADE)
        assert sorted(c.args for c in links.reset.call_args_list) == [("s0", "s1"), ("s1", "s2")]
    assert now == {"s0-s1": "normal", "s1-s2": "normal"}


def test_load_fills_the_defaults(tmp_path):
    path = tmp_path / "t.py"
    path.write_text('NAME = "t"\nWINDOWS = [{}, {"s0-s1": "down"}]\n')
    plan = timeline.load(path)
    assert (plan["NAME"], plan["WINDOW_S"], len(plan["WINDOWS"]), plan["FLOWS"]) == ("t", 60, 2, [])
    path.write_text("WINDOW_S = 5\n")
    with pytest.raises(TopologyError, match="NAME"):
        timeline.load(path)


def test_flows_start_and_stop_on_time(tmp_path):
    flows = [{"tool": "ping", "client": "cl0", "server": "ds0", "start": 10, "duration": 5, "id": "f1", "sid": None, "done": False}]
    meta = {"id": "t1", "file": str(tmp_path / "flows" / "f1" / "cl0-ds0.ping.txt")}
    with patch.object(timeline.traffic, "start", return_value=meta) as start, patch.object(timeline.traffic, "stop") as stop:
        timeline._tick(5, flows, [], [], tmp_path)
        start.assert_not_called()
        timeline._tick(10, flows, [], [], tmp_path)
        assert start.call_args.kwargs == {"tool": "ping", "client": "cl0", "server": "ds0", "duration": 5,
                                          "out": str(tmp_path / "flows" / "f1")}
        timeline._tick(15, flows, [], [], tmp_path)
        stop.assert_called_once_with("t1")
    assert flows[0]["done"]
