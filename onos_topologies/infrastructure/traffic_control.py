import re
import shlex
import subprocess


# Band 1: probes; band 2: ICMP; band 3: rate-limited TCP traffic
NETEM_BANDS = (("1:1", "10:"), ("1:2", "20:"), ("1:3", "30:"))


def create_prio_netem(sw, interfaces, tcp_ports):
    """Create bands for {interface: (rate, delay, jitter)} in one Docker call"""
    commands = []
    for iface, (rate, delay, jitter) in interfaces.items():
        device = shlex.quote(iface)
        commands.extend([
            # Removes qdisc from iface
            f"tc qdisc del dev {device} root 2>/dev/null || true",
            # Creates a prio escalator with 3 bands on iface (device)
            f"tc qdisc add dev {device} root handle 1: prio bands 3 "
            "priomap 2 2 2 2 2 2 2 2 1 1 1 1 1 1 1 1",
        ])
        commands.extend(_netem_commands("add", iface, delay, jitter, rate))
        commands.extend([
            f"tc filter add dev {device} parent 1: protocol all prio 1 u32 "
            "match u16 0x3366 0xffff at -2 flowid 1:1",
            f"tc filter add dev {device} parent 1: protocol ip prio 2 u32 "
            "match ip protocol 1 0xff flowid 1:2",
        ])
        for port in tcp_ports:
            for direction in ("dport", "sport"):
                commands.append(
                    f"tc filter add dev {device} parent 1: protocol ip prio 3 u32 "
                    f"match ip protocol 6 0xff match ip {direction} {int(port)} 0xffff flowid 1:3"
                )
    if commands:
        subprocess.run(
            ["docker", "exec", sw, "sh", "-ec", "\n".join(commands)],
            check=True,
        )


# Brief: Degrade both link ends, or restore them when action is omitted, and verify the result
def set_link(link, qdisc_params, action=None):
    sw_a, iface_a, sw_b, iface_b = link
    for iface in (iface_a, iface_b):
        if iface not in qdisc_params:
            raise ValueError(f"Missing link parameters for interface {iface!r}")

    results = []
    for sw, iface in [(sw_a, iface_a), (sw_b, iface_b)]:
        old_rate, old_delay, jitter = qdisc_params[iface]
        rate, delay = old_rate, old_delay
        if action is not None:
            delay_factor = action["delay_factor"]
            rate_factor = action["rate_factor"]
            if not 0 <= delay_factor < float("inf") or not 0 < rate_factor < float("inf"):
                raise ValueError("Delay factor must be finite and nonnegative; rate factor must be finite and positive")
            match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(us|ms|s)\s*', str(old_delay))
            if not match:
                raise ValueError(f"Invalid delay or unsupported unit: {old_delay!r}")
            delay_value = float(match.group(1)) * delay_factor
            delay = f"{delay_value:g}{match.group(2)}"
            rate_kbit = rate_to_kbit(old_rate) * rate_factor
            if rate_kbit >= 1000:
                rate = f"{rate_kbit / 1000:g}mbit"
            else:
                rate = f"{rate_kbit:g}kbit"
        update_prio_netem(sw, iface, delay, jitter, rate)
        ok, actual_delay, actual_rate = verify_netem(sw, iface, delay, rate)
        results.append({
            "sw": sw,
            "iface": iface,
            "jitter": jitter,
            "ok": ok,
            "old_delay": old_delay,
            "delay": delay,
            "actual_delay": actual_delay,
            "old_rate": old_rate,
            "rate": rate,
            "actual_rate": actual_rate,
        })
    return results


def update_prio_netem(sw, iface, delay, jitter, rate):
    """Update existing bands without replacing filters"""
    commands = _netem_commands("change", iface, delay, jitter, rate)
    subprocess.run(
        ["docker", "exec", sw, "sh", "-ec", "\n".join(commands)],
        check=True,
    )


def verify_netem(sw, iface, expected_delay, expected_rate):
    """Check the live rate-limited band within 1 ms and 5% tolerance"""
    result = subprocess.run(
        ["docker", "exec", sw, "tc", "qdisc", "show", "dev", iface],
        check=True, capture_output=True, text=True,
    )
    actual_delay = actual_rate = None
    for line in result.stdout.splitlines():
        if f"netem {NETEM_BANDS[-1][1]}" in line:
            delay_match = re.search(r'delay\s+(\S+)', line)
            rate_match = re.search(r'rate\s+(\S+)', line)
            if delay_match:
                actual_delay = delay_match.group(1)
            if rate_match:
                actual_rate = rate_match.group(1)
            break

    if actual_delay is None or actual_rate is None:
        return False, actual_delay, actual_rate

    delays_ms = []
    for delay in (expected_delay, actual_delay):
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(us|ms|s)\s*', str(delay))
        if not match:
            raise ValueError(f"Invalid delay or unsupported unit: {delay!r}")
        factors = {"us": 0.001, "ms": 1.0, "s": 1000.0}
        delays_ms.append(float(match.group(1)) * factors[match.group(2)])
    expected_delay_value, actual_delay_value = delays_ms
    expected_rate_value = rate_to_kbit(expected_rate)
    actual_rate_value = rate_to_kbit(actual_rate)

    delay_ok = abs(actual_delay_value - expected_delay_value) <= 1.0
    rate_ok = abs(actual_rate_value - expected_rate_value) <= 0.05 * expected_rate_value
    return delay_ok and rate_ok, actual_delay, actual_rate


# Brief: Build delay/jitter commands for all bands and rate limiting for the TCP band
# Returns command strings without executing them; use add to create or change to update
# Example: _netem_commands("add", "s0s1", "20ms", "2ms", "10mbit") returns:
# tc qdisc add dev s0s1 parent 1:1 handle 10: netem delay 20ms 2ms
# tc qdisc add dev s0s1 parent 1:2 handle 20: netem delay 20ms 2ms
# tc qdisc add dev s0s1 parent 1:3 handle 30: netem delay 20ms 2ms rate 10mbit
def _netem_commands(operation, iface, delay, jitter, rate):
    commands = []
    for parent, handle in NETEM_BANDS:
        command = (
            f"tc qdisc {operation} dev {shlex.quote(iface)} parent {parent} "
            f"handle {handle} netem delay {shlex.quote(delay)} {shlex.quote(jitter)}"
        )
        if handle == NETEM_BANDS[-1][1]:
            command += f" rate {shlex.quote(rate)}"
        commands.append(command)
    return commands


# Brief: Convert an explicitly specified bit, kbit, mbit or gbit rate to kbit/s
def rate_to_kbit(rate_str):
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(bit|kbit|mbit|gbit)\s*', str(rate_str), re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid rate or unsupported unit: {rate_str!r}")
    value = float(match.group(1))
    unit = match.group(2).lower()
    factors = {"bit": 0.001, "kbit": 1.0, "mbit": 1000.0, "gbit": 1_000_000.0}
    return value * factors[unit]
