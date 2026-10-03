import json
import logging
import os
import subprocess
import time
from pathlib import Path

from onos_topologies.assets import ASSETS_DIR
from profissa_lft.exceptions import NodeInstantiationFailed
from profissa_lft.host import Host


class DashClient(Host):
    def __init__(self, nodeName: str) -> None:
        super().__init__(nodeName)

    def instantiate(
        self, dockerImage="neubot/dash-client:latest", networkMode="none"
    ) -> None:
        try:
            dockerCommand = f"docker run -d --name={self.getNodeName()} --network={networkMode} --cap-add=NET_ADMIN --entrypoint sleep {dockerImage} infinity"
            return super().instantiate(dockerImage, dockerCommand)
        except Exception as ex:
            logging.error(
                f"Error instantiating DASH client {self.getNodeName()}: {str(ex)}"
            )
            raise NodeInstantiationFailed(
                f"Error instantiating DASH client {self.getNodeName()}: {str(ex)}"
            )

    def setIp(self, ip: str, mask: int, interfaceName="") -> None:
        if interfaceName == "":
            interfaceName = self.getNodeName()
        self._Node__setIp(ip, mask, interfaceName)

    # Brief: Run dash-client and return segment measurements, server samples and errors
    # Use blocking Docker execution without sudo to avoid background password prompts
    # Parse segment JSON objects followed by the server-sample array
    def run_measurement(
        self, server_ip: str, scheme: str = "http", timeout_s: int = 90
    ) -> dict:
        t0 = time.time()
        try:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.getNodeName(),
                    "bash",
                    "-lc",
                    f"/usr/local/bin/dash-client -y -hostname {server_ip} -scheme {scheme}",
                ],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            proc_ok, stdout, stderr = (
                (result.returncode == 0),
                result.stdout,
                result.stderr.strip(),
            )
        except subprocess.TimeoutExpired:
            proc_ok, stdout, stderr = False, "", "timeout"
        elapsed_s = time.time() - t0

        iterations, server_ticks = [], None
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                server_ticks = parsed
            else:
                iterations.append(parsed)

        return {
            "ok": proc_ok and bool(iterations),
            "elapsed_s": elapsed_s,
            "iterations": iterations,
            "server_ticks": server_ticks,
            "stderr": stderr or None,
        }


class DashServer(Host):
    def __init__(self, nodeName: str) -> None:
        super().__init__(nodeName)

    def instantiate(self, dockerImage="neubot/dash:latest", mapPorts=True) -> None:
        try:
            curr_dir = Path(__file__).resolve().parents[2] / "results" / "dash"
            certs_dir = ASSETS_DIR / "certs"

            # Host datadir root
            host_datadir_root = (
                Path(os.environ.get("LFT_RESULTS", str(curr_dir))).resolve() / "datadir"
            )
            host_datadir_root.mkdir(parents=True, exist_ok=True)

            base_command = (
                f"-v {certs_dir}:/certs:ro "
                f"-v {host_datadir_root}:/datadir "
                f"{dockerImage} "
                f"-datadir /datadir "
                f"-http-listen-address :80 "
                f"-https-listen-address '' "
                f"-prometheusx.listen-address :9999 "
                f"-tls-cert /certs/cert.pem -tls-key /certs/key.pem"
            )

            if mapPorts:
                dockerCommand = f"docker run -d --name={self.getNodeName()} --network=bridge -p 80:80 -p 9990:9999 {base_command}"
            else:
                dockerCommand = f"docker run -d --name={self.getNodeName()} --network=none {base_command}"

            return super().instantiate(dockerImage, dockerCommand)

        except Exception as ex:
            logging.error(
                f"Error instantiating DASH server {self.getNodeName()}: {str(ex)}"
            )
            raise NodeInstantiationFailed(
                f"Error instantiating DASH server {self.getNodeName()}: {str(ex)}"
            )

    def setIp(self, ip: str, mask: int, interfaceName="") -> None:
        if interfaceName == "":
            interfaceName = self.getNodeName()
        self._Node__setIp(ip, mask, interfaceName)
