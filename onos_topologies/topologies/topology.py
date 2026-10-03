import os
import random
import subprocess
import time
from pathlib import Path

from onos_topologies.assets import ASSETS_DIR
from onos_topologies.experiments.runtime import print_banner, sleep_countdown
from onos_topologies.infrastructure.containers import get_container_ip
from onos_topologies.traffic.iperf import IperfClient, IperfServer

from ..infrastructure.onos import ONOS
from ..infrastructure.switch import Switch
from ..traffic.dash import DashClient, DashServer
from .configs.dash import DEFAULT_CONFIG, RANDOM_RANGES


class Topology:
    """
    Encapsulates all logic to build, configure and test the topology
    """

    def __init__(self, 
                 config: dict = DEFAULT_CONFIG, 
                 results_dir: Path = None,
                 iperf: bool = True,
                 onos_version: str = "onosproject/onos:2.5.0"
                 ):
        self.config = config

        # Default version v2.5 for compatibility with measuring tools
        self.onos_version = onos_version

        self.server_ip_range, self.client_ip_range = self.__get_ip_ranges(self.config["pops"])
        
        # Only created for the iperf experiment. If true, clients and servers use iperf instead of the typical dash algo
        self.iperf = iperf  

        # Map: {pop_name: switch_name}
        self.pop_to_sname = {pop[0]: f"s{i}" for i, pop in enumerate(self.config['pops'])}

        # Map: {client_name: client_obj}
        self.clients = {}   

        # Map: {server_name: server_obj}
        self.servers = {}

        # Map: {pop_name: switch_obj}
        self.switches = {}

        # ONOS controller (object)
        self.controller = ""

        # PoP list of client Node (used by collectFlows to select host-facing ports)
        self.hosts_by_pop = {pop[0]: [] for pop in self.config['pops']}

        # Host-side directory that will be bind-mounted into each switch at /results/dash
        self.host_results = Path(results_dir).resolve() if results_dir else None

        self.onos_ip   = ""
        self._host_ips = {} # used by interactive create_host/connect_nodes

        # List of inter-switch links built by __connect_switches:
        # each as (sw_a, iface_a, sw_b, iface_b)
        self.inter_switch_links = []

        # Per-interface netem params applied at setup (iface_name -> (throughput, delay, jitter)),
        # so callers can restore the original qdisc after temporarily overriding it (e.g. chaos tools)
        self.link_qdisc_params = {}

    # Brief: Allocate server and client IPs in the shared subnet
    def __get_ip_ranges(self, pops: tuple) -> tuple:
        tot_servers = sum(p[2] for p in pops)
        tot_clients = sum(p[1] for p in pops)
        server_ip_range = [f"192.168.0.{i+1}" for i in range(tot_servers)]
        client_ip_range = [f"192.168.0.{i}" for i in range(tot_servers + 1, tot_servers + tot_clients + 1)]
        return server_ip_range, client_ip_range


    # Brief: Create and connect server containers for the selected traffic type
    def __create_servers(self, iperf=False):
        ds_index = 0
        print(f"[Experiment] ... Creating servers")
        
        for pop, _, num_servers in self.config["pops"]:
            edge_node = self.switches[pop]

            for _ in range(num_servers):
                throughput = delay = jitter = "-" 
                dsname = f"ds{ds_index}"
                ds_if, sw_if = f"{dsname}{self.pop_to_sname[pop]}", f"{self.pop_to_sname[pop]}{dsname}"

                ds = IperfServer(dsname) if iperf else DashServer(dsname)
                ds.instantiate(mapPorts=False)
                ds.connect(edge_node, ds_if, sw_if)

                server_ip = self.server_ip_range[ds_index]
                ds.setIp(server_ip, 24, ds_if)
                print(f"  ... Host {dsname} ({server_ip}) created and linked to {pop}")

                # Host<->switch (access) link: gated separately from
                # apply_link_properties (which governs the RNP-data-backed
                # inter-switch matrix below) -- unlike those, this link has no
                # real-world value behind it, so by default (unless a config
                # explicitly opts in) we leave the interface unshaped rather
                # than baking in an arbitrary delay/jitter/rate that would
                # confound every measurement, degraded or not.
                if self.config.get("apply_access_link_properties", True):
                    if self.config.get("randomize_link_properties"):
                        throughput, delay, jitter = f"{random.choice(RANDOM_RANGES['throughput'])}mbit", f"{random.choice(RANDOM_RANGES['delay'])}ms", f"{random.choice(RANDOM_RANGES['jitter'])}ms"
                    else:
                        throughput, delay, jitter = self.config["throughput"], self.config["delay"], self.config["jitter"]

                    edge_node.setInterfaceProperties(interfaceName=sw_if, throughput=throughput, delay=delay, jitter=jitter)
                    ds.setInterfaceProperties(interfaceName=ds_if, throughput=throughput, delay=delay, jitter=jitter)
                    print(f"Throughput={throughput}, Delay={delay}, Jitter={jitter}")
                else:
                    print("Access link: unshaped (no qdisc)")

                self.servers[dsname] = ds
                self._host_ips[dsname] = server_ip
                self.hosts_by_pop[pop].append(ds)
                ds_index += 1

        print("[OK] Servers created!\n")


    # Brief: Create and connect client containers for the selected traffic type
    def __create_clients(self, iperf=False):
        cli_index = 0
        print(f"[Experiment] ... Creating DASH clients")

        for pop, num_clients, _ in self.config["pops"]:
            edge_node = self.switches[pop]

            for _ in range(num_clients):
                throughput = delay = jitter = "-" 
                cname = f"cl{cli_index}"
                cl_if, sw_if = f"{cname}{self.pop_to_sname[pop]}", f"{self.pop_to_sname[pop]}{cname}"

                cl = IperfClient(cname) if iperf else DashClient(cname)
                cl.instantiate()
                cl.connect(edge_node, cl_if, sw_if)

                client_ip = self.client_ip_range[cli_index]
                cl.setIp(client_ip, 24, cl_if)
                print(f"  ... Host {cname} ({client_ip}) created and linked to {pop}")

                # See the matching comment in __create_servers: this is the
                # host<->switch access link, not RNP-backed data, so it's
                # gated separately and left unshaped by default.
                if self.config.get("apply_access_link_properties", True):
                    if self.config.get("randomize_link_properties"):
                        throughput, delay, jitter = f"{random.choice(RANDOM_RANGES['throughput'])}mbit", f"{random.choice(RANDOM_RANGES['delay'])}ms", f"{random.choice(RANDOM_RANGES['jitter'])}ms"
                    else:
                        throughput, delay, jitter = self.config["throughput"], self.config["delay"], self.config["jitter"]

                    edge_node.setInterfaceProperties(interfaceName=sw_if, throughput=throughput, delay=delay, jitter=jitter)
                    cl.setInterfaceProperties(interfaceName=cl_if, throughput=throughput, delay=delay, jitter=jitter)
                    print(f"Throughput={throughput}, Delay={delay}, Jitter={jitter}")
                else:
                    print("Access link: unshaped (no qdisc)")

                self.clients[cname] = cl
                self._host_ips[cname] = client_ip
                self.hosts_by_pop[pop].append(cl)
                cli_index += 1
                
        print("[OK] DASH clients created!\n")


    # Brief: Create the ONOS controller, start it and activate required apps
    def __create_controller(self):
        print("\n[Experiment] ... Creating ONOS controller")
        c1 = ONOS("c1")
        dockerImage=self.onos_version
        c1.instantiate(dockerImage=dockerImage, mapPorts=True) 
        self.onos_ip = get_container_ip("c1")
        c1.setCliIp(self.onos_ip) # needed in runOnosCliCommands() from Onos class
        print(f"[CTRL] ONOS IP: {self.onos_ip}")
        print("Waiting for ONOS to initialize (30s) ...")
        sleep_countdown(30)

        print("[CTRL] Activating OpenFlow + Proxy Arp + Reactive Forwarding")
        apps_to_activate = ["org.onosproject.openflow", "org.onosproject.fwd", "org.onosproject.proxyarp"]
        for app in apps_to_activate:
            c1.activateONOSApps(server_ip=self.onos_ip, command=f'app activate {app}')

        current_dir = str(ASSETS_DIR)

        # install and activate telemetry app
        if (dockerImage == "onosproject/onos:2.5.0"):
            print("[CTRL] Installing custom latency app...")
            oar_path = os.path.abspath(os.path.join(current_dir, "onos_apps", "onos-apps-ONOS_Link_Quality_Measurement-oar.oar"))

            if os.path.exists(oar_path):
                activation_cmd = (
                    f'curl -u onos:rocks -X POST '
                    f'-H "Content-Type:application/octet-stream" '
                    f'"http://{self.onos_ip}:8181/onos/v1/applications?activate=true" '
                    f'--data-binary "@{oar_path}"'
                )
                subprocess.run(activation_cmd, shell=True, capture_output=True)
                print("[OK] Latency app installed!")
            else:
                print(f"[ERROR] OAR file not found in: {oar_path}")

        print("[OK] ONOS is ready!\n")
        self.controller = c1 # stores c1 obj to access a few methods outside of this function


    # Brief: Create all OVS switches and connect them to the ONOS controller
    def __create_switches(self):
        if self.host_results is None:
            self.host_results = Path(os.getenv("LFT_RESULTS", "/lft/results/dash")).resolve()
            self.host_results.mkdir(parents=True, exist_ok=True)

        print(f"[Experiment] ... Creating {len(self.config['pops'])} OVS switches")
        dpid_counter = 1
        for pop, sname in self.pop_to_sname.items():
            # If pop is "PoP-BA", uf becomes "BA"
            uf = str(pop).split("-")[-1].upper()

            datapath_id = f"{dpid_counter:016x}" # ex: "0000000000000001"
            dpid_counter += 1

            sw = Switch(sname, hostPath=str(self.host_results), containerPath="/results/dash")
            sw.instantiate(
                image="alexandremitsurukaihara/lst2.0:openvswitch",
                networkMode="bridge",
                datapath_id=datapath_id,
                sw_desc=uf,
            )

            self.switches[pop] = sw
            print(f"  ... Switch {pop} as {sname} was created! dpid={datapath_id} desc={uf}")
            time.sleep(0.4)

        print(f"[CTRL] Pointing all switches to ONOS ({self.onos_ip}:6653)")
        for pop, *_ in self.config['pops']:
            self.switches[pop].setController(self.onos_ip, 6653)
        print("[OK] Controllers configured!\n")


    # Brief: Create PoP links based on self.config['adjacency_matrix']
    def __connect_switches(self):
        print("[Experiment] ... Connecting PoP-to-PoP switches")
        connections_made = set()
        throughput = delay = jitter = "-" # defaults for printing

        for i, pop_i in enumerate(self.config['pops']):
            pop_i_name = pop_i[0] # ex: pop_i_name = "PoP-AC"; pop_i = ("PoP-AC", 0, 1)
            for j, pop_j in enumerate(self.config['pops']):
                pop_j_name = pop_j[0] # ex: pop_j_name = "PoP-CE"; pop_j = ("PoP-CE", 5, 0)
                if i == j:
                    continue
                if self.config['adjacency_matrix'][i][j] != 1:
                    continue

                edge = tuple(sorted((pop_i_name, pop_j_name)))
                if edge in connections_made:
                    continue
                connections_made.add(edge)

                si = self.pop_to_sname[pop_i_name]
                sj = self.pop_to_sname[pop_j_name]
                self.switches[pop_i_name].connect(self.switches[pop_j_name], f"{si}{sj}", f"{sj}{si}")
                self.inter_switch_links.append((si, f"{si}{sj}", sj, f"{sj}{si}"))

                if self.config.get("apply_link_properties"):
                    if self.config.get("randomize_link_properties"):
                        throughput = f"{random.choice(RANDOM_RANGES['throughput'])}mbit"
                        delay = f"{random.choice(RANDOM_RANGES['delay'])}ms"
                        jitter = f"{random.choice(RANDOM_RANGES['jitter'])}ms"
                    else:
                        tm = self.config.get("throughput_matrix")
                        throughput = tm[i][j] if (tm and tm[i][j]) else self.config["throughput"]
                        lm = self.config.get("rtt_matrix")
                        if lm and lm[i][j]:
                            rtt_ms = float(lm[i][j].replace("ms", ""))
                            delay = f"{rtt_ms / 2:.2f}ms"
                        else:
                            delay = self.config["delay"]
                        jitter = self.config["jitter"]

                    si_obj = self.switches[pop_i_name]
                    sj_obj = self.switches[pop_j_name]
                    si_obj.setInterfaceProperties(interfaceName=f"{si}{sj}", throughput=throughput, delay=delay, jitter=jitter)
                    sj_obj.setInterfaceProperties(interfaceName=f"{sj}{si}", throughput=throughput, delay=delay, jitter=jitter)
                    self.link_qdisc_params[f"{si}{sj}"] = (throughput, delay, jitter)
                    self.link_qdisc_params[f"{sj}{si}"] = (throughput, delay, jitter)
                    print(f"Throughput={throughput}, Delay={delay}, Jitter={jitter}")

                print(f"  [LINK] {pop_i_name} <-> {pop_j_name}")
                time.sleep(0.4)

        print(f"[OK] {len(connections_made)} inter-PoP links created!\n")


    # Brief: Force host discovery in ONOS by sending ARP/ICMP traffic
    def __run_ping(self) -> None:
        print("\n[DISCOVERY] Forcing host discovery for ONOS...")

        # self.values = {server_name: server_obj}
        for server in self.servers.values():
            print(f"  ... Ping: ALL Servers -> 192.168.0.254") # non-attributed IP addr. Just sends ARP and ONOS discovers it
            server.run(f'bash -lc "ping -c 1 192.168.0.254"')

        # self.clients = {client_name: client_obj}
        for client in self.clients.values():
            print(f"  ... Ping: ALL Clients -> 192.168.0.254")
            client.run(f'bash -lc "ping -c 1 192.168.0.254"')

        print("  ... Discovery packets sent. Waiting 3s for ONOS to process.")
        sleep_countdown(3)
        print("[OK] Hosts should be visible in ONOS.\n")


    def __discover_dash_servers(self) -> None:
        probe_ip = "192.168.0.254"
        print("\n[DISCOVERY] Priming servers (ARP via ping) ...")

        for sname, server in self.servers.items():
            print(f"  ... {sname}: ping {probe_ip}")
            server.run(f'sh -lc "ping -c 1 -W 1 {probe_ip} >/dev/null 2>&1 || true"')
        print("  ... waiting 3s for ONOS /hosts update")
        sleep_countdown(3)
        print("[OK] Servers should be visible in ONOS /hosts.\n")


    # Brief: Run each DASH client once against a randomly selected server
    def __run_dash_clients(self, scheme: str = "http"):
        print("\n[DIAG] Running dash-client for all clients (random server each)")

        procs = []
        for cname in self.clients.keys():
            srv = random.choice(self.server_ip_range)
            cmd = (
                f"sudo docker exec {cname} bash -lc "
                f"\"/usr/local/bin/dash-client -y -hostname {srv} -scheme {scheme}\""
            )
            print(f"[DIAG] start {cname} -> server {srv}")
            procs.append(subprocess.Popen(cmd, shell=True))

        for p in procs:
            p.wait()

        print("[DIAG] Done.\n")


    def start_controller(self):
        self.__create_controller()

    def create_switch(self, name: str):
        sname = f"s{len(self.switches)}"
        sw = Switch(sname)
        sw.instantiate(networkMode="bridge")
        sw.setController(self.onos_ip, 6653)
        self.switches[name]     = sw
        self.pop_to_sname[name] = sname
        print(f"  ... Switch {name} ({sname})")

    def create_host(self, name: str, ip: str):
        h = IperfClient(name)
        h.instantiate()
        self.clients[name]    = h
        self._host_ips[name]  = ip
        print(f"  ... Host {name} ({ip})")

    def create_server(self, name: str, ip: str):
        s = IperfServer(name)
        s.instantiate()
        s.startServer()
        self.servers[name]    = s
        self._host_ips[name]  = ip
        print(f"  ... Server {name} ({ip}) [iperf3 -s]")

    def connect_nodes(self, name1: str, name2: str):
        def get(n):
            return self.switches.get(n) or self.clients.get(n) or self.servers.get(n)
        obj1, obj2 = get(name1), get(name2)
        if not obj1 or not obj2:
            raise ValueError(f"unknown node: {name1 if not obj1 else name2}")
        obj1.connect(obj2, f"{name1}{name2}", f"{name2}{name1}")
        if name1 in self._host_ips:
            obj1.setIp(self._host_ips[name1], 24, f"{name1}{name2}")
        if name2 in self._host_ips:
            obj2.setIp(self._host_ips[name2], 24, f"{name2}{name1}")
        print(f"  ... Link {name1} <-> {name2}")

    # Brief: Run full topology
    def run(self, run_discovery: bool = False, disable_fwd: bool = False, run_dash_clients: bool = False):
        print_banner()
        
        self.__create_controller()
        c1 = self.controller

        self.__create_switches()
        self.__connect_switches()

        if (not self.iperf):
            # Default DASH
            self.__create_clients()
            self.__create_servers()
        if (self.iperf):
            # Only for the iperf experiment!!
            self.__create_clients(iperf=True)
            self.__create_servers(iperf=True)

        self.__discover_dash_servers()

        print("Waiting for network stabilization (5s)...\n")
        sleep_countdown(5)

        if disable_fwd:
            c1.deactivateONOSApps(self.onos_ip)
        else:
            print("[INFO] ONOS Active Forwarding is active (Turn it off if you want to test the deployer).")

        if run_discovery:
            self.__run_ping()
        else:
            print("[INFO] Host discovery (ping) skipped.")

        if run_dash_clients:
            self.__run_dash_clients()
        else:
            print("[INFO] Dash Client script (GET /dash/download/<size>) skipped.")



