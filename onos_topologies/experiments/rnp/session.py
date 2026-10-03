"""RNP traffic lifecycle, including server-change notifications and ping tracking"""

import subprocess
import threading
import time

from flask import Flask, jsonify, request
from werkzeug.serving import make_server

from onos_topologies.measurements.iperf import zero_fill_if_empty

from .config import (
    DEMAND_RATE,
    IPERF_CONNECT_TIMEOUT_S,
    MIN_RESTART_REMAINING_S,
    PATH_WARMUP_TIMEOUT_S,
)


class IperfSession:
    def __init__(self, ping_dir, client_to_server, server_by_ip, mark):
        self.ping_dir = ping_dir
        self.client_to_server = client_to_server
        self.server_by_ip = server_by_ip
        self.mark = mark
        self.lock = threading.Lock()
        self.active_jobs = {}
        self.run_deadline = 0.0
        self.run_start = 0.0
        self.iperf_dir = None
        self.run_over = False

    def start_ping(self, client_name, server_ip, mode="a"):
        f_out = open(self.ping_dir / f"{client_name}.txt", mode, encoding="utf-8")
        proc = subprocess.Popen(
            [
                "sudo",
                "docker",
                "exec",
                client_name,
                "ping",
                server_ip,
                "-i",
                "0.5",
                "-D",
                "-O",
            ],
            stdout=f_out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        return proc, f_out

    def wait_for_path(self, client_name, server_ip, timeout_s=PATH_WARMUP_TIMEOUT_S):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            probe = subprocess.run(
                [
                    "sudo",
                    "docker",
                    "exec",
                    client_name,
                    "ping",
                    "-c",
                    "3",
                    "-W",
                    "2",
                    "-q",
                    server_ip,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            if probe.returncode == 0:
                return True
            time.sleep(2)
        return False

    def stop_ping(self, job):
        proc, f_out = job.get("ping_proc"), job.get("ping_out")
        if proc is not None:
            subprocess.run(
                ["sudo", "docker", "exec", job["client_name"], "pkill", "-INT", "ping"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if f_out is not None:
            try:
                f_out.close()
            except Exception:
                pass

    def apply_server_change(self, client_ip, new_server, reason="deploy"):
        with self.lock:
            # Every early return is marked: a refused restart otherwise looks
            # identical to "the deployer never asked", and the kill/relaunch
            # below is itself a throughput dip, not a network one.
            if self.run_over:
                self.mark(
                    f"SERVER_CHANGE_SKIPPED {client_ip} -> {new_server} ({reason}) run_over"
                )
                return False

            old_server = self.client_to_server.get(client_ip)
            self.client_to_server[client_ip] = new_server
            if new_server == old_server:
                self.mark(
                    f"SERVER_CHANGE_NOOP {client_ip} already on {new_server} ({reason})"
                )
                return False

            job = self.active_jobs.get(client_ip)
            if job is None:
                self.mark(
                    f"SERVER_CHANGE_SKIPPED {client_ip} -> {new_server} ({reason}) no job"
                )
                return False

            remaining = self.run_deadline - time.time()
            if remaining < MIN_RESTART_REMAINING_S:
                self.mark(
                    f"SERVER_CHANGE_SKIPPED {client_ip} -> {new_server} ({reason}) "
                    f"only {remaining:.0f}s left"
                )
                return False

            self.mark(
                f"IPERF_RESTART_BEGIN {client_ip} {old_server} -> {new_server} ({reason})"
            )
            job["client_obj"].stopIperf(job["proc"])
            # The destination's listener may still be holding this port with the
            # session this same client abandoned earlier; give it a fresh one.
            if new_server in self.server_by_ip:
                self.server_by_ip[new_server].restartServer(job["port"])
            try:
                job["f_out"].close()
            except Exception:
                pass

            zero_fill_if_empty(
                job["parts"][-1],
                job.get("part_start_ts", self.run_start),
                job["client_name"],
            )

            out_path = (
                self.iperf_dir
                / f"{job['client_name']}_part{len(job['parts']) + 1}.json"
            )
            proc, f_out = job["client_obj"].runIperf(
                new_server,
                job["port"],
                remaining,
                out_path,
                connect_timeout_s=IPERF_CONNECT_TIMEOUT_S,
                rate=DEMAND_RATE,
            )
            job["proc"], job["f_out"] = proc, f_out
            job["server_ip"] = new_server
            job["parts"].append(out_path)
            job["part_start_ts"] = time.time()

            # Follow the client, or the RTT series keeps measuring a path that
            # no longer carries its traffic.
            self.stop_ping(job)
            job["ping_proc"], job["ping_out"] = self.start_ping(
                job["client_name"], new_server
            )
            self.mark(f"IPERF_RESTART_END {client_ip} now on {new_server}")

        print(
            f" [IPERF] {job['client_name']}: server changed {old_server} -> {new_server} ({reason}), "
            f"relaunching ({remaining:.0f}s left)..."
        )
        return True


def start_notifications(apply_server_change, port):
    app = Flask(__name__)

    @app.route("/server_changed", methods=["POST"])
    def on_server_changed():
        body = request.get_json(silent=True, force=True) or {}
        client_ip, new_server = body.get("client_ip"), body.get("server_ip")
        if not client_ip or not new_server:
            return jsonify({"error": "client_ip and server_ip required"}), 400
        restarted = apply_server_change(client_ip, new_server, reason="push")
        return jsonify({"status": "ok", "restarted": restarted}), 200

    server = make_server("0.0.0.0", port, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f" [SETUP] Listening for deployer server-change pushes on port {port}...")
    return server
