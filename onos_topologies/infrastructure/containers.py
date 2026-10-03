import os
import shlex
import subprocess
import time

import requests
from pathlib import Path

from onos_topologies.experiments.runtime import phase

# Brief: REIN checkout whose docker-compose.yml defines the deployer and supervisor, which the ONOS
# experiments start in the modes that use them
REIN_DIR = Path(os.environ.get("REIN_DIR", Path(__file__).resolve().parents[2].parent / "REIN"))
_COMPOSE = f"docker compose -f {shlex.quote(str(REIN_DIR / 'docker-compose.yml'))}"


# Brief: Builds the compose command, exporting env vars the compose file forwards to the services
def compose_cmd(action: str, env: dict = None) -> str:
    exports = "".join(f"{k}={shlex.quote(str(v))} " for k, v in (env or {}).items())
    return f"sudo {exports}{_COMPOSE} {action}"


# Brief: Starts deployer and supervisor detached, building the images on first run
def compose_up(env: dict = None) -> None:
    phase("rein", "Starting deployer and supervisor")
    subprocess.run(compose_cmd("up -d --build", env), shell=True, check=True)


# Brief: Stops and removes both services
def compose_down() -> None:
    subprocess.run(compose_cmd("down"), shell=True)


# Brief: Retrieves the IP address of a Docker container by its name
def get_container_ip(name: str) -> str:
    cmd = f"docker inspect -f '{{{{range .NetworkSettings.Networks}}}}{{{{.IPAddress}}}}{{{{end}}}}' {name}"
    return subprocess.check_output(cmd, shell=True, text=True).strip()


# Brief: Removes the topology's containers (label lft=1; nothing else on the host, e.g. the REIN services)
# and purges unused networks
def cleanup() -> None:
    phase("cleanup", "Removing the previous topology's containers")
    print("\n[CLEANUP] Removing old SSH key for ONOS...")
    subprocess.run('ssh-keygen -R "[172.17.0.2]:8101" >/dev/null 2>&1', shell=True)
    print("[CLEANUP] Stopping and removing the topology's containers...")
    subprocess.run('sudo docker rm -f $(sudo docker ps -aq --filter label=lft=1) >/dev/null 2>&1 || true', shell=True)
    print("[CLEANUP] Removing unused Docker networks...")
    subprocess.run('sudo docker network prune -f >/dev/null 2>&1', shell=True)
    print("[CLEANUP] Done.")


# Brief: Wait for an HTTP endpoint to return success before starting measurements
def wait_http(url, auth=None, timeout=120):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"Service not ready after {timeout}s: {url}")
        try:
            response = requests.get(url, auth=auth, timeout=min(5, remaining))
            response.raise_for_status()
            return
        except requests.RequestException as error:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Service not ready after {timeout}s: {url}") from error
            time.sleep(min(2, max(0, deadline - time.monotonic())))
