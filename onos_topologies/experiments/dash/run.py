import json
import logging
import os
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

from onos_topologies.topologies.configs.dash import DEBUG_CONFIG, DEFAULT_CONFIG
from onos_topologies.topologies.topology import Topology


def main():
    ROTATE_S = 120 # 2 minutes per snapshot
    HW_POLL_S = 5 
    DISPLAY_FILTER = None
    #BPF_FILTER = ""
    BPF_FILTER = "(tcp port 80 or tcp port 443 or icmp)"

    results_root = project_root / "results" / "dash"
    results_root.mkdir(parents=True, exist_ok=True)

    disable_fwd = (input("Disable ONOS Active Forwarding? [y/N] ").strip().lower() == "y")
    run_discovery = (input("Controller host discovery? [y/N] ").strip().lower() == "y")
    run_capture = (input("Would you like to capture traffic and flow information from the network? [y/N] ").strip().lower() == "y")
    run_default = (input("Would you like to run the default topology? (Debug, if NOT) [y/N] ").strip().lower() == "y")

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
        "rotate_s": f"{ROTATE_S}s",
        "bpf_filter": BPF_FILTER,
    }
    (run_root / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        log.info("[RESET] cleanup() (pre)")
        cleanup() 

        # Creates and run the topology
        if (run_default):
            topo = Topology(config=DEFAULT_CONFIG, results_dir=run_root)
        else:
            topo = Topology(config=DEBUG_CONFIG, results_dir=run_root)
        topo.run(run_discovery=run_discovery, disable_fwd=disable_fwd)

        # Prints the starting time of execution and saves the stdout string into events.log
        append_event(run_root, f"CONTINUOUS_START {int(time.time())}")


        # ONLY inspects traffic if user said so
        if (run_capture):
            log.info(f"[CONTINUOUS] Snapshot every {ROTATE_S} minutes. Ctrl+C to stop.")
            snap_idx = 1
            # Each execution corresponds to a snapshot
            while True:
                ts = time.strftime("%Y%m%d-%H%M%S")
                snap_dir = snaps_root / f"snapshot_{snap_idx}"
                ovs_dir = snap_dir / "ovs"
                pcaps_dir = snap_dir / "tcpdump"
                ovs_dir.mkdir(parents=True, exist_ok=True)
                pcaps_dir.mkdir(parents=True, exist_ok=True)

                append_event(run_root, f"SNAPSHOT_{snap_idx}_START {ts}")

                # Start tcpdump on each switch interface, writing straight into this snapshot/
                for pop, sw in topo.switches.items():
                    capture_path = f"/results/dash/snapshots/snapshot_{snap_idx}/tcpdump"

                    nodes = list(topo.hosts_by_pop.get(pop, []))

                    # Start a new tcpdump every snapshot (per interface). It auto-stops after ROTATE_S via the timeout flag, so it doesn't accumulate!!
                    sw.collectFlowsTcpdump(
                        nodes=nodes,
                        path=capture_path,
                        rotateInterval=ROTATE_S,
                        sniffAll=False,
                        bpf_filter=BPF_FILTER,
                        snapshot_idx=snap_idx,
                    )

                st = list(hw_state()) # st = [idle_cpu, total_cpu, disk_read_bytes_total, disk_write_bytes_total]
                samples = max(1, int(ROTATE_S // HW_POLL_S)) # ex: ROTATE_S = 600s and HW_POLL_S = 5s => 120 samples

                # This loop lasts ROTATE_S seconds (same duration as the tcpdumps) while sampling HW every HW_POLL_S seconds
                for _ in range(samples):
                    time.sleep(HW_POLL_S)
                    hw_sample(Path(run_root) / "hw.csv", snap_idx, st)

                time.sleep(2)

                # OVS snapshot for every switch (end of snapshot window)
                snapshot_ovs_state(
                    switch_names=[sw.getNodeName() for sw in topo.switches.values()],
                    outdir=ovs_dir,
                    of_version="OpenFlow13",
                    parse_csv=True,
                    snapshot_idx=snap_idx,
                )

                # Build ONE merged CSV for this snapshot from the .pcaps generated per tcpdump
                packet_flow_csv = pcaps_dir / "packet_flow.csv"
                stats = snapshot_pcaps_to_single_csv(
                    tcpdump_dir=pcaps_dir,
                    out_csv=packet_flow_csv,
                    display_filter=DISPLAY_FILTER,
                    delete_pcaps=True, 
                )

                log.info(f"[PCAP->CSV] snapshot_{snap_idx}: pcaps={stats['pcaps']} rows={stats['rows']} -> {packet_flow_csv}")
                append_event(run_root, f"SNAPSHOT_{snap_idx}_END {time.strftime('%Y%m%d-%H%M%S')}")
                snap_idx += 1
        else:
            # Infinite loop without traffic capture. Runs forever, until user presses Ctrl + C
            while True:
                time.sleep(ROTATE_S)

    except KeyboardInterrupt:
        log.info("[CONTINUOUS] Stop requested.")

    finally:
        append_event(run_root, f"CONTINUOUS_STOP {int(time.time())}")

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

        try:
            cleanup()
        except Exception:
            pass

    raise SystemExit(0)


if __name__ == "__main__":
    main()
