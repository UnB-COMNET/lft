import os, sys, time, json, subprocess, requests
from constants import CONFIG
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from onos_topologies.dash_topology.dash_topology import DashTopology
from onos_topologies.dash_topology import utils


def get_network_summary(topo):
    lines = ["\n" + "="*60]
    lines.append(" [LINK INSPECTION] Current Ports Status (tc)")

    links_to_check = [
        ("MG (s1)", "s1s0"), ("ES (s0)", "s0s1"),
        ("RJ (s2)", "s2s0"), ("ES (s0)", "s0s2")
    ]

    for sw_name, interface in links_to_check:
        sw_id = sw_name.split('(')[1].replace(')', '')
        cmd = f"docker exec {sw_id} tc qdisc show dev {interface}"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        clean_res = res.stdout.replace("qdisc netem 90d4: root refcnt 2 ", "").strip()
        lines.append(f" {sw_name} [{interface}]: {clean_res}")

    lines.append("="*60 + "\n")
    return "\n".join(lines)


def start_ollama():
    print(" [MOTOR] Running Ollama...")
    subprocess.run("systemctl start ollama", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    print(" [MOTOR] Pre-loading Qwen 3.6 in the memory...")
    try:
        requests.post("http://localhost:11434/api/generate", json={"model": "qwen3.6", "keep_alive": "30m"}, timeout=5)
    except requests.exceptions.ReadTimeout:
        pass
    except Exception as e:
        print(f" [AVISO] Failed to pre-load LLM: {e}")


# Brief: Applies a prio qdisc with 3 bands + netem on each band
# Band 1:1 - MaoLinkQuality probes (ethertype 0x3366): highest priority
# Band 1:2 - ICMP (ping): medium priority
# Band 1:3 - iperf TCP port 5201: lowest priority, rate capped at bottleneck_rate
def setup_prio_netem(sw: str, iface: str, delay_ms: int, jitter_ms: int = 0, bottleneck_rate: str = "10mbit"):
    cmds = [
        f"docker exec {sw} tc qdisc del dev {iface} root 2>/dev/null || true",
        f"docker exec {sw} tc qdisc add dev {iface} root handle 1: prio bands 3 priomap 2 2 2 2 2 2 2 2 1 1 1 1 1 1 1 1",
        # all bands share the same base delay and rate
        f"docker exec {sw} tc qdisc add dev {iface} parent 1:1 handle 10: netem delay {delay_ms}ms {jitter_ms}ms",
        f"docker exec {sw} tc qdisc add dev {iface} parent 1:2 handle 20: netem delay {delay_ms}ms {jitter_ms}ms",
        f"docker exec {sw} tc qdisc add dev {iface} parent 1:3 handle 30: netem delay {delay_ms}ms {jitter_ms}ms rate {bottleneck_rate}",
        # MaoLinkQuality probes (0x3366) -> band 1:1 (highest priority)
        f"docker exec {sw} tc filter add dev {iface} parent 1: protocol all prio 1 u32 match u16 0x3366 0xffff at -2 flowid 1:1",
        # ICMP -> band 1:2
        f"docker exec {sw} tc filter add dev {iface} parent 1: protocol ip prio 2 u32 match ip protocol 1 0xff flowid 1:2",
        # iperf TCP port 5201 (both directions) -> band 1:3 (lowest priority, rate limited)
        f"docker exec {sw} tc filter add dev {iface} parent 1: protocol ip prio 3 u32 match ip protocol 6 0xff match ip dport 5201 0xffff flowid 1:3",
        f"docker exec {sw} tc filter add dev {iface} parent 1: protocol ip prio 3 u32 match ip protocol 6 0xff match ip sport 5201 0xffff flowid 1:3",
    ]
    for cmd in cmds:
        subprocess.run(cmd, shell=True)


DOCKER_RUN = "sudo docker run --rm -d --network host -v /var/run/docker.sock:/var/run/docker.sock --name"

def start_container(name: str):
    subprocess.run(f"{DOCKER_RUN} {name} {name}", shell=True)


MODES = {
    '1': {"name": "cdn-qoe",  "onos": "2.5.0", "disable_fwd": True,  "apps": "proxyarp", "use_deployer": True},
    '2': {"name": "llm",      "onos": "2.5.0", "disable_fwd": True,  "apps": "proxyarp", "use_deployer": True, "pre_run": "ollama"},
    '3': {"name": "treshold", "onos": "2.5.0", "disable_fwd": True,  "apps": "proxyarp", "use_deployer": True},
    '4': {"name": "fwd",      "onos": "2.5.0", "disable_fwd": False, "apps": "",         "use_deployer": False},
    '5': {"name": "ospf",     "onos": "1.6",   "disable_fwd": True,  "apps": "proxyarp", "use_deployer": False}
}


def main(
    algorithm: str = None,
    hindering: str = None,
    auto_start: bool = False,
    run_name: str = None,
):
    """
        Step: Defining Experiment Constants
    """
    ROTATE_S = 60 # seconds per snapshot
    DEGRADED_ITERS = {2, 4, 6}
    server_name = "ds0"
    base_url_deployer = "http://127.0.0.1:5000/deploy"

    cfg_delay  = int(CONFIG["delay"].replace("ms", "")) # 10ms
    cfg_jitter = int(CONFIG["jitter"].replace("ms", "")) # 1ms

    # During degradation (snapshots 2, 4, 6):
    #   - probe/ICMP bands get DEGRADED_DELAY_MS so link-latency crosses the threshold
    #   - iperf band gets DEGRADED_RATE and DEGRADED_DELAY_MS
    # QoS tiers: normal MG<->ES=35mbit(4K), static RJ<->ES=5mbit(1080p), degraded MG<->ES=3mbit(720p)
    DEGRADED_DELAY_MS = 130
    DEGRADED_RATE = "3mbit"

    """
        Step: Input Handling - interactive if not provided, automated if passed as args
    """
    results_root = project_root / "results" / "iperf"
    results_root.mkdir(parents=True, exist_ok=True)

    if algorithm is None:
        while algorithm not in {'1', '2', '3', '4', '5'}:
            algorithm = input(
                "Choose a number for the experiment: "
                "\n[1] - cdn-qoe\n[2] - LLM\n[3] - Treshold\n[4] - fwd\n[5] - ospf\n"
            ).strip().lower()

    if hindering is None:
        while hindering not in {'degrade', 'take down'}:
            hindering = input(
                "Choose what you want to do with the MG <-> ES link: "
                "\n[1] - Degrade (lower throughput and increase delay)"
                "\n[2] - Take Down (for fwd and ifwd to notice)\n"
            ).strip().lower()
            if hindering == '1': hindering = 'degrade'
            elif hindering == '2': hindering = 'take down'

    mode_cfg = MODES.get(algorithm)
    service  = mode_cfg["name"]

    auto_start_containers = auto_start
    if not auto_start and mode_cfg.get("use_deployer", False):
        launch_choice = ''
        while launch_choice not in {'1', '2'}:
            launch_choice = input(
                "\nHow do you want to start the deployer and supervisor?"
                "\n[1] - Automatically (no logs visible)"
                "\n[2] - Manually (I'll start them in separate terminals)\n"
            ).strip()
        auto_start_containers = (launch_choice == '1')

    if run_name is None:
        custom_name = (input(
            "\nWould you like to add a custom name to the results directory? [y/N]\n"
        ).strip().lower() == "y")
        if custom_name:
            run_name = input("Please type in the name of the file: ").strip().lower()

    if run_name:
        run_root = results_root / run_name
    else:
        run_root = results_root / f"run_{time.strftime('%Y-%m-%d_%H-%M-%S')}"

    server_ip = "192.168.0.1" if algorithm != '5' else "192.168.10.10"

    run_root.mkdir(parents=True, exist_ok=True)
    os.environ["LFT_RESULTS"] = str(run_root)

    snaps_root = run_root / "snapshots"
    snaps_root.mkdir(parents=True, exist_ok=True)

    meta = {
        "algorithm": algorithm,
        "start_ts": int(time.time()),
        "rotate_s": f"{ROTATE_S}s"
    }
    ping_jobs = []

    (run_root / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    if mode_cfg.get("pre_run") == "ollama":
        start_ollama()

    try:
        utils.cleanup()

        onos_tag = f"onosproject/onos:{mode_cfg['onos']}"
        topo = DashTopology(config=CONFIG, results_dir=run_root, iperf=True, onos_version=onos_tag)

        topo.run(run_discovery=True, disable_fwd=mode_cfg["disable_fwd"])
        c1 = topo.controller

        if mode_cfg["apps"]:
            print(f" [SETUP] Activating extra apps: {mode_cfg['apps']}")
            c1.activateONOSApps(server_ip=topo.onos_ip,
                                command=f"app activate org.onosproject.{mode_cfg['apps']}")

        print(" [SETUP] Telemetry -> Real-Time Mode")
        comp = "com.maojianwei.link.quality.measurement.impl.MaoLinkQualityManager"
        karaf = "/home/onos/apache-karaf-4.2.14/bin/client -u karaf -p karaf"
        cmd_str = f"cfg set {comp} latencyAverageSize 1; cfg set {comp} probeInterval 500; cfg set {comp} calculateInterval 500"
        subprocess.run(f"echo '{cmd_str}' | sudo docker exec -i c1 {karaf}",
                       shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        topo.servers[server_name].startServer(port=5201)
        time.sleep(2)

        supervisor_image = "supervisor-quantization" if algorithm == '3' else "supervisor"

        if mode_cfg.get("use_deployer", False):
            if auto_start_containers:
                print("\n [SETUP] Starting deployer and supervisor containers...")
                start_container("deployer")
                subprocess.run(f"{DOCKER_RUN} supervisor {supervisor_image}", shell=True)
            else:
                print("\n [SETUP] Start the deployer and supervisor manually in separate terminals:")
                print("  deployer:   sudo docker run --rm -it --network host -v /var/run/docker.sock:/var/run/docker.sock --name deployer deployer")
                print(f"  supervisor: sudo docker run --rm -it --network host -v /var/run/docker.sock:/var/run/docker.sock --name supervisor {supervisor_image}")
            utils.sleep_countdown(t=60)
        else:
            print(f"\n [SETUP] Skipping deployer and supervisor (mode '{service}' does not use them).")
            time.sleep(2)

        """
            Step: Apply prio+netem on all inter-switch links.

            Link props before degradation:
              Normal (MG<->ES): 35mbit / 10ms  -> 4K        (snapshots 1,3,5)
              Degraded (MG<->ES): 3mbit / 130ms -> 720p     (snapshots 2,4,6)
              Static Bottleneck (RJ<->ES): 5mbit / 30ms -> 1080p (always)

            Degradation (snapshots 2,4,6):
              Probe/ICMP bands: delay=130ms -> RTT crosses supervisor threshold
              iperf band: delay=130ms, rate=3mbit

            prio ensures probes always dequeue before iperf for RTT measurements
        """
        print(" [SETUP] Applying prio+netem on all inter-switch links...")
        prio_links = [
            # (switch, iface,         delay_ms,         jitter_ms,   bottleneck_rate)
            ("s1", "s1s0", cfg_delay,        cfg_jitter, "35mbit"),   # MG -> ES  (normal)
            ("s0", "s0s1", cfg_delay,        cfg_jitter, "35mbit"),   # ES -> MG
            ("s2", "s2s0", cfg_delay + 20,   cfg_jitter, "5mbit"),    # RJ -> ES  (static bottleneck: 30ms / 5mbit)
            ("s0", "s0s2", cfg_delay + 20,   cfg_jitter, "5mbit"),    # ES -> RJ
            ("s3", "s3s1", cfg_delay,        cfg_jitter, "35mbit"),   # SP -> MG
            ("s1", "s1s3", cfg_delay,        cfg_jitter, "35mbit"),   # MG -> SP
            ("s3", "s3s2", cfg_delay,        cfg_jitter, "35mbit"),   # SP -> RJ
            ("s2", "s2s3", cfg_delay,        cfg_jitter, "35mbit"),   # RJ -> SP
        ]
        for sw, iface, delay_ms, jitter_ms, br in prio_links:
            setup_prio_netem(sw, iface, delay_ms, jitter_ms, br)
            print(f"  [prio] {sw}/{iface} -> delay={delay_ms}ms  rate={br}")

        msg = get_network_summary(topo)
        print(msg)
        utils.append_event(run_root, msg)
        utils.append_event(run_root, f"CONTINUOUS_START {int(time.time())}")

        """
            Step: Start ping monitoring
        """
        ping_dir = run_root / "ping_logs"
        ping_dir.mkdir(parents=True, exist_ok=True)

        print(" [SETUP] Pinging from cl to srv...")
        for client_name in topo.clients.keys():
            out_txt = ping_dir / f"{client_name}.txt"
            f_out = open(out_txt, "w", encoding="utf-8")
            cmd = ["sudo", "docker", "exec", client_name, "ping", server_ip, "-i", "0.5", "-D", "-O"]
            proc = subprocess.Popen(cmd, stdout=f_out, stderr=subprocess.STDOUT, text=True)
            ping_jobs.append((proc, f_out))

        """
            Step: Snapshot Loop
        """
        snap_idx = 1
        while snap_idx <= 6:
            ts = time.strftime("%Y%m%d-%H%M%S")
            snap_start_ts = time.time()
            snap_dir = snaps_root / f"snapshot_{snap_idx}"
            ovs_dir = snap_dir / "ovs"
            iperf_dir = snap_dir / "iperf"
            ovs_dir.mkdir(parents=True, exist_ok=True)
            iperf_dir.mkdir(parents=True, exist_ok=True)
            utils.append_event(run_root, f"SNAPSHOT_{snap_idx}_START {ts}")

            """
                Step: Degrade or take down link MG <-> ES.

                degrade:
                  All three bands on s1s0 and s0s1 get DEGRADED_DELAY_MS (130ms):
                  - Probe (1:1) + ICMP (1:2): 130ms delay -> RTT crosses supervisor threshold
                  - iperf (1:3): 130ms delay + 3mbit cap
                  prio still ensures probes are never queued behind iperf

                take down:
                  ip link set down/up; full link failure scenario
            """
            if hindering == 'degrade':
                try:
                    if snap_idx in DEGRADED_ITERS:
                        msg = f"\n [DEGRADE] Snapshot {snap_idx}: Degradando link MG <-> ES"
                        for sw, iface in [("s1", "s1s0"), ("s0", "s0s1")]:
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:1 handle 10: netem delay {DEGRADED_DELAY_MS}ms {cfg_jitter}ms", shell=True, check=True)
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:2 handle 20: netem delay {DEGRADED_DELAY_MS}ms {cfg_jitter}ms", shell=True, check=True)
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:3 handle 30: netem delay {DEGRADED_DELAY_MS}ms {cfg_jitter}ms rate {DEGRADED_RATE}", shell=True, check=True)
                    else:
                        msg = f"\n [NORMAL] Snapshot {snap_idx}: Link MG <-> ES operando normalmente"
                        for sw, iface in [("s1", "s1s0"), ("s0", "s0s1")]:
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:1 handle 10: netem delay {cfg_delay}ms {cfg_jitter}ms", shell=True, check=True)
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:2 handle 20: netem delay {cfg_delay}ms {cfg_jitter}ms", shell=True, check=True)
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:3 handle 30: netem delay {cfg_delay}ms {cfg_jitter}ms rate 35mbit", shell=True, check=True)

                    print(msg)
                    utils.append_event(run_root, msg)
                except Exception as e:
                    print(f" [WARNING] Failed to change link properties: {e}")

            elif hindering == 'take down':
                try:
                    if snap_idx in DEGRADED_ITERS:
                        msg  = f" [FAILURE] Snapshot {snap_idx}: Taking down link MG <-> ES (IP LINK DOWN)"
                        cmd1 = "sudo docker exec s1 ip link set s1s0 down"
                        cmd2 = "sudo docker exec s0 ip link set s0s1 down"
                    else:
                        msg  = f" [RECOVERY] Snapshot {snap_idx}: Restoring link MG <-> ES (IP LINK UP)"
                        cmd1 = "sudo docker exec s1 ip link set s1s0 up"
                        cmd2 = "sudo docker exec s0 ip link set s0s1 up"

                    print(msg)
                    utils.append_event(run_root, msg)
                    subprocess.run(cmd1, shell=True, check=True)
                    subprocess.run(cmd2, shell=True, check=True)
                except Exception as e:
                    print(f" [WARNING] Falha ao alterar as propriedades do link: {e}")

            link_properties = subprocess.run("sudo tc qdisc show", shell=True, check=True, capture_output=True, text=True)
            utils.append_event(run_root, f"SNAPSHOT_{snap_idx}: {link_properties}")

            service = {
                '1': 'cdn-qoe', '2': 'llm', '3': 'treshold', '4': 'fwd', '5': 'ospf'
            }.get(algorithm, 'unknown')

            msg = " [WAIT] Waiting for ONOS telemetry (5s)..."
            print(msg)
            utils.append_event(run_root, msg)
            time.sleep(5)

            msg = get_network_summary(topo)
            print(msg)
            utils.append_event(run_root, msg)

            if snap_idx == 1 and mode_cfg.get("use_deployer", False):
                for raw_ip in topo.client_ip_range:
                    clean_ip = raw_ip.split('/')[0].strip()
                    deployer_service = "cdn-qoe" if service == "treshold" else service
                    payload = {"intent": f"define intent q1: from endpoint('{clean_ip}') add service('{deployer_service}')"}
                    print(f"\n [SNAPSHOT 1] Sending intent for {clean_ip}...")
                    try:
                        response = requests.post(base_url_deployer, json=payload, timeout=30)
                        if response.status_code in [200, 201]:
                            data = response.json()
                            for ip, info in data.get('controller_responses', {}).items():
                                flows = info.get('output', {}).get('responses', [])
                                print(f" [DEPLOYER] {len(flows)} flows installed by ONOS ({ip})")
                        else:
                            print(f" [ERROR] Deployer returned {response.status_code}")
                    except Exception as e:
                        print(f" [ERROR] Request error: {e}")

            print(" [WAIT] Aguardando programação dos flows nos switches (15s)...")
            time.sleep(15)

            """
                Step: Run iperf per snapshot with JSON output (-J)
                No -b flag so TCP uses all available bandwidth up to the netem rate cap
                Naming pattern: cl0%{snap_idx}.json inside snapshot_{idx}/iperf/
            """
            print(f" [SETUP] Starting iperf for snapshot {snap_idx} ({ROTATE_S}s)...")
            iperf_jobs = []
            for client_name in topo.clients.keys():
                out_json = iperf_dir / f"{client_name}%{snap_idx}.json"
                f_out    = open(out_json, "w", encoding="utf-8")
                cmd      = ["sudo", "docker", "exec", client_name, "bash", "-lc",
                            f"iperf3 -c {server_ip} -p 5201 -t {ROTATE_S} -i 1 -J --connect-timeout 10000"]
                proc = subprocess.Popen(cmd, stdout=f_out, stderr=subprocess.STDOUT, text=True)
                iperf_jobs.append((proc, f_out))

            print(f" [WAIT] Snapshot {snap_idx} running for {ROTATE_S}s...")
            time.sleep(ROTATE_S)

            for proc, f_out in iperf_jobs:
                try:
                    proc.wait(timeout=ROTATE_S + 30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                finally:
                    try:
                        f_out.close()
                    except Exception:
                        pass

            iperf_csv   = iperf_dir / "iperf_flow.csv"
            iperf_stats = utils.snapshot_iperf_jsons_to_single_csv(
                iperf_dir=iperf_dir,
                out_csv=iperf_csv,
                snap_start_ts=snap_start_ts,
            )
            print(f" [IPERF] snap {snap_idx}: {iperf_stats}")

            utils.snapshot_ovs_state(
                switch_names=[sw.getNodeName() for sw in topo.switches.values()],
                outdir=ovs_dir,
                of_version="OpenFlow13",
                parse_csv=True,
                snapshot_idx=snap_idx,
            )

            utils.append_event(run_root, f"SNAPSHOT_{snap_idx}_END {time.strftime('%Y%m%d-%H%M%S')}")
            snap_idx += 1

    except KeyboardInterrupt:
        print("[CONTINUOUS] Stop requested.")

    finally:
        utils.append_event(run_root, f"CONTINUOUS_STOP {int(time.time())}")

        utils.merge_all_snapshot_csvs(
            run_root=Path(run_root),
            out_csv_name="packet_flow_all.csv",
            delete_inputs=False,
        )

        utils.merge_all_snapshot_ovs_csvs(
            run_root=Path(run_root),
            delete_inputs=False,
        )

        iperf_final = utils.merge_all_snapshot_csvs(
            run_root=Path(run_root),
            out_csv_name="iperf_flow_all.csv",
            glob_pattern="snapshots/snapshot_*/iperf/iperf_flow.csv",
            delete_inputs=False,
        )
        print(f" [IPERF] merged: {iperf_final}")

        for proc, f_out in ping_jobs:
            proc.kill()
            try:
                f_out.close()
            except Exception:
                pass

        ping_csv_out = run_root / "ping_flow_all.csv"
        ping_stats   = utils.snapshot_pings_to_single_csv(
            ping_dir=run_root / "ping_logs",
            out_csv=ping_csv_out
        )
        print(f" [RESULTADOS] CSV de Ping gerado com {ping_stats['rows']} linhas.")

        if auto_start_containers:
            for container in ("supervisor", "deployer"):
                subprocess.run(f"sudo docker rm -f {container} 2>/dev/null || true", shell=True)

        try:
            utils.cleanup()
        except Exception:
            pass

    return


if __name__ == "__main__":
    main()
