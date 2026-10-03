import sys
import json
import os
import random
import subprocess
import threading
import time
from pathlib import Path

import requests

# Resolve checkout imports when executed directly
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    __package__ = "onos_topologies.experiments.rnp"

from onos_topologies.experiments.runtime import (
    append_event,
    restore_tty,
    sleep_countdown,
)
from onos_topologies.infrastructure import onos_client
from onos_topologies.infrastructure.containers import wait_http
from onos_topologies.infrastructure.containers import cleanup, compose_cmd, compose_down, compose_up
from onos_topologies.infrastructure.traffic_control import (
    create_prio_netem,
    rate_to_kbit,
    set_link,
)
from onos_topologies.measurements.csv_io import merge_all_snapshot_csvs
from onos_topologies.measurements.iperf import (
    merge_all_iperf_jsons_to_csv,
    slice_iperf_json_to_snapshots,
    stitch_iperf_parts,
    zero_fill_if_empty,
)
from onos_topologies.measurements.ovs import (
    merge_all_snapshot_ovs_csvs,
    snapshot_ovs_state,
)
from onos_topologies.measurements.ping import snapshot_pings_to_single_csv
from onos_topologies.measurements.service_metrics import (
    BASELINE_METRICS_FIELDS,
    SUPERVISOR_METRICS_FIELDS,
    append_deployer_metrics,
    append_metrics_row,
)
from onos_topologies.topologies.configs.rnp import CONFIG_RNP
from onos_topologies.topologies.topology import Topology

from .baseline import apply_best_paths, log_baseline_decision, select_best_servers
from .config import (
    DEMAND_RATE,
    INTENT_TIMEOUT_S,
    IPERF_CONNECT_TIMEOUT_S,
    IPERF_DURATION_MARGIN_S,
    IPERF_NOTIFY_PORT,
    LLM_URL,
    MODE_MENU,
    MODES,
    N_SNAPSHOTS,
    PATH_WARMUP_TIMEOUT_S,
    POPS,
    ROTATE_S,
    SEED,
    SNAPSHOT_ACTIONS,
    SUPERVISOR_CRITICAL_MBIT,
    base_url_deployer,
    base_url_metrics,
    base_url_supervisor,
)
from .session import IperfSession, start_notifications

project_root = Path(__file__).resolve().parents[3]


# Fire-and-forget telemetry: never let an unreachable supervisor abort a run.
def post_quietly(url, **kwargs):
    try:
        requests.post(url, timeout=3, **kwargs)
    except Exception:
        pass


def main(algorithm: str = None, seed: int = None, auto_start: bool = None, run_name: str = None):
    if algorithm is None:
        algorithm = ''
        while algorithm not in MODES:
            algorithm = input(f"Choose a number for the topology mode: {MODE_MENU}\n").strip().lower()

    mode_cfg = MODES[algorithm]
    service  = mode_cfg.get("service", mode_cfg["name"])

    # None asks; True starts deployer and supervisor; False: they are already running
    auto_start_containers = bool(auto_start)
    if auto_start is None and mode_cfg.get("use_deployer", False):
        launch_choice = ''
        while launch_choice not in {'1', '2'}:
            launch_choice = input(
                "\nHow do you want to start the deployer and supervisor?"
                "\n[1] - Automatically (no logs visible)"
                "\n[2] - Manually (I'll start them in separate terminals)\n"
            ).strip()
        auto_start_containers = (launch_choice == '1')

    if seed is None:
        seed_input = input(f"\nRandom seed for client/server placement and link "
                            f"degradation [{SEED}]: ").strip()
        seed = int(seed_input) if seed_input else SEED
    print(f" [SETUP] Random seed: {seed}")
    rng = random.Random(seed)
    path_cache = {} # Live degraded links can differ between runs with the same seed
    # POPS rows are mutable module state: without this reset a second main() in
    # the same process (batch.py) stacks hosts on the previous run's counts.
    for pop in POPS:
        pop[1] = pop[2] = 0
    # 2 clients and 4 servers, scattered over random PoPs (seeded).
    for _ in range(2):
        pop_index = rng.randint(0, len(POPS)-1)
        POPS[pop_index][1] += 1
    for _ in range(4):
        pop_index = rng.randint(0, len(POPS)-1)
        POPS[pop_index][2] += 1

    results_root = project_root / "results" / "iperf"
    results_root.mkdir(parents=True, exist_ok=True)

    if run_name is None:
        custom_name = (input("\nWould you like to add a custom name to the results directory? [y/N]\n").strip().lower() == "y")
        run_name = input("Please type in the name: ").strip().lower() if custom_name else None

    run_root = results_root / run_name if run_name else results_root / f"run_{time.strftime('%Y-%m-%d_%H-%M-%S')}"
    run_root.mkdir(parents=True, exist_ok=True)
    os.environ["LFT_RESULTS"] = str(run_root)

    snaps_root = run_root / "snapshots"
    snaps_root.mkdir(parents=True, exist_ok=True)

    # Whole-run parts + the stitched continuous file per client, before slicing
    # into snapshots/snapshot_{idx}/iperf/{client}%{idx}.json at the end.
    iperf_continuous_dir = run_root / "iperf_continuous"
    iperf_continuous_dir.mkdir(parents=True, exist_ok=True)

    # ICMP rides prio band 1:2, which has netem's delay but no rate limit, so
    # ping measures the path itself instead of iperf3's queue-dominated TCP RTT.
    ping_dir = run_root / "ping_logs"
    ping_dir.mkdir(parents=True, exist_ok=True)

    snap_start_times = {}
    # Closed when the degradation stops, so the restore and reroute that follow
    # don't land inside the window they come after.
    snap_end_times = {}

    meta = {
        "algorithm": algorithm,
        "mode": mode_cfg["name"],
        "supervisor_mode": mode_cfg.get("supervisor_mode"),
        "start_ts": int(time.time()),
        "rotate_s": f"{ROTATE_S}s",
        "n_snapshots": N_SNAPSHOTS,
        "seed": seed,
    }
    (run_root / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    append_event(run_root, f"RUN_START {time.strftime('%Y%m%d-%H%M%S')}")

    # Epoch-stamped phase markers, so a dip in iperf_all.csv/ping_all.csv can be
    # lined up against the orchestration step running at that moment.
    def mark(label):
        append_event(run_root, f"PHASE {time.time():.3f} {label}")

    client_to_server = {}
    currently_degraded = []
    client_jobs = []
    run_t0 = None
    server_by_ip = {} # filled once the topology exists; used to recycle listeners

    session = IperfSession(ping_dir, client_to_server, server_by_ip, mark)

    def _send_intent_async(clean_ip, deployer_service):
        payload = {"intent": f"define intent q1: for endpoint('{clean_ip}') add service('{deployer_service}')"}
        print(f" [SETUP] Sending intent for {clean_ip} (async, timeout={INTENT_TIMEOUT_S}s)...")
        try:
            response = requests.post(base_url_deployer, json=payload, timeout=INTENT_TIMEOUT_S)
            if response.status_code in [200, 201]:
                data = response.json()
                srv_ip = data.get('server_ip')
                if srv_ip:
                    session.apply_server_change(clean_ip, srv_ip, reason="deploy")
                    print(f" [DEPLOYER] client {clean_ip} -> server {srv_ip}")
                for ip, info in data.get('controller_responses', {}).items():
                    flows = info.get('output', {}).get('responses', [])
                    print(f" [DEPLOYER] {len(flows)} flows installed by ONOS ({ip})")
            else:
                print(f" [ERROR] Deployer returned {response.status_code} for {clean_ip}")
        except Exception as e:
            print(f" [ERROR] Request error for {clean_ip}: {e}")

    notify_server = None
    if mode_cfg.get("use_deployer", False):
        notify_server = start_notifications(session.apply_server_change, IPERF_NOTIFY_PORT)

    try:
        cleanup()

        onos_tag = f"onosproject/onos:{mode_cfg['onos']}"
        topo = Topology(config=CONFIG_RNP, results_dir=run_root, iperf=True, onos_version=onos_tag)
        topo.run(run_discovery=True, disable_fwd=mode_cfg["disable_fwd"])
        c1 = topo.controller

        switch_names = [sw.getNodeName() for sw in topo.switches.values()]
        link_lookup = {
            onos_client.link_key(sw_a, sw_b): (sw_a, iface_a, sw_b, iface_b)
            for sw_a, iface_a, sw_b, iface_b in topo.inter_switch_links
        }
        device_id_to_sname = {f"of:{int(sname[1:]) + 1:016x}": sname for sname in topo.pop_to_sname.values()}

        if mode_cfg["apps"]:
            print(f" [SETUP] Activating extra apps: {', '.join(mode_cfg['apps'])}")
            for app in mode_cfg["apps"]:
                c1.activateONOSApps(server_ip=topo.onos_ip,
                                    command=f"app activate org.onosproject.{app}")

        print(" [SETUP] Telemetry -> Real-Time Mode")
        comp = "com.maojianwei.link.quality.measurement.impl.MaoLinkQualityManager"
        karaf = "/home/onos/apache-karaf-4.2.14/bin/client -u karaf -p karaf"
        # Liveness detection compares flow byte counters, so the default 10s
        # poll makes live rules read unchanged and look abandoned.
        flow_provider = "org.onosproject.provider.of.flow.impl.OpenFlowRuleProvider"
        cmd_str = (f"cfg set {comp} latencyAverageSize 1; cfg set {comp} probeInterval 500; "
                   f"cfg set {comp} calculateInterval 500; "
                   f"cfg set {flow_provider} flowPollFrequency 2")
        # Command as argument, not via `-i`: Karaf's interactive console puts the
        # tty into raw mode, staircasing every print() for the rest of the run.
        subprocess.run(f'sudo docker exec c1 {karaf} "{cmd_str}"',
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if not mode_cfg["disable_fwd"]:
            # With the default 10s idle timeout, expiring mid-path rules get
            # rebuilt one switch at a time, leaving neighbours with inconsistent
            # next hops -- that closed a routing loop in this cyclic topology.
            # flowTimeout past the run length stops the piecemeal rebuild, and
            # matchDstMacOnly makes every host's rules one loop-free tree.
            fwd_comp = "org.onosproject.fwd.ReactiveForwarding"
            fwd_timeout = N_SNAPSHOTS * ROTATE_S + 600
            print(f" [SETUP] Hardening reactive forwarding (flowTimeout={fwd_timeout}s, "
                  f"matchDstMacOnly=true)...")
            fwd_cfg = (f"cfg set {fwd_comp} flowTimeout {fwd_timeout}; "
                       f"cfg set {fwd_comp} matchDstMacOnly true")
            subprocess.run(f'sudo docker exec c1 {karaf} "{fwd_cfg}"',
                           shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        print("\n[DONE] Topology is up and running.")

        if mode_cfg.get("use_deployer", False):
            wait_http("http://127.0.0.1:8181/onos/v1/cluster", auth=("onos", "rocks"))
            sup_mode = mode_cfg["supervisor_mode"]
            supervisor_env = {"SUPERVISOR_MODE": sup_mode}
            if sup_mode == "llm":
                supervisor_env["LLM_URL"] = os.environ.get("LLM_URL", LLM_URL)
            if auto_start_containers:
                print(f"\n [SETUP] Starting deployer and supervisor (drift mode: {sup_mode})...")
                compose_up(supervisor_env)
            else:
                print("\n [SETUP] Start the deployer and supervisor manually, with their logs attached:")
                print(f"  {compose_cmd('up', supervisor_env)}")
            append_event(run_root, f"SUPERVISOR_MODE {sup_mode}")
            wait_http(base_url_metrics)
            wait_http(f"{base_url_supervisor}/metrics")

        for raw_ip in topo.client_ip_range:
            clean_ip = raw_ip.split('/')[0].strip()
            client_to_server[clean_ip] = rng.choice(topo.server_ip_range).split('/')[0].strip()

        # Baseline is the oracle reference, so it re-decides BOTH axes -- which
        # server and which path -- under whatever link state is in force. Fixing
        # the server at setup crippled it: cl0 was pinned to SE, and SE is a
        # dead end (its only other neighbour, AL, reaches the graph through SE
        # itself), so a strangled BA-SE left the path recompute with nothing to
        # choose and the client ate 9.6 Mbit/s for the whole window.
        # Records the wall-clock time each reroute finishes writing flows, so the
        # snapshot loop can measure degradation -> flow-rules-applied latency.
        reroute_timing = {}

        def baseline_reroute(qdisc_params, key, tag=None):
            client_ips = [ip.split('/')[0].strip() for ip in topo.client_ip_range]
            server_ips = [ip.split('/')[0].strip() for ip in topo.server_ip_range]

            hit = path_cache.get(key)
            if hit:
                print(f" [CACHE] {key}: reusing cached decision, skipping the decisor.")
                chosen, paths = hit["servers"], hit["paths"]
            else:
                chosen, paths = select_best_servers(topo, client_ips, server_ips, qdisc_params), None

            for client_ip, new_server in chosen.items():
                old_server = client_to_server.get(client_ip)
                if new_server == old_server:
                    continue
                # Drop the old pair's rules before the client moves, or they sit
                # in the tables matching an IP that no longer carries traffic.
                if old_server:
                    onos_client.remove_flows_for_pair(
                        topo.onos_ip, client_ip, old_server, list(device_id_to_sname.keys()))
                # Follow the client with iperf3 and ping, exactly as the deployer
                # push does -- otherwise the flows point at the new server while
                # the traffic keeps going to the old one. It updates
                # client_to_server itself, which apply_best_paths reads below.
                session.apply_server_change(client_ip, new_server, reason="baseline")

            applied = apply_best_paths(topo, client_to_server, qdisc_params,
                                       device_id_to_sname, paths)
            reroute_timing["apply_ts"] = time.time()

            if not hit:
                path_cache[key] = {"servers": dict(client_to_server), "paths": applied}
                # The decisor report reads live flow state with its own resampling
                # loop, so it only runs on the miss that produced the decision --
                # and never at setup, where no traffic exists to observe yet.
                log_baseline_decision(topo, client_to_server, qdisc_params,
                                      device_id_to_sname, link_lookup, run_root,
                                      tag or key, read_flows=(key != "setup"))

        if mode_cfg.get("onos_weighted"):
            print(" [BASELINE] Selecting each client's best server and path "
                  "(ONOS's own /paths is hop-count-only, ignores pushed link weights)...")
            baseline_reroute(topo.link_qdisc_params, "setup", "initial (undegraded weights)")

        if service == "fwd":
            # The seeded draw above is this mode's only decision, so log it.
            for client_ip, server_ip in client_to_server.items():
                print(f" [FWD] {client_ip}: random server {server_ip} (seed {seed}), "
                      f"routing left to org.onosproject.fwd, never revisited")

        num_clients = len(topo.clients)
        iperf_ports = range(5201, 5201 + num_clients)

        # Batch interface setup in one Docker call per switch
        print(" [SETUP] Applying prio+netem (probe/ICMP/iperf bands) on all inter-switch links...")
        by_switch = {}
        for sw_a, iface_a, sw_b, iface_b in topo.inter_switch_links:
            for sw, iface in [(sw_a, iface_a), (sw_b, iface_b)]:
                params = topo.link_qdisc_params[iface]
                by_switch.setdefault(sw, {})[iface] = params

        for sw, interfaces in by_switch.items():
            create_prio_netem(sw, interfaces, tcp_ports=iperf_ports)

        print(f" [SETUP] Starting iperf3 servers on all {len(topo.servers)} nodes "
              f"(ports 5201-{5200 + num_clients})...")
        server_by_ip.update({
            topo._host_ips[name].split('/')[0].strip(): obj
            for name, obj in topo.servers.items() if name in topo._host_ips
        })
        for server_obj in topo.servers.values():
            for port in iperf_ports:
                server_obj.startServer(port)
        time.sleep(2)

        append_event(run_root, f"CONTINUOUS_START {int(time.time())}")

        run_t0 = time.time()
        snapshots_duration = N_SNAPSHOTS * ROTATE_S
        run_duration = snapshots_duration + IPERF_DURATION_MARGIN_S 

        for cli_idx, (client_name, client_obj) in enumerate(topo.clients.items()):
            client_ip = topo.client_ip_range[cli_idx].split('/')[0].strip()
            port = 5201 + cli_idx

            assigned_server = client_to_server.get(client_ip)
            if not assigned_server:
                print(f" [WARN] No server assigned for {client_name} ({client_ip}), skipping.")
                continue

            # cdn-qoe deploys asynchronously after this loop, so probing here
            # would always fail and burn the timeout per client.
            if mode_cfg.get("use_deployer", False):
                print(f" [SETUP] {client_name} -> {assigned_server}: deferring path check "
                      f"to the deployer's deploy.")
            elif session.wait_for_path(client_name, assigned_server):
                print(f" [SETUP] {client_name} -> {assigned_server}: path is up.")
            else:
                msg = (f"[WARN] {client_name} -> {assigned_server}: path did NOT come up in "
                       f"{PATH_WARMUP_TIMEOUT_S}s; its data will be zero-filled and is NOT usable.")
                print(f" {msg}")
                append_event(run_root, msg)

            out_path = iperf_continuous_dir / f"{client_name}_part1.json"
            proc, f_out = client_obj.runIperf(assigned_server, port, run_duration, out_path,
                                               connect_timeout_s=IPERF_CONNECT_TIMEOUT_S,
                                               rate=DEMAND_RATE)
            ping_proc, ping_out = session.start_ping(client_name, assigned_server, mode="w")
            client_jobs.append({
                "client_name": client_name,
                "client_obj": client_obj,
                "client_ip": client_ip,
                "port": port,
                "server_ip": assigned_server,
                "proc": proc,
                "f_out": f_out,
                "ping_proc": ping_proc,
                "ping_out": ping_out,
                "parts": [out_path],
                "part_start_ts": run_t0,
            })

        restore_tty() # Restore terminal formatting after starting iperf3

        # Both the deployer push and baseline's own reroute move clients between
        # servers, and both need the running iperf3 jobs to follow them.
        if mode_cfg.get("use_deployer", False) or mode_cfg.get("onos_weighted"):
            with session.lock:
                session.active_jobs = {job["client_ip"]: job for job in client_jobs}
                # Covers the real end, not N*ROTATE_S: expiring early makes
                # _apply_server_change refuse to relaunch iperf3, pinning a
                # client to a server the deployer abandoned.
                session.run_deadline = run_t0 + run_duration
                session.run_start    = run_t0
                session.iperf_dir    = iperf_continuous_dir

        if mode_cfg.get("use_deployer", False):
            for url in (f"{base_url_supervisor}/metrics/reset", f"{base_url_metrics}/reset"):
                requests.post(url, timeout=5).raise_for_status()

        if mode_cfg.get("use_deployer", False):
            print(f" [SETUP] Sending intents in background (deploy timeout={INTENT_TIMEOUT_S}s)...")
            for raw_ip in topo.client_ip_range:
                clean_ip = raw_ip.split('/')[0].strip()
                threading.Thread(
                    target=_send_intent_async,
                    args=(clean_ip, service),
                    daemon=True,
                ).start()

        snap_idx = 1
        while snap_idx <= N_SNAPSHOTS:
            snap_dir = snaps_root / f"snapshot_{snap_idx}"
            ovs_dir = snap_dir / "ovs"
            ovs_dir.mkdir(parents=True, exist_ok=True)

            currently_degraded = []
            mark(f"snap{snap_idx} ITERATION_BEGIN")

            # Baseline keeps its own control-plane metrics in-process: zero the
            # onos_client message counters here and collect degrade/apply times
            # for this snapshot as they happen.
            baseline_metrics = {}
            if mode_cfg.get("onos_weighted"):
                onos_client.reset_msg_counters()
                reroute_timing.pop("apply_ts", None)

            action = SNAPSHOT_ACTIONS.get(snap_idx)
            if action is not None:
                mark(f"snap{snap_idx} SAMPLING_LIVE_LINKS_BEGIN")
                # Degrade a link that is really forwarding: read it from ONOS's
                # flow tables, not from any path we computed ourselves.
                active_links_by_client = onos_client.find_active_links_from_flows(
                    topo.onos_ip, list(client_to_server.keys()), device_id_to_sname, link_lookup)
                mark(f"snap{snap_idx} SAMPLING_LIVE_LINKS_END "
                     f"found={ {ip: len(v) for ip, v in active_links_by_client.items()} }")
                access_links_by_client = {
                    client_ip: rng.choice(links)
                    for client_ip, links in active_links_by_client.items()
                }
                no_links_msg = "no active links found in ONOS flow state for any client"

                link_to_clients = {}
                for client_ip, link in access_links_by_client.items():
                    link_to_clients.setdefault(link, []).append(client_ip)
                active_links = list(link_to_clients.keys())

                if active_links:
                    msg_lines = [f"[SCALE] snap={snap_idx} degrading {len(active_links)} link(s) "
                                 f"(delay x{action['delay_factor']}, rate x{action['rate_factor']}):"]
                    qdisc_overrides = {}
                    for link in active_links:
                        a, _, b, _ = link
                        clients_str = ",".join(link_to_clients[link])
                        changes = set_link(link, topo.link_qdisc_params, action)
                        currently_degraded.append(link)
                        for c in changes:
                            qdisc_overrides[c["iface"]] = (c["rate"], c["delay"], c["jitter"])
                            msg_lines.append(
                                f"[SCALE]   {a}<->{b} ({c['sw']}:{c['iface']}) clients={clients_str} "
                                f"delay {c['old_delay']}->{c['delay']} rate {c['old_rate']}->{c['rate']} "
                                f"verified={c['ok']} actual={c['actual_delay']}/{c['actual_rate']}")

                        # Says up front whether threshold mode can even notice
                        # this degradation, instead of waiting a whole snapshot.
                        share = rate_to_kbit(changes[0]["rate"]) / 1000.0 / len(link_to_clients[link])
                        trips = share < SUPERVISOR_CRITICAL_MBIT
                        msg_lines.append(
                            f"[PREDICT] {a}<->{b}: ~{share:.1f} Mbit/s per client vs Critical at "
                            f"{SUPERVISOR_CRITICAL_MBIT:.0f} -> "
                            f"{'should trigger a recalculation' if trips else 'WARNING only, cdn-qoe will NOT react'}")

                    degrade_ts = time.time()
                    post_quietly(f"{base_url_supervisor}/metrics/degrade", json={"ts": degrade_ts})
                    print("\n".join(msg_lines))
                    append_event(run_root, "\n".join(msg_lines))
                    mark(f"snap{snap_idx} NETEM_APPLIED")

                    if mode_cfg.get("onos_weighted"):
                        print(" [BASELINE] Re-picking best server and path after degradation...")
                        mark(f"snap{snap_idx} REROUTE_BEGIN")
                        baseline_reroute({**topo.link_qdisc_params, **qdisc_overrides},
                                         f"snap{snap_idx}:degraded", f"snap={snap_idx} DEGRADED weights")
                        mark(f"snap{snap_idx} REROUTE_END")
                        # Degradation -> flow-rules-applied latency, the baseline's
                        # analogue of the deployer's total_recalculate_time_s.
                        apply_ts = reroute_timing.get("apply_ts")
                        baseline_metrics["degrade_ts"] = degrade_ts
                        if apply_ts is not None:
                            baseline_metrics["degrade_to_apply_s"] = apply_ts - degrade_ts
                else:
                    print(f" [DEGRADE] Snapshot {snap_idx}: {no_links_msg}, skipping.")

            # Window opens only now, after the degrade/reroute work, and closes
            # before the restore: both ends bounded, so every snapshot measures
            # exactly ROTATE_S under one stable condition.
            snap_start_times[snap_idx] = time.time()
            append_event(run_root,
                               f"SNAPSHOT_{snap_idx}_START {time.strftime('%Y%m%d-%H%M%S')}")
            mark(f"snap{snap_idx} WINDOW_OPEN")
            print(f" [WAIT] Snapshot {snap_idx} measuring for {ROTATE_S}s "
                  f"(iperf3 runs continuously in the background)...")
            time.sleep(ROTATE_S)
            snap_end_times[snap_idx] = time.time()
            mark(f"snap{snap_idx} WINDOW_CLOSE")

            if currently_degraded:
                mark(f"snap{snap_idx} RESTORE_BEGIN")
                msg_lines = [f"[RESTORE] snap={snap_idx} restoring {len(currently_degraded)} link(s):"]
                for link in currently_degraded:
                    a, _, b, _ = link
                    for r in set_link(link, topo.link_qdisc_params):
                        msg_lines.append(
                            f"[RESTORE]   {a}<->{b} ({r['sw']}:{r['iface']}) "
                            f"delay ->{r['delay']} rate ->{r['rate']} verified={r['ok']} actual={r['actual_delay']}/{r['actual_rate']}")
                print("\n".join(msg_lines))
                append_event(run_root, "\n".join(msg_lines))
                currently_degraded = []
                mark(f"snap{snap_idx} RESTORE_END")

                if mode_cfg.get("onos_weighted"):
                    print(" [BASELINE] Re-picking best server and path after restoring link(s)...")
                    mark(f"snap{snap_idx} RESTORE_REROUTE_BEGIN")
                    baseline_reroute(topo.link_qdisc_params, f"snap{snap_idx}:restored",
                                     f"snap={snap_idx} RESTORED weights")
                    mark(f"snap{snap_idx} RESTORE_REROUTE_END")

            mark(f"snap{snap_idx} OVS_DUMP_BEGIN")
            snapshot_ovs_state(
                switch_names=switch_names,
                outdir=ovs_dir,
                of_version="OpenFlow13",
                parse_csv=True,
                snapshot_idx=snap_idx,
            )
            mark(f"snap{snap_idx} OVS_DUMP_END")

            if mode_cfg.get("use_deployer", False):
                append_deployer_metrics(run_root, snap_idx, base_url_metrics, reset_after=True)
                append_deployer_metrics(
                    run_root, snap_idx, f"{base_url_supervisor}/metrics",
                    out_csv_name="supervisor_metrics.csv",
                    fields=SUPERVISOR_METRICS_FIELDS, reset_after=True,
                )
                mark(f"snap{snap_idx} METRICS_PULLED")
            elif mode_cfg.get("onos_weighted"):
                # Fold in the message counters accumulated since the reset at the
                # top of this snapshot (degrade reroute + any restore reroute).
                counters = onos_client.get_msg_counters()
                baseline_metrics["msgs_to_controller"] = counters["to_controller"]
                baseline_metrics["msgs_controller_to_network"] = counters["controller_to_network"]
                append_metrics_row(
                    run_root, snap_idx, baseline_metrics,
                    out_csv_name="baseline_metrics.csv",
                    fields=BASELINE_METRICS_FIELDS,
                )
                mark(f"snap{snap_idx} METRICS_PULLED")

            append_event(run_root, f"SNAPSHOT_{snap_idx}_END {time.strftime('%Y%m%d-%H%M%S')}")
            snap_idx += 1

        append_event(run_root, f"RUN_END {time.strftime('%Y%m%d-%H%M%S')}")
        print(f"\n [RESULTS] Run saved to: {run_root}")

    except KeyboardInterrupt:
        print("[CONTINUOUS] Stop requested.")

    finally:
        if sys.exc_info()[0] is not None:
            for container in ("c1", "deployer", "supervisor"):
                try:
                    with (run_root / f"{container}-failure.log").open("w", encoding="utf-8") as output:
                        subprocess.run(
                            ["docker", "logs", "--tail", "200", container],
                            stdout=output, stderr=subprocess.STDOUT, timeout=15,
                        )
                except Exception as error:
                    print(f"[DIAGNOSTICS] Could not save {container} logs: {error}")
        append_event(run_root, f"CONTINUOUS_STOP {int(time.time())}")

        # Release the port before the next main() in this process binds it.
        if notify_server is not None:
            notify_server.shutdown()

        if currently_degraded:
            exit_lines = [f"[RESTORE-EXIT] {r['sw']}:{r['iface']} verified={r['ok']} actual={r['actual_delay']}/{r['actual_rate']}"
                          for link in currently_degraded
                          for r in set_link(link, topo.link_qdisc_params)]
            append_event(run_root, "\n".join(["DEGRADE_RESTORED_ON_EXIT"] + exit_lines))

        with session.lock:
            session.run_over = True

            for job in client_jobs:
                session.stop_ping(job)
                try:
                    job["proc"].wait(timeout=30)
                except subprocess.TimeoutExpired:
                    job["client_obj"].stopIperf(job["proc"])
                finally:
                    try:
                        job["f_out"].close()
                    except Exception:
                        pass

                zero_fill_if_empty(job["parts"][-1], job.get("part_start_ts", run_t0 or time.time()), job["client_name"])

                if run_t0 is not None:
                    continuous_out = iperf_continuous_dir / f"{job['client_name']}_continuous.json"
                    stitch_iperf_parts(job["parts"], continuous_out)
                    # The real window end, not run_t0 + N*ROTATE_S: snapshots
                    # drift late, so the theoretical bound clips the last tail.
                    last_snap_end = max(snap_end_times.values()) if snap_end_times else None
                    slice_iperf_json_to_snapshots(
                        run_root=run_root,
                        client_name=job["client_name"],
                        continuous_json_path=continuous_out,
                        run_t0=run_t0,
                        snap_start_times=snap_start_times,
                        max_end_ts=last_snap_end,
                        snap_end_times=snap_end_times,
                    )

        merge_all_snapshot_csvs(
            run_root=Path(run_root),
            out_csv_name="packet_flow_all.csv",
            delete_inputs=False,
        )
        merge_all_snapshot_ovs_csvs(
            run_root=Path(run_root),
            delete_inputs=False,
        )

        iperf_all = merge_all_iperf_jsons_to_csv(
            run_root=Path(run_root),
            snap_start_times=snap_start_times,
        )
        print(f" [IPERF] merged CSV: {iperf_all['files']} files, "
              f"{iperf_all['rows']} rows -> {iperf_all['out']}")

        # One continuous stream per client, bucketed into snapshots by the rows'
        # own unix timestamps rather than by splitting the files.
        ping_stats = snapshot_pings_to_single_csv(
            ping_dir=ping_dir,
            out_csv=run_root / "ping_all.csv",
            snap_boundaries=sorted(snap_start_times.items()),
            snap_end_times=snap_end_times,
        )
        print(f" [PING] merged CSV: {ping_stats['rows']} rows "
              f"({ping_stats.get('dropped', 0)} outside any window) "
              f"-> {run_root / 'ping_all.csv'}")
        
        if auto_start_containers:
            compose_down()

        try:
            cleanup()
        except Exception:
            pass

    return

if __name__ == "__main__":
    main()
