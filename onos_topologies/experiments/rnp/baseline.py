"""Baseline's decisor: the minimum-latency (server, path), by plain Dijkstra

Latency is the only weight. It is the one metric that is additive along a path,
which is what Dijkstra needs to be correct

Bandwidth is still reported so the logs but it never enters the decision
"""

import re

import networkx as nx

from onos_topologies.experiments.runtime import append_event
from onos_topologies.infrastructure import onos_client


def build_graph(inter_switch_links, link_qdisc_params):
    """Edge weight is the min-max normalised latency, matching the cdn-qoe
    solver's own `aij = a * nrttm[i][j]`. It ranks the same as raw milliseconds
    apart from a ~0.03 discount per hop (the shared `-min` term), so it changes
    no decision here -- it just states the two decisors in the same units"""
    edges = []
    for sw_a, iface_a, sw_b, iface_b in inter_switch_links:
        throughput, delay, _jitter = link_qdisc_params.get(
            iface_a, ("10mbit", "10ms", "0ms")
        )
        bw_match = re.match(r"^\s*([\d.]+)\s*mbit", str(throughput).lower())
        delay_ms = float(str(delay).lower().replace("ms", "").strip())
        bandwidth_mbit = float(bw_match.group(1)) if bw_match else 10.0
        edges.append((sw_a, sw_b, delay_ms, bandwidth_mbit))

    graph = nx.Graph()
    latencies = [edge[2] for edge in edges] or [0.0]
    minimum_latency = min(latencies)
    latency_range = max(latencies) - minimum_latency
    for sw_a, sw_b, delay_ms, bandwidth_mbit in edges:
        weight = 0.0
        if latency_range > 0:
            weight = (delay_ms - minimum_latency) / latency_range
        graph.add_edge(
            sw_a,
            sw_b,
            delay_ms=delay_ms,
            bandwidth_mbit=bandwidth_mbit,
            weight=weight,
        )
    return graph


def _describe(graph, path):
    """`cost` is what Dijkstra minimises (normalised); latency_ms and
    bottleneck_mbit are the raw figures, for the logs only"""
    hops = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
    return {
        "path": path,
        "cost": sum(graph[a][b]["weight"] for a, b in hops),
        "latency_ms": sum(graph[a][b]["delay_ms"] for a, b in hops),
        "bottleneck_mbit": min(
            (graph[a][b]["bandwidth_mbit"] for a, b in hops), default=float("inf")
        ),
    }


def shortest_path(graph, source, target):
    if source == target:
        return _describe(graph, [source])
    try:
        _, path = nx.single_source_dijkstra(graph, source, target, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    return _describe(graph, path)


def k_shortest_paths(graph, source, target, k=3):
    """Best k routes for the decisor report, cheapest first"""
    if source == target:
        return [shortest_path(graph, source, target)]
    out = []
    try:
        for i, path in enumerate(
            nx.shortest_simple_paths(graph, source, target, weight="weight")
        ):
            if i >= k:
                break
            out.append(_describe(graph, path))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        pass
    return out


def select_best_server(graph, client_sw, candidate_switches):
    costs = {}
    for sw in candidate_switches:
        sp = shortest_path(graph, client_sw, sw)
        if sp is not None:
            costs[sw] = sp
    if not costs:
        return {"best": None, "costs": {}}
    return {"best": min(costs, key=lambda sw: costs[sw]["cost"]), "costs": costs}


# Brief: {ip: switch_name} for every host, from the topology's own bookkeeping
def _build_ip_to_switch(topo):
    ip_to_switch = {}
    for pop_name, hosts in topo.hosts_by_pop.items():
        sname = topo.pop_to_sname[pop_name]
        for host in hosts:
            ip = topo._host_ips.get(host.getNodeName())
            if ip:
                ip_to_switch[ip.split("/")[0].strip()] = sname
    return ip_to_switch


def select_best_servers(topo, client_ips, server_ips, qdisc_params=None):
    known = onos_client.known_host_ips(topo.onos_ip, client_ips + server_ips)
    missing = [ip for ip in server_ips if ip not in known]
    if missing:
        print(
            f" [BASELINE] Servers not yet discovered by ONOS, excluded as candidates: {missing}"
        )

    ip_to_switch = _build_ip_to_switch(topo)
    graph = build_graph(topo.inter_switch_links, qdisc_params or topo.link_qdisc_params)
    # Servers sharing a PoP are interchangeable, so the first IP there wins.
    ip_by_switch = {}
    for ip in server_ips:
        if ip in known and ip_to_switch.get(ip):
            ip_by_switch.setdefault(ip_to_switch[ip], ip)

    assignment = {}
    for client_ip in client_ips:
        client_sw = ip_to_switch.get(client_ip) if client_ip in known else None
        if not client_sw:
            print(
                f" [BASELINE] {client_ip}: not discovered by ONOS yet, skipping server selection."
            )
            continue

        best = select_best_server(graph, client_sw, list(ip_by_switch))
        if not best["best"]:
            print(f" [WARNING] {client_ip}: no reachable server found for selection.")
            continue

        c = best["costs"][best["best"]]
        assignment[client_ip] = ip_by_switch[best["best"]]
        print(
            f" [BASELINE] {client_ip}: best server is {assignment[client_ip]} "
            f"(cost={c['cost']:.4f}, latency={c['latency_ms']:.1f}ms, "
            f"bottleneck={c['bottleneck_mbit']:.0f}mbit)"
        )

    return assignment


def log_baseline_decision(
    topo,
    client_to_server,
    qdisc_params,
    device_id_to_sname,
    link_lookup,
    run_root,
    tag,
    read_flows=True,
):
    ip_to_switch = _build_ip_to_switch(topo)
    sname_to_uf = {
        sname: pop.split("-")[-1].upper() for pop, sname in topo.pop_to_sname.items()
    }
    graph = build_graph(topo.inter_switch_links, qdisc_params)

    server_ips = [ip.split("/")[0].strip() for ip in topo.server_ip_range]
    server_switches = [sw for sw in (ip_to_switch.get(ip) for ip in server_ips) if sw]

    def fmt(path):
        return "-".join(sname_to_uf.get(s, s) for s in path)

    active = (
        onos_client.find_active_links_from_flows(
            topo.onos_ip, list(client_to_server.keys()), device_id_to_sname, link_lookup
        )
        if read_flows
        else {}
    )

    lines = [f"[DECISOR] {tag}:"]
    for client_ip, server_ip in client_to_server.items():
        src, dst = ip_to_switch.get(client_ip), ip_to_switch.get(server_ip)
        if not src or not dst:
            lines.append(f"[DECISOR]   {client_ip}: switch unknown, skipping")
            continue

        # Dijkstra takes the lowest weight, so option#1 is always the choice.
        options = k_shortest_paths(graph, src, dst, k=3)
        chosen = options[0] if options else None
        for i, alt in enumerate(options):
            mark = " <- CHOSEN" if i == 0 else ""
            lines.append(
                f"[DECISOR]   {client_ip}->{server_ip} option#{i + 1} "
                f"latency={alt['latency_ms']:.1f}ms "
                f"bottleneck={alt['bottleneck_mbit']:.0f}mbit "
                f"via {fmt(alt['path'])}{mark}"
            )

        installed = {
            onos_client.link_key(a, b) for a, _, b, _ in active.get(client_ip, [])
        }
        pretty = ", ".join(
            f"{sname_to_uf.get(a, a)}<->{sname_to_uf.get(b, b)}"
            for a, _, b, _ in active.get(client_ip, [])
        )
        lines.append(
            f"[DECISOR]   {client_ip} ONOS installed: {pretty or 'NONE (no ADDED flows)'}"
        )

        if chosen and installed:
            want = chosen["path"]
            want_links = {
                onos_client.link_key(want[i], want[i + 1]) for i in range(len(want) - 1)
            }
            if want_links == installed:
                lines.append(
                    f"[DECISOR]   {client_ip} PATH: installed == best ({fmt(want)})"
                )
            else:
                lines.append(
                    f"[DECISOR]   {client_ip} PATH MISMATCH: best is {fmt(want)} "
                    f"but ONOS is forwarding over {pretty}"
                )

        best = select_best_server(graph, src, server_switches)
        if best["best"]:
            b = best["costs"][best["best"]]
            verdict = (
                "SERVER SHOULD CHANGE" if best["best"] != dst else "server unchanged"
            )
            lines.append(
                f"[DECISOR]   {client_ip} SERVER: best under these weights = "
                f"{sname_to_uf.get(best['best'], best['best'])} "
                f"latency={b['latency_ms']:.1f}ms bottleneck={b['bottleneck_mbit']:.0f}mbit "
                f"via {fmt(b['path'])} -> {verdict}"
            )

    msg = "\n".join(lines)
    print(msg)
    append_event(run_root, msg)


def apply_best_paths(
    topo, client_to_server, qdisc_params, device_id_to_sname, paths=None
):
    onos_client.push_link_weights(topo.onos_ip, qdisc_params, device_id_to_sname)

    ip_to_switch = _build_ip_to_switch(topo)
    sname_to_device = {sname: dev for dev, sname in device_id_to_sname.items()}
    graph = None

    applied = {}
    for client_ip, server_ip in client_to_server.items():
        src, dst = ip_to_switch.get(client_ip), ip_to_switch.get(server_ip)
        if not src or not dst:
            print(f" [BASELINE] {client_ip} -> {server_ip}: switch unknown, skipping.")
            continue

        path, detail_str = (paths or {}).get(client_ip), "from cache"
        if path is None:
            if graph is None:
                graph = build_graph(topo.inter_switch_links, qdisc_params)
            sp = shortest_path(graph, src, dst)
            if not sp or not sp["path"]:
                print(
                    f" [BASELINE] {client_ip} -> {server_ip}: no usable path, skipping."
                )
                continue
            path = sp["path"]
            detail_str = (
                f"latency={sp['latency_ms']:.1f}ms "
                f"bottleneck={sp['bottleneck_mbit']:.0f}mbit"
            )

        onos_client.remove_flows_for_pair(
            topo.onos_ip, client_ip, server_ip, list(device_id_to_sname.keys())
        )
        ok, detail = onos_client.install_path_flows(
            topo.onos_ip, path, client_ip, server_ip, sname_to_device
        )

        status = "installed" if ok else f"FAILED ({detail})"
        print(
            f" [BASELINE] {client_ip} -> {server_ip}: path {'-'.join(path)} "
            f"{detail_str} -> {status}"
        )
        if ok:
            applied[client_ip] = path

    return applied
