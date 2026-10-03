import logging
import subprocess

from profissa_lft.exceptions import NodeInstantiationFailed
from profissa_lft.host import Host


class IperfClient(Host):
    def __init__(self, nodeName: str) -> None:
        super().__init__(nodeName)

    def instantiate(
        self, dockerImage="lft-iperf:latest", networkMode="none", mapPorts=False
    ) -> None:
        try:
            dockerCommand = f"docker run -d --name={self.getNodeName()} --network={networkMode} --cap-add=NET_ADMIN --entrypoint sleep {dockerImage} infinity"
            return super().instantiate(dockerImage, dockerCommand)
        except Exception as ex:
            logging.error(
                f"Error instantiating IPERF client {self.getNodeName()}: {str(ex)}"
            )
            raise NodeInstantiationFailed(
                f"Error instantiating IPERF client {self.getNodeName()}: {str(ex)}"
            )

    def setIp(self, ip: str, mask: int, interfaceName="") -> None:
        if interfaceName == "":
            interfaceName = self.getNodeName()
        self._Node__setIp(ip, mask, interfaceName)

    def runIperf(
        self,
        server_ip: str,
        port: int,
        duration: float,
        out_path,
        connect_timeout_s: int = 60,
        rate: str = "35M",
    ):
        connect_timeout_ms = min(round(duration), connect_timeout_s) * 1000
        cmd = [
            "sudo",
            "docker",
            "exec",
            self.getNodeName(),
            "iperf3",
            "-c",
            server_ip,
            "-p",
            str(port),
            "-t",
            str(max(1, round(duration))),
            "-i",
            "1",
            "-b",
            rate,
            "--fq-rate",
            rate,
            "--connect-timeout",
            str(max(1000, connect_timeout_ms)),
            "--forceflush",
            "-J",
        ]
        f_out = open(out_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=f_out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        return proc, f_out

    def stopIperf(self, proc, grace_s: float = 5) -> None:
        subprocess.run(
            ["sudo", "docker", "exec", self.getNodeName(), "pkill", "-INT", "iperf3"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        try:
            proc.wait(timeout=grace_s)
            return
        except subprocess.TimeoutExpired:
            pass

        subprocess.run(
            ["sudo", "docker", "exec", self.getNodeName(), "pkill", "-KILL", "iperf3"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        proc.terminate()
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            proc.kill()


class IperfServer(Host):
    def __init__(self, nodeName: str) -> None:
        super().__init__(nodeName)

    def instantiate(
        self, dockerImage="lft-iperf:latest", networkMode="none", mapPorts=False
    ) -> None:
        try:
            dockerCommand = f"docker run -d --name={self.getNodeName()} --network={networkMode} --cap-add=NET_ADMIN --entrypoint sleep {dockerImage} infinity"
            return super().instantiate(dockerImage, dockerCommand)
        except Exception as ex:
            logging.error(
                f"Error instantiating IPERF server {self.getNodeName()}: {str(ex)}"
            )
            raise NodeInstantiationFailed(
                f"Error instantiating IPERF server {self.getNodeName()}: {str(ex)}"
            )

    def setIp(self, ip: str, mask: int, interfaceName="") -> None:
        if interfaceName == "":
            interfaceName = self.getNodeName()
        self._Node__setIp(ip, mask, interfaceName)

    # `iperf3 -s` serves one test at a time and, before 3.7, has no way to reap a
    # session whose client was killed. A client that changes server and later
    # comes back finds the port still held by its own dead session: it connects,
    # cwnd stays 0, and the run is silently zero-filled. Restarting the listener
    # costs milliseconds and works on every version.
    def restartServer(self, port: int = 5201) -> None:
        subprocess.run(
            f"docker exec {self.getNodeName()} pkill -f 'iperf3 -s -p {port}'",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        self.startServer(port)

    def _supports_idle_timeout(self) -> bool:
        """Cached per node: --idle-timeout only exists from iperf 3.7 on, and an
        unknown flag would leave the server dead with nobody watching (it starts
        detached, output redirected to a file)"""
        if not hasattr(self, "_idle_ok"):
            probe = subprocess.run(
                f"docker exec {self.getNodeName()} iperf3 --help",
                shell=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
            )
            self._idle_ok = "--idle-timeout" in (probe.stdout + probe.stderr)
            if not self._idle_ok:
                logging.warning(
                    "%s: iperf3 has no --idle-timeout; a client that changes server "
                    "mid-run may find this port still held by its own dead session.",
                    self.getNodeName(),
                )
        return self._idle_ok

    # --idle-timeout reaps a test whose client vanished. `iperf3 -s` serves one
    # test at a time, so a client killed mid-run (a server change) leaves the
    # session hanging, and the next client to hit this port connects but never
    # transfers: cwnd stays 0 and the run is silently zero-filled. Left alone the
    # session only clears after minutes, which is why this went unnoticed while
    # snapshots lasted 600s and only bit at 60s.
    def startServer(self, port: int = 5201, idle_timeout_s: int = 5) -> None:
        idle = (
            f"--idle-timeout {idle_timeout_s} " if self._supports_idle_timeout() else ""
        )
        cmd = (
            f"docker exec -d {self.getNodeName()} "
            f'bash -lc "iperf3 -s -p {port} {idle}'
            f'</dev/null >/tmp/iperf3-{port}.log 2>&1"'
        )
        subprocess.run(cmd, shell=True, check=True, stdin=subprocess.DEVNULL)
