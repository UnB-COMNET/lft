from unittest.mock import patch
import subprocess

import pytest

from onos_topologies.infrastructure import traffic_control as tc


def test_create_batches_interfaces_and_preserves_traffic_classes():
    interfaces = {"s0s1": ("10mbit", "20ms", "1ms"), "s0s2": ("5mbit", "30ms", "2ms")}
    with patch.object(tc.subprocess, "run") as run:
        tc.create_prio_netem("s0", interfaces, tcp_ports=(6000, 6001))
    run.assert_called_once()
    args = run.call_args.args[0]
    assert args[:5] == ["docker", "exec", "s0", "sh", "-ec"]
    assert run.call_args.kwargs["check"] is True
    commands = args[5].splitlines()
    assert len(commands) == 24  # per iface: root, prio, 3 netem bands, probe + LLDP + ICMP filters, 4 TCP port filters
    for iface, (rate, delay, jitter) in interfaces.items():
        band_commands = [c for c in commands if f"dev {iface} parent" in c and "qdisc add" in c]
        assert len(band_commands) == 3
        assert all(f"delay {delay} {jitter}" in c for c in band_commands)
        assert " rate " not in band_commands[0]
        assert " rate " not in band_commands[1]
        assert band_commands[2].endswith(f"rate {rate}")
        assert any(f"dev {iface}" in c and "0x3366" in c and "flowid 1:1" in c for c in commands)
        assert any(f"dev {iface}" in c and "0x88cc" in c and "flowid 1:1" in c for c in commands)
        assert any(f"dev {iface}" in c and "protocol 1 0xff flowid 1:2" in c for c in commands)
        for port in (6000, 6001):
            for direction in ("sport", "dport"):
                assert any(f"dev {iface}" in c and f"{direction} {port} 0xffff flowid 1:3" in c for c in commands)
    assert "5201" not in args[5]


def test_update_preserves_filters_and_reports_execution_failure():
    error = subprocess.CalledProcessError(2, "docker")
    with patch.object(tc.subprocess, "run", side_effect=error) as run:
        with pytest.raises(subprocess.CalledProcessError):
            tc.update_prio_netem("s0", "s0s1", "100ms", "2ms", "1mbit")
    commands = run.call_args.args[0][5].splitlines()
    assert len(commands) == 3
    assert all(c.startswith("tc qdisc change") for c in commands)
    assert commands[-1].endswith("netem delay 100ms 2ms rate 1mbit")
    assert run.call_args.kwargs["check"] is True


def test_link_degradation_and_restore_use_original_parameters():
    link = ("s0", "s0s1", "s1", "s1s0")
    params = {"s0s1": ("10mbit", "10ms", "1ms"), "s1s0": ("5mbit", "20ms", "2ms")}
    with patch.object(tc, "update_prio_netem") as update, patch.object(
        tc, "verify_netem", return_value=(True, "100ms", "1mbit")
    ):
        tc.set_link(link, params, {"delay_factor": 10, "rate_factor": 0.1})
        assert update.call_args_list[0].args == ("s0", "s0s1", "100ms", "1ms", "1mbit")
        assert update.call_args_list[1].args == ("s1", "s1s0", "200ms", "2ms", "500kbit")
        update.reset_mock()
        tc.set_link(link, params)
        assert update.call_args_list[0].args == ("s0", "s0s1", "10ms", "1ms", "10mbit")
        assert update.call_args_list[1].args == ("s1", "s1s0", "20ms", "2ms", "5mbit")


@pytest.mark.parametrize("output, expected", [
    ("qdisc netem 30: parent 1:3 delay 10ms 1ms rate 10Mbit", (True, "10ms", "10Mbit")),
    ("qdisc netem 30: parent 1:3 delay 15ms 1ms rate 10Mbit", (False, "15ms", "10Mbit")),
    ("qdisc netem 30: parent 1:3 delay 10ms 1ms rate 5Mbit", (False, "10ms", "5Mbit")),
    ("qdisc netem 10: parent 1:1 delay 10ms", (False, None, None)),
    ("qdisc netem 30: parent 1:3 delay 10ms", (False, "10ms", None)),
])
def test_verify_live_band(output, expected):
    result = subprocess.CompletedProcess([], 0, stdout=output)
    with patch.object(tc.subprocess, "run", return_value=result):
        assert tc.verify_netem("s0", "s0s1", "10ms", "10mbit") == expected


@pytest.mark.parametrize("rate", ["10", "10watts", "10mbit trailing", "1..2mbit", None])
def test_rate_requires_a_supported_explicit_unit(rate):
    with pytest.raises(ValueError, match="Invalid rate"):
        tc.rate_to_kbit(rate)


@pytest.mark.parametrize("rate, expected", [("500bit", 0.5), ("1.5kbit", 1.5), ("10Mbit", 10000), ("2gbit", 2000000)])
def test_rate_conversion(rate, expected):
    assert tc.rate_to_kbit(rate) == expected


def test_missing_link_parameters_fail_before_changing_either_end():
    with patch.object(tc, "update_prio_netem") as update:
        with pytest.raises(ValueError, match="s1s0"):
            tc.set_link(("s0", "s0s1", "s1", "s1s0"), {"s0s1": ("10mbit", "10ms", "0ms")})
    update.assert_not_called()


@pytest.mark.parametrize("delay", ["0.01s", "10000us"])
def test_verification_converts_delay_units(delay):
    result = subprocess.CompletedProcess([], 0, stdout=f"qdisc netem 30: delay {delay} rate 10Mbit")
    with patch.object(tc.subprocess, "run", return_value=result):
        assert tc.verify_netem("s0", "s0s1", "10ms", "10mbit")[0]


def test_scaling_preserves_fractional_values_and_zero_delay():
    params = {"a": ("1kbit", "0ms", "0ms"), "b": ("1kbit", "0.5ms", "0ms")}
    with patch.object(tc, "update_prio_netem") as update, patch.object(
        tc, "verify_netem", return_value=(True, "0ms", "0.1kbit")
    ):
        tc.set_link(("s0", "a", "s1", "b"), params, {"rate_factor": 0.1, "delay_factor": 0.5})
    assert update.call_args_list[0].args == ("s0", "a", "0ms", "0ms", "0.1kbit")
    assert update.call_args_list[1].args == ("s1", "b", "0.25ms", "0ms", "0.1kbit")



def test_loss_stays_out_of_the_probe_band():
    probes, icmp, data = tc._netem_commands("add", "s0s1", "20ms", "1ms", "10mbit", loss=2)
    assert probes.endswith("handle 10: netem delay 20ms 1ms")
    assert icmp.endswith("handle 20: netem delay 20ms 1ms loss 2%")
    assert data.endswith("handle 30: netem delay 20ms 1ms loss 2% rate 10mbit")
