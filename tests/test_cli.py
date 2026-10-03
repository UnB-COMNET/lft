import click
import pytest

import cli


@pytest.mark.parametrize("text, mbps", [("10mbit", 10), ("500kbit", 0.5), ("35M", 35), ("2G", 2000), ("7.5", 7.5)])
def test_rates(text, mbps):
    assert cli.parse_rate(text) == mbps


def test_shaping_options_become_numbers():
    assert cli.shaping_values(rate="10mbit", delay="20ms", jitter=None, loss="0.5%") == \
        {"rate": 10.0, "delay": 20.0, "jitter": None, "loss": 0.5}
    with pytest.raises(click.UsageError):
        cli.shaping_values(loss="120")


def test_link_option_fills_the_defaults():
    defaults = {"rate": 35.0, "delay": 10.0, "jitter": 1.0, "loss": 0.0}
    assert cli.parse_link("s0:rate=50mbit,delay=8ms", defaults) == ("s0", {"rate": 50.0, "delay": 8.0, "jitter": 1.0, "loss": 0.0})
    assert cli.parse_link("s1", defaults) == ("s1", defaults)
    with pytest.raises(click.UsageError):
        cli.parse_link("s0:speed=1", defaults)
