import sys
import json
import os
import subprocess
import time
from pathlib import Path

import requests

# Resolve checkout imports when executed directly
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    __package__ = "onos_topologies.experiments.diamond"

from onos_topologies.experiments.runtime import append_event, sleep_countdown
from onos_topologies.infrastructure.containers import cleanup
from onos_topologies.infrastructure.traffic_control import create_prio_netem
from onos_topologies.measurements.csv_io import merge_all_snapshot_csvs
from onos_topologies.measurements.iperf import snapshot_iperf_jsons_to_single_csv
from onos_topologies.measurements.ovs import (
    merge_all_snapshot_ovs_csvs,
    snapshot_ovs_state,
)
from onos_topologies.measurements.ping import snapshot_pings_to_single_csv
from onos_topologies.topologies.configs.diamond import CONFIG



project_root = Path(__file__).resolve().parents[3]

from onos_topologies.topologies.topology import Topology


# Brief: Formats a fixed-width tag prefix so every printed line starts at the same column
def log(tag: str, msg: str = "") -> str:
    return f"{f'[{tag}]':<13} {msg}"


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


# Ollama now runs on its own GPU VM (see OLLAMA_URL in the deployer's .env), not locally
OLLAMA_URL = "http://gpu.mfcaetano.lan:11434"

def start_ollama():
    print(log("MOTOR", "Pre-loading Qwen 3.6 on the Ollama VM..."))
    try:
        requests.post(f"{OLLAMA_URL}/api/generate", json={"model": "qwen3.6", "keep_alive": "30m"}, timeout=5)
    except requests.exceptions.ReadTimeout:
        pass
    except Exception as e:
        print(log("AVISO", f"Failed to pre-load LLM: {e}"))


# Brief: Applies a prio qdisc with 3 bands + netem on each band
# Band 1:1 - MaoLinkQuality probes (ethertype 0x3366): highest priority
# Band 1:2 - ICMP (ping): medium priority
# Band 1:3 - iperf TCP port 5201: lowest priority, rate capped at bottleneck_rate
def setup_prio_netem(sw: str, iface: str, delay_ms: int, jitter_ms: int = 0, bottleneck_rate: str = "10mbit"):
    interfaces = {iface: (bottleneck_rate, f"{delay_ms}ms", f"{jitter_ms}ms")}
    create_prio_netem(sw, interfaces, tcp_ports=(5201,))


DOCKER_RUN = "sudo docker run --rm -d --network host -v /var/run/docker.sock:/var/run/docker.sock --name"

def start_container(name: str):
    subprocess.run(f"{DOCKER_RUN} {name} {name}", shell=True)


MODES = {
    '1': {"name": "cdn-qoe",  "onos": "2.5.0", "disable_fwd": True,  "apps": "proxyarp", "use_deployer": True},
    '2': {"name": "llm",      "onos": "2.5.0", "disable_fwd": True,  "apps": "proxyarp", "use_deployer": True, "pre_run": "ollama"},
    '3': {"name": "treshold", "onos": "2.5.0", "disable_fwd": True,  "apps": "proxyarp", "use_deployer": True},
    '4': {"name": "fwd",      "onos": "2.5.0", "disable_fwd": False, "apps": "",         "use_deployer": False},
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
        while algorithm not in MODES:
            algorithm = input(
                "Choose a number for the experiment: "
                "\n[1] - cdn-qoe\n[2] - LLM\n[3] - Treshold\n[4] - fwd\n"
            ).strip().lower()

    if algorithm not in MODES:
        raise ValueError(f"Unknown mode: {algorithm}")

    if hindering is None:
        while hindering not in {'degrade', 'take down'}:
            hindering = input(
                "Choose what you want to do with the MG <-> ES link: "
                "\n[1] - Degrade (lower throughput and increase delay)"
                "\n[2] - Take Down (for fwd and ifwd to notice)\n"
            ).strip().lower()
            if hindering == '1': hindering = 'degrade'
            elif hindering == '2': hindering = 'take down'

    mode_cfg = MODES[algorithm]
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

    server_ip = "192.168.0.1"

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
        cleanup()

        onos_tag = f"onosproject/onos:{mode_cfg['onos']}"
        topo = Topology(config=CONFIG, results_dir=run_root, iperf=True, onos_version=onos_tag)

        topo.run(run_discovery=True, disable_fwd=mode_cfg["disable_fwd"])
        c1 = topo.controller

        if mode_cfg["apps"]:
            print(log("SETUP", f"Activating extra apps: {mode_cfg['apps']}"))
            c1.activateONOSApps(server_ip=topo.onos_ip,
                                command=f"app activate org.onosproject.{mode_cfg['apps']}")

        print(log("SETUP", "Telemetry -> Real-Time Mode"))
        comp = "com.maojianwei.link.quality.measurement.impl.MaoLinkQualityManager"
        karaf = "/home/onos/apache-karaf-4.2.14/bin/client -u karaf -p karaf"
        cmd_str = f"cfg set {comp} latencyAverageSize 1; cfg set {comp} probeInterval 500; cfg set {comp} calculateInterval 500"
        # Passing the command as an argument (not via stdin pipe with -i) keeps Karaf's
        # JLine console non-interactive, so it never puts our controlling tty into raw
        # mode â€” piping through `-i` left the terminal missing \r on every \n afterwards
        # (the "staircase" effect), corrupting every print() for the rest of the run.
        subprocess.run(f'sudo docker exec c1 {karaf} "{cmd_str}"',
                       shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        topo.servers[server_name].startServer(port=5201)
        time.sleep(2)

        supervisor_image = "supervisor-quantization" if algorithm == '3' else "supervisor"

        if mode_cfg.get("use_deployer", False):
            if auto_start_containers:
                print("\n" + log("SETUP", "Starting deployer and supervisor containers..."))
                start_container("deployer")
                subprocess.run(f"{DOCKER_RUN} supervisor {supervisor_image}", shell=True)
            else:
                print("\n" + log("SETUP", "Start the deployer and supervisor manually in separate terminals:"))
                indent = " " * len(log(""))
                print(indent + "deployer:   sudo docker run --rm -it --network host -v /var/run/docker.sock:/var/run/docker.sock --name deployer deployer")
                print(indent + f"supervisor: sudo docker run --rm -it --network host -v /var/run/docker.sock:/var/run/docker.sock --name supervisor {supervisor_image}")
            sleep_countdown(t=60)
        else:
            print("\n" + log("SETUP", f"Skipping deployer and supervisor (mode '{service}' does not use them)."))
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
        print(log("SETUP", "Applying prio+netem on all inter-switch links..."))
        prio_links = [
            # (switch, iface,         delay_ms,         jitter_ms,   bottleneck_rate)
            ("s1", "s1s0", cfg_delay,        cfg_jitter, "35mbit"), # MG -> ES  (normal)
            ("s0", "s0s1", cfg_delay,        cfg_jitter, "35mbit"), # ES -> MG
            ("s2", "s2s0", cfg_delay + 20,   cfg_jitter, "5mbit"), # RJ -> ES  (static bottleneck: 30ms / 5mbit)
            ("s0", "s0s2", cfg_delay + 20,   cfg_jitter, "5mbit"), # ES -> RJ
            ("s3", "s3s1", cfg_delay,        cfg_jitter, "35mbit"), # SP -> MG
            ("s1", "s1s3", cfg_delay,        cfg_jitter, "35mbit"), # MG -> SP
            ("s3", "s3s2", cfg_delay,        cfg_jitter, "35mbit"), # SP -> RJ
            ("s2", "s2s3", cfg_delay,        cfg_jitter, "35mbit"), # RJ -> SP
        ]
        for sw, iface, delay_ms, jitter_ms, br in prio_links:
            setup_prio_netem(sw, iface, delay_ms, jitter_ms, br)
            print(log("prio", f"{sw}/{iface} -> delay={delay_ms}ms  rate={br}"))

        msg = get_network_summary(topo)
        append_event(run_root, msg)
        append_event(run_root, f"CONTINUOUS_START {int(time.time())}")

        """
            Step: Start ping monitoring
        """
        ping_dir = run_root / "ping_logs"
        ping_dir.mkdir(parents=True, exist_ok=True)

        print(log("SETUP", "Pinging from cl to srv..."))
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
            append_event(run_root, f"SNAPSHOT_{snap_idx}_START {ts}")

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
                        msg = "\n" + log("DEGRADE", f"Snapshot {snap_idx}: Degradando link MG <-> ES")
                        for sw, iface in [("s1", "s1s0"), ("s0", "s0s1")]:
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:1 handle 10: netem delay {DEGRADED_DELAY_MS}ms {cfg_jitter}ms", shell=True, check=True)
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:2 handle 20: netem delay {DEGRADED_DELAY_MS}ms {cfg_jitter}ms", shell=True, check=True)
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:3 handle 30: netem delay {DEGRADED_DELAY_MS}ms {cfg_jitter}ms rate {DEGRADED_RATE}", shell=True, check=True)
                    else:
                        msg = "\n" + log("NORMAL", f"Snapshot {snap_idx}: Link MG <-> ES operando normalmente")
                        for sw, iface in [("s1", "s1s0"), ("s0", "s0s1")]:
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:1 handle 10: netem delay {cfg_delay}ms {cfg_jitter}ms", shell=True, check=True)
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:2 handle 20: netem delay {cfg_delay}ms {cfg_jitter}ms", shell=True, check=True)
                            subprocess.run(f"docker exec {sw} tc qdisc change dev {iface} parent 1:3 handle 30: netem delay {cfg_delay}ms {cfg_jitter}ms rate 35mbit", shell=True, check=True)

                    print(msg)
                    append_event(run_root, msg)
                except Exception as e:
                    print(log("WARNING", f"Failed to change link properties: {e}"))

            elif hindering == 'take down':
                try:
                    if snap_idx in DEGRADED_ITERS:
                        msg  = log("FAILURE", f"Snapshot {snap_idx}: Taking down link MG <-> ES (IP LINK DOWN)")
                        cmd1 = "sudo docker exec s1 ip link set s1s0 down"
                        cmd2 = "sudo docker exec s0 ip link set s0s1 down"
                    else:
                        msg  = log("RECOVERY", f"Snapshot {snap_idx}: Restoring link MG <-> ES (IP LINK UP)")
                        cmd1 = "sudo docker exec s1 ip link set s1s0 up"
                        cmd2 = "sudo docker exec s0 ip link set s0s1 up"

                    print(msg)
                    append_event(run_root, msg)
                    subprocess.run(cmd1, shell=True, check=True)
                    subprocess.run(cmd2, shell=True, check=True)
                except Exception as e:
                    print(log("WARNING", f"Falha ao alterar as propriedades do link: {e}"))

            link_properties = subprocess.run("sudo tc qdisc show", shell=True, check=True, capture_output=True, text=True)
            append_event(run_root, f"SNAPSHOT_{snap_idx}: {link_properties}")

            msg = log("WAIT", "Waiting for ONOS telemetry (5s)...")
            print(msg)
            append_event(run_root, msg)
            time.sleep(5)

            msg = get_network_summary(topo)
            append_event(run_root, msg)

            if snap_idx == 1 and mode_cfg.get("use_deployer", False):
                for raw_ip in topo.client_ip_range:
                    clean_ip = raw_ip.split('/')[0].strip()
                    deployer_service = "cdn-qoe" if service == "treshold" else service
                    payload = {"intent": f"define intent q1: from endpoint('{clean_ip}') add service('{deployer_service}')"}
                    print("\n" + log("SNAPSHOT 1", f"Sending intent for {clean_ip}..."))
                    try:
                        response = requests.post(base_url_deployer, json=payload, timeout=60)
                        if response.status_code in [200, 201]:
                            data = response.json()
                            for ip, info in data.get('controller_responses', {}).items():
                                flows = info.get('output', {}).get('responses', [])
                                print(log("DEPLOYER", f"{len(flows)} flows installed by ONOS ({ip})"))
                        else:
                            print(log("ERROR", f"Deployer returned {response.status_code}"))
                    except Exception as e:
                        print(log("ERROR", f"Request error: {e}"))

            print(log("WAIT", "Aguardando programaÃ§Ã£o dos flows nos switches (15s)..."))
            time.sleep(15)

            """
                Step: Run iperf per snapshot with JSON output (-J)
                No -b flag so TCP uses all available bandwidth up to the netem rate cap
                Naming pattern: cl0%{snap_idx}.json inside snapshot_{idx}/iperf/
            """
            print(log("SETUP", f"Starting iperf for snapshot {snap_idx} ({ROTATE_S}s)..."))
            iperf_jobs = []
            for client_name in topo.clients.keys():
                out_json = iperf_dir / f"{client_name}%{snap_idx}.json"
                f_out    = open(out_json, "w", encoding="utf-8")
                cmd      = ["sudo", "docker", "exec", client_name, "bash", "-lc",
                            f"iperf3 -c {server_ip} -p 5201 -t {ROTATE_S} -i 1 -J --connect-timeout 10000"]
                proc = subprocess.Popen(cmd, stdout=f_out, stderr=subprocess.STDOUT, text=True)
                iperf_jobs.append((proc, f_out))

            print(log("WAIT", f"Snapshot {snap_idx} running for {ROTATE_S}s..."))
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
            iperf_stats = snapshot_iperf_jsons_to_single_csv(
                iperf_dir=iperf_dir,
                out_csv=iperf_csv,
                snap_start_ts=snap_start_ts,
            )
            print(log("IPERF", f"snap {snap_idx}: {iperf_stats}"))

            snapshot_ovs_state(
                switch_names=[sw.getNodeName() for sw in topo.switches.values()],
                outdir=ovs_dir,
                of_version="OpenFlow13",
                parse_csv=True,
                snapshot_idx=snap_idx,
            )

            append_event(run_root, f"SNAPSHOT_{snap_idx}_END {time.strftime('%Y%m%d-%H%M%S')}")
            snap_idx += 1

    except KeyboardInterrupt:
        print(log("CONTINUOUS", "Stop requested."))

    finally:
        append_event(run_root, f"CONTINUOUS_STOP {int(time.time())}")

        merge_all_snapshot_csvs(
            run_root=Path(run_root),
            out_csv_name="packet_flow_all.csv",
            delete_inputs=False,
        )

        merge_all_snapshot_ovs_csvs(
            run_root=Path(run_root),
            delete_inputs=False,
        )

        iperf_final = merge_all_snapshot_csvs(
            run_root=Path(run_root),
            out_csv_name="iperf_flow_all.csv",
            glob_pattern="snapshots/snapshot_*/iperf/iperf_flow.csv",
            delete_inputs=False,
        )
        print(log("IPERF", f"merged: {iperf_final}"))

        for proc, f_out in ping_jobs:
            proc.kill()
            try:
                f_out.close()
            except Exception:
                pass

        ping_csv_out = run_root / "ping_flow_all.csv"
        ping_stats   = snapshot_pings_to_single_csv(
            ping_dir=run_root / "ping_logs",
            out_csv=ping_csv_out
        )
        print(log("RESULTADOS", f"CSV de Ping gerado com {ping_stats['rows']} linhas."))

        if auto_start_containers:
            for container in ("supervisor", "deployer"):
                subprocess.run(f"sudo docker rm -f {container} 2>/dev/null || true", shell=True)

        try:
            cleanup()
        except Exception:
            pass

    return


if __name__ == "__main__":
    main()
