"""Create a topology for manual use without running measurements"""

import subprocess
import sys
from pathlib import Path

# Use the checkout when this file is executed directly
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onos_topologies.experiments.diamond.run import MODES
from onos_topologies.experiments.registry import mode_key
from onos_topologies.topologies.configs.diamond import CONFIG
from onos_topologies.topologies.topology import Topology


# Edit these values before running the module
MODE = None # None opens the mode menu; accepts names such as "fwd" or "cdn-qoe"
TRAFFIC = "iperf" # "iperf" or "dash"
RESULTS_DIR = Path("results/manual")


# Brief: Create the network, configure telemetry and leave containers running
def main(mode=None, config=CONFIG, traffic="iperf", results_dir=Path("results/manual")):
    if traffic not in ("iperf", "dash"):
        raise ValueError("Traffic must be 'iperf' or 'dash'")
    if mode is None:
        for key, settings in MODES.items():
            print(f"[{key}] - {settings['name']}")
        while mode is None:
            choice = input("Choose a topology mode: ").strip().lower()
            try:
                mode = mode_key("diamond", choice)
            except ValueError as error:
                print(error)
    mode = MODES[mode_key("diamond", mode)]

    topo = Topology(
        config=config,
        results_dir=results_dir,
        iperf=traffic == "iperf",
        onos_version=f"onosproject/onos:{mode['onos']}",
    )
    topo.run(run_discovery=True, disable_fwd=mode["disable_fwd"])
    if mode["apps"]:
        topo.controller.activateONOSApps(
            server_ip=topo.onos_ip,
            command=f"app activate org.onosproject.{mode['apps']}",
        )

    component = "com.maojianwei.link.quality.measurement.impl.MaoLinkQualityManager"
    commands = (
        f"cfg set {component} latencyAverageSize 1; "
        f"cfg set {component} probeInterval 500; "
        f"cfg set {component} calculateInterval 500"
    )
    subprocess.run(
        ["docker", "exec", "c1", "/home/onos/apache-karaf-4.2.14/bin/client",
         "-u", "karaf", "-p", "karaf", commands],
        check=True,
    )
    print("[DONE] Topology is running; containers remain active")
    if mode["use_deployer"]:
        supervisor = "supervisor-quantization" if mode["name"] == "treshold" else "supervisor"
        print("Start the external services manually:")
        for service in ("deployer", supervisor):
            print(f"sudo docker run --rm -it --network host "
                  f"-v /var/run/docker.sock:/var/run/docker.sock --name {service} {service}")
    return topo


if __name__ == "__main__":
    main(mode=MODE, config=CONFIG, traffic=TRAFFIC, results_dir=RESULTS_DIR)
