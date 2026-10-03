import re
import time
import urllib.parse

import requests

# Brief: ONOS REST helpers for host discovery, link configuration and flow management

ONOS_AUTH = ("onos", "rocks")


# Count route-application REST calls only; exclude diagnostic reads
# to_controller: all calls; controller_to_network: flow POST/DELETE calls
_MSG_COUNTERS = {"to_controller": 0, "controller_to_network": 0}


def reset_msg_counters():
    _MSG_COUNTERS["to_controller"] = 0
    _MSG_COUNTERS["controller_to_network"] = 0


def get_msg_counters():
    return dict(_MSG_COUNTERS)


def _count_msg(is_flow_write=False):
    _MSG_COUNTERS["to_controller"] += 1
    if is_flow_write:
        _MSG_COUNTERS["controller_to_network"] += 1


def onos_get(onos_ip, path, timeout=5):
    resp = requests.get(f"http://{onos_ip}:8181/onos/v1/{path}", auth=ONOS_AUTH, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def find_host_by_ip(hosts, ip_addr):
    for host in hosts:
        if ip_addr in host.get("ipAddresses", []):
            return host
    return None


def host_location(host):
    locs = host.get("locations") or ([host["location"]] if host.get("location") else [])
    return locs[0] if locs else None


# Canonical key for an undirected switch link
def link_key(sw_a, sw_b):
    return (sw_a, sw_b) if sw_a <= sw_b else (sw_b, sw_a)




# Brief: Publish current link bandwidth and latency as ONOS BasicLinkConfig
def push_link_weights(onos_ip, qdisc_params, device_id_to_sname):
    try:
        _count_msg()
        onos_links = onos_get(onos_ip, "links").get("links", [])
    except Exception as e:
        print(f" [WARNING] Could not fetch ONOS links for weight push: {e}")
        return

    link_cfg = {}
    for onos_link in onos_links:
        src = onos_link.get("src", {})
        dst = onos_link.get("dst", {})
        sw_a, sw_b = device_id_to_sname.get(src.get("device")), device_id_to_sname.get(dst.get("device"))
        if not sw_a or not sw_b:
            continue
        throughput, delay, _jitter = qdisc_params.get(f"{sw_a}{sw_b}", ("10mbit", "10ms", "0ms"))
        bw_match = re.match(r'^\s*([\d.]+)\s*mbit', str(throughput).lower())
        bandwidth_mbps = float(bw_match.group(1)) if bw_match else 10.0
        latency_ms = float(str(delay).lower().replace("ms", "").strip())
        link_cfg_key = f"{src.get('device')}/{src.get('port')}-{dst.get('device')}/{dst.get('port')}"
        link_cfg[link_cfg_key] = {"basic": {"bandwidth": bandwidth_mbps, "latency": latency_ms}}

    if link_cfg:
        try:
            _count_msg()
            requests.post(f"http://{onos_ip}:8181/onos/v1/network/configuration/",
                          json={"links": link_cfg}, auth=ONOS_AUTH, timeout=10)
        except Exception as e:
            print(f" [WARNING] Could not push link weights to ONOS: {e}")


# Brief: Return candidate IPs already discovered by ONOS
def known_host_ips(onos_ip, ips):
    try:
        hosts = onos_get(onos_ip, "hosts").get("hosts", [])
    except Exception as e:
        print(f" [WARNING] Could not fetch hosts from ONOS for discovery check: {e}")
        return set()
    known = {ip for host in hosts for ip in host.get("ipAddresses", [])}
    return {ip for ip in ips if ip in known}


# Brief: Build an IPv4 forwarding rule matching the deployer format
def _flow_body(src_ip, dst_ip, out_port, device_id, priority):
    return {
        "appId": "org.onosproject.core",
        "priority": priority,
        "isPermanent": "true",
        "deviceId": device_id,
        "treatment": {"instructions": [{"type": "OUTPUT", "port": str(out_port)}]},
        "selector": {"criteria": [
            {"type": "ETH_TYPE", "ethType": "0x0800"},
            {"type": "IPV4_SRC", "ip": f"{src_ip}/32"},
            {"type": "IPV4_DST", "ip": f"{dst_ip}/32"},
        ]},
    }


# Brief: Remove rules matching both endpoints, in either direction
# Call before installing a replacement path to avoid stale forwarding rules
def remove_flows_for_pair(onos_ip, client_ip, server_ip, device_ids):
    removed = 0
    for device_id in device_ids:
        try:
            _count_msg()
            flows = onos_get(onos_ip, f"flows/{device_id}").get("flows", [])
        except Exception:
            continue
        for flow in flows:
            criteria = flow.get("selector", {}).get("criteria", [])
            ips = {c["ip"].split("/")[0] for c in criteria if "ip" in c}
            if client_ip not in ips or server_ip not in ips:
                continue
            try:
                _count_msg(is_flow_write=True)
                requests.delete(
                    f"http://{onos_ip}:8181/onos/v1/flows/"
                    f"{urllib.parse.quote_plus(device_id)}/{flow.get('id')}",
                    auth=ONOS_AUTH, timeout=5)
                removed += 1
            except Exception:
                pass
    return removed


# Brief: Install bidirectional flows along path_snames; return (ok, detail)
# Use explicit flows because the intent compiler does not honor these path weights
def install_path_flows(onos_ip, path_snames, client_ip, server_ip,
                       sname_to_device, priority=40000):
    # A shared-switch path still needs both host-egress rules
    if not path_snames:
        return False, "empty path"

    try:
        _count_msg()
        links = onos_get(onos_ip, "links").get("links", [])
        _count_msg()
        hosts = onos_get(onos_ip, "hosts").get("hosts", [])
    except Exception as e:
        return False, f"could not read ONOS links/hosts: {e}"

    egress = {(l["src"]["device"], l["dst"]["device"]): l["src"]["port"] for l in links}

    def host_port(ip_addr):
        host = find_host_by_ip(hosts, ip_addr)
        loc = host_location(host) if host else None
        return (loc.get("elementId"), loc.get("port")) if loc else (None, None)

    cli_sw, cli_port = host_port(client_ip)
    srv_sw, srv_port = host_port(server_ip)
    if not cli_port or not srv_port:
        return False, f"host location unknown (client={cli_sw}, server={srv_sw})"

    devices = [sname_to_device.get(s) for s in path_snames]
    if any(d is None for d in devices):
        return False, f"unknown switch in path {path_snames}"

    posts = []
    # Forward: client -> server, one hop at a time, then out to the server host.
    for i in range(len(devices) - 1):
        port = egress.get((devices[i], devices[i + 1]))
        if not port:
            return False, f"no link {path_snames[i]} -> {path_snames[i + 1]}"
        posts.append((devices[i], _flow_body(client_ip, server_ip, port, devices[i], priority)))
    posts.append((devices[-1], _flow_body(client_ip, server_ip, srv_port, devices[-1], priority)))

    # Return: same path reversed, then out to the client host.
    for i in range(len(devices) - 1, 0, -1):
        port = egress.get((devices[i], devices[i - 1]))
        if not port:
            return False, f"no link {path_snames[i]} -> {path_snames[i - 1]}"
        posts.append((devices[i], _flow_body(server_ip, client_ip, port, devices[i], priority)))
    posts.append((devices[0], _flow_body(server_ip, client_ip, cli_port, devices[0], priority)))

    failed = 0
    for device_id, body in posts:
        try:
            _count_msg(is_flow_write=True)
            resp = requests.post(
                f"http://{onos_ip}:8181/onos/v1/flows/{urllib.parse.quote_plus(device_id)}",
                json=body, auth=ONOS_AUTH, timeout=10)
            if resp.status_code not in (200, 201):
                failed += 1
        except Exception:
            failed += 1

    if failed:
        return False, f"{failed}/{len(posts)} flow POSTs failed"
    return True, f"{len(posts)} rules over {'-'.join(path_snames)}"


# Brief: Return active inter-switch links per client, matched by IP or MAC
# Require ADDED flows with increasing byte counters to exclude stale rules
# Resample until every client has a live link or max_wait_s expires
def find_active_links_from_flows(onos_ip, client_ips, device_id_to_sname, link_lookup,
                                 sample_gap_s=4.0, max_wait_s=30.0):
    try:
        onos_links = onos_get(onos_ip, "links").get("links", [])
    except Exception as e:
        print(f" [WARNING] Could not fetch ONOS links: {e}")
        return {}

    port_to_peer_device = {
        (l["src"]["device"], str(l["src"]["port"])): l["dst"]["device"]
        for l in onos_links
    }

    try:
        hosts = onos_get(onos_ip, "hosts").get("hosts", [])
    except Exception:
        hosts = []
    ip_to_mac = {}
    for ip in client_ips:
        h = find_host_by_ip(hosts, ip)
        if h and h.get("mac"):
            ip_to_mac[ip] = h["mac"].upper()

    def sample():
        out = {}
        for device_id in device_id_to_sname:
            try:
                out[device_id] = onos_get(onos_ip, f"flows/{device_id}").get("flows", [])
            except Exception:
                out[device_id] = []
        return out

    client_ip_set = set(client_ips)
    seen_per_client = {ip: set() for ip in client_ips}
    active_links = {ip: [] for ip in client_ips}

    def clients_of(flow):
        criteria = flow.get("selector", {}).get("criteria", [])
        ips_in_flow = {c["ip"].split("/")[0] for c in criteria if "ip" in c}
        macs_in_flow = {c["mac"].upper() for c in criteria if "mac" in c}
        return {ip for ip in client_ip_set
                if ip in ips_in_flow or ip_to_mac.get(ip) in macs_in_flow}

    def record(device_id, flow, clients):
        for instr in flow.get("treatment", {}).get("instructions", []):
            if instr.get("type") != "OUTPUT":
                continue
            peer_device = port_to_peer_device.get((device_id, str(instr.get("port"))))
            if not peer_device:
                continue # port faces a host, not another switch
            sw_a, sw_b = device_id_to_sname.get(device_id), device_id_to_sname.get(peer_device)
            if not sw_a or not sw_b or sw_a == sw_b:
                continue
            key = link_key(sw_a, sw_b)
            link = link_lookup.get(key)
            if not link:
                continue
            for client_ip in clients:
                if key not in seen_per_client[client_ip]:
                    seen_per_client[client_ip].add(key)
                    active_links[client_ip].append(link)

    prev_bytes = {(d, f.get("id")): f.get("bytes", 0)
                  for d, flows in sample().items() for f in flows}

    deadline = time.time() + max_wait_s
    while True:
        time.sleep(sample_gap_s)
        for device_id, flows in sample().items():
            for flow in flows:
                key = (device_id, flow.get("id"))
                was, now = prev_bytes.get(key), flow.get("bytes", 0)
                prev_bytes[key] = now
                if flow.get("state") != "ADDED":
                    continue
                # New rules with nonzero byte counters are already active
                if now <= (was if was is not None else 0):
                    continue
                clients = clients_of(flow)
                if clients:
                    record(device_id, flow, clients)

        if all(active_links[ip] for ip in client_ips) or time.time() >= deadline:
            break

    missing = [ip for ip in client_ips if not active_links[ip]]
    if missing:
        print(f" [WARNING] No live link proven for {', '.join(missing)} after "
              f"{max_wait_s:.0f}s -- they will not be degraded this snapshot.")

    return {ip: links for ip, links in active_links.items() if links}
