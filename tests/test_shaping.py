from unittest.mock import patch

import pytest

from onos_topologies.runtime import shaping


def test_apply_creates_the_bands_then_changes_them_in_place():
    values = {"rate": 5, "delay": 8, "jitter": 1, "loss": 2}
    with patch.object(shaping, "qdiscs", return_value=[]), patch.object(shaping.traffic_control, "create_prio_netem") as create:
        shaping.apply("s0", "s0s1", values)
    create.assert_called_once_with("s0", {"s0s1": ("5mbit", "8ms", "1ms")}, (), 2)
    bands = [{"dev": "s0s1", "kind": "prio", "root": True}]
    with patch.object(shaping, "qdiscs", return_value=bands), patch.object(shaping.traffic_control, "update_prio_netem") as update:
        shaping.apply("s0", "s0s1", values)
    update.assert_called_once_with("s0", "s0s1", "8ms", "1ms", "5mbit", 2)


def test_read_takes_the_data_band_or_a_plain_netem():
    qdiscs = [
        {"dev": "s0s1", "kind": "prio", "root": True, "handle": "1:"},
        {"dev": "s0s1", "kind": "netem", "handle": "10:", "options": {"delay": {"delay": 0.02}}},
        {"dev": "s0s1", "kind": "netem", "handle": "30:",
         "options": {"delay": {"delay": 0.02, "jitter": 0.001}, "rate": {"rate": 1250000}, "loss-random": {"loss": 0.02}}},
        {"dev": "cl0s0", "kind": "netem", "root": True, "handle": "8001:", "options": {"delay": {"delay": 0.005}}},
    ]
    with patch.object(shaping, "qdiscs", return_value=qdiscs):
        assert shaping.read("s0") == {"s0s1": {"rate": 10.0, "delay": 20.0, "jitter": 1.0, "loss": 2.0},
                                      "cl0s0": {"rate": None, "delay": 5.0, "jitter": 0, "loss": 0}}


@pytest.mark.parametrize("mbps, text", [(35, "35mbit"), (0.2, "200kbit"), (1000, "1gbit"), (2.5, "2.5mbit")])
def test_rate_str(mbps, text):
    assert shaping.rate_str(mbps) == text
    assert shaping.mbit(text) == mbps


def test_units():
    assert (shaping.ms("10ms"), shaping.ms("500us"), shaping.ms("1s")) == (10.0, 0.5, 1000.0)
    with pytest.raises(ValueError):
        shaping.ms("10 minutes")
