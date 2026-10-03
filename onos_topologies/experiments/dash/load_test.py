import json
import logging
import os
import random
import subprocess
import sys
import time
from pathlib import Path

# Resolve checkout imports when executed directly
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    __package__ = "onos_topologies.experiments.dash"

from onos_topologies.experiments.runtime import append_event
from onos_topologies.infrastructure.containers import cleanup
from onos_topologies.measurements.csv_io import merge_all_snapshot_csvs
from onos_topologies.measurements.hardware import hw_sample, hw_state
from onos_topologies.measurements.ovs import (
    merge_all_snapshot_ovs_csvs,
    snapshot_ovs_state,
)
from onos_topologies.measurements.pcap import snapshot_pcaps_to_single_csv

project_root = Path(__file__).resolve().parents[3]

from onos_topologies.topologies.configs.dash import DEFAULT_CONFIG
from onos_topologies.topologies.topology import Topology


def start_dash_clients_batch(client_batch: list[str], server_ips: list[str], scheme: str = "http") -> list[subprocess.Popen]:
    procs: list[subprocess.Popen] = []

    for cname in client_batch:
        srv = random.choice(server_ips)
        cmd = [
            "sudo", "docker", "exec", cname, "bash", "-lc",
            f"/usr/local/bin/dash-client -y -hostname {srv} -scheme {scheme}",
        ]
        print(f"[DIAG] start {cname} -> server {srv}")
        procs.append(subprocess.Popen(cmd))

    return procs


# Brief: Cumulative DASH load in four snapshots
# Params:
#   bool yes: Answer yes to the discovery question
#   int duration: Seconds per snapshot (default 300)
#   int clients: Clients in the last snapshot (default 100); the others take 25, 50 and 75% of it
def main(yes: bool = False, duration: int = None, clients: int = None):
    ROTATE_S = duration or 300
    HW_POLL_S = 5
    DISPLAY_FILTER = None
    BPF_FILTER = "(tcp port 80 or tcp port 443 or icmp)"

    # Cumulative load plan: 25, 50, 75, 100
    MAX_CLIENTS = clients or 100
    BATCH_SIZES = [MAX_CLIENTS * k // 4 for k in (1, 2, 3, 4)]

    results_root = project_root / "results" / "dash"
    results_root.mkdir(parents=True, exist_ok=True)

    run_discovery = yes or (input("Controller host discovery? [y/N] ").strip().lower() == "y")

    run_root = results_root / f"run_{time.strftime('%Y-%m-%d_%H-%M-%S')}"
    run_root.mkdir(parents=True, exist_ok=True)
    os.environ["LFT_RESULTS"] = str(run_root)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(run_root / "run.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("lft")

    snaps_root = run_root / "snapshots"
    snaps_root.mkdir(parents=True, exist_ok=True)

    meta = {
        "run_id": run_root.name,
        "start_ts": int(time.time()),
        "run_discovery": run_discovery,
        "run_root": str(run_root),
        "rotate_s": ROTATE_S,
        "hw_poll_s": HW_POLL_S,
        "bpf_filter": BPF_FILTER,
        "display_filter": DISPLAY_FILTER,
        "experiment": f"4 snapshots, cumulative clients {'/'.join(map(str, BATCH_SIZES))}, random server among ALL servers",
        "max_clients": MAX_CLIENTS,
    }
    (run_root / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        log.info("[RESET] cleanup() (pre)")
        cleanup()

        topo = Topology(config=DEFAULT_CONFIG, results_dir=run_root)
        topo.run(run_discovery=run_discovery)

        server_ips = [str(ip) for ip in topo.server_ip_range]
        if not server_ips:
            raise RuntimeError("No server IPs found in topo.server_ip_range")

        append_event(run_root, f"EXPERIMENT_START {int(time.time())}")

        client_names = sorted(topo.clients.keys())
        client_pool = client_names[:MAX_CLIENTS]
        log.info(f"[EXPERIMENT] ROTATE_S={ROTATE_S}s, HW_POLL_S={HW_POLL_S}s, servers={server_ips}, total_clients_pool={len(client_pool)}")

        for snap_idx, k in enumerate(BATCH_SIZES, start=1):
            ts = time.strftime("%Y%m%d-%H%M%S")
            snap_dir = snaps_root / f"snapshot_{snap_idx}"
            ovs_dir = snap_dir / "ovs"
            tcpdump_dir = snap_dir / "tcpdump"
            ovs_dir.mkdir(parents=True, exist_ok=True)
            tcpdump_dir.mkdir(parents=True, exist_ok=True)

            append_event(run_root, f"SNAPSHOT_{snap_idx}_START {ts}")

            # Start tcpdump on each switch, writing into this snapshot tcpdump dir
            for pop, sw in topo.switches.items():
                swname = sw.getNodeName()
                capture_path = f"/results/dash/snapshots/snapshot_{snap_idx}/tcpdump"

                nodes = list(topo.hosts_by_pop.get(pop, []))
                if not nodes:
                    log.info(f"[tcpdump] skip {swname} (no host-facing nodes for pop={pop})")
                    continue

                sw.collectFlowsTcpdump(
                    nodes=nodes,
                    path=capture_path,
                    rotateInterval=ROTATE_S,
                    sniffAll=False,
                    bpf_filter=BPF_FILTER,
                    snapshot_idx=snap_idx,
                )

            # Cumulative batch: first k clients (includes previous ones)
            k_eff = min(k, len(client_pool))
            batch = client_pool[:k_eff]
            log.info(f"[EXPERIMENT] snapshot_{snap_idx}: running cumulative dash-client k={k_eff}")

            # Start clients (async), then keep the window open for ROTATE_S while sampling HW
            procs: list[subprocess.Popen] = []
            if batch:
                procs = start_dash_clients_batch(batch, server_ips, scheme="http")

            st = list(hw_state()) # [idle_cpu, total_cpu, disk_read_total, disk_write_total]
            samples = max(1, int(ROTATE_S // HW_POLL_S))
            remainder = ROTATE_S - samples * HW_POLL_S

            # Wait ROTATE_S seconds while sampling HW every HW_POLL_S seconds
            for _ in range(samples):
                time.sleep(HW_POLL_S)
                hw_sample(Path(run_root) / "hw.csv", snap_idx, st)

            if remainder > 0:
                time.sleep(remainder)
                hw_sample(Path(run_root) / "hw.csv", snap_idx, st)

            time.sleep(2)

            # Snapshot OVS/OpenFlow state into snapshot_X/ovs/
            snapshot_ovs_state(
                switch_names=[sw.getNodeName() for sw in topo.switches.values()],
                outdir=ovs_dir,
                of_version="OpenFlow13",
                parse_csv=True,
                snapshot_idx=snap_idx,
            )

            # Build one merged CSV for this snapshot
            packet_flow_csv = tcpdump_dir / "packet_flow.csv"
            stats = snapshot_pcaps_to_single_csv(
                tcpdump_dir=tcpdump_dir,
                out_csv=packet_flow_csv,
                display_filter=DISPLAY_FILTER,
                delete_pcaps=True,
            )
            log.info(
                f"[PCAP->CSV] snapshot_{snap_idx}: pcaps={stats['pcaps']} rows={stats['rows']} -> {packet_flow_csv}"
            )

            append_event(run_root, f"SNAPSHOT_{snap_idx}_END {time.strftime('%Y%m%d-%H%M%S')}")
            log.info(f"[OK] snapshot_{snap_idx} -> {snap_dir}")

    except KeyboardInterrupt:
        log.info("[EXPERIMENT] Stop requested.")

    finally:
        append_event(run_root, f"EXPERIMENT_STOP {int(time.time())}")

        # Merge all snapshot_X/tcpdump/packet_flow.csv into one run_root/packet_flow_all.csv
        final_stats = merge_all_snapshot_csvs(
            run_root=Path(run_root),
            out_csv_name="packet_flow_all.csv",
            delete_inputs=False,
        )
        log.info(
            f"[CSV-MERGE] files={final_stats['files']} rows={final_stats['rows']} -> "
            f"{Path(run_root) / 'packet_flow_all.csv'}"
        )

        ovs_stats = merge_all_snapshot_ovs_csvs(
            run_root=Path(run_root),
            delete_inputs=False,
        )
        log.info(f"[OVS-MERGE] flows={ovs_stats['flows']} ports={ovs_stats['ports']}")

        log.info("[RESET] cleanup() (post)")
        try:
            cleanup()
        except Exception:
            pass

    raise SystemExit(0)


if __name__ == "__main__":
    main()
