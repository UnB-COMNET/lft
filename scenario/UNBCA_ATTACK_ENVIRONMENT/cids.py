#!/usr/bin/env python3
import os
import signal
import sys
import subprocess
from configparser import ConfigParser

from profissa_lft.host import Host
from profissa_lft.switch import Switch
from profissa_lft.controller import Controller
from profissa_lft.node import Node

from globalvariables import *


class Seafile(Host):
    def instantiate(self):
        super().instantiate(dockerImage=seafileserver)

    def updateServerConfig(self) -> None:
        self.copyContainerToLocal("/home/seafolder", "seafolder")
        out = subprocess.run("cat seafolder", shell=True, capture_output=True).stdout.decode('utf8')
        parser = ConfigParser()
        parser.read('serverconfig.ini')
        parser.set("50", "seafolder", out)
        parser.set("200", "seafolder", out)
        parser.set("210", "seafolder", out)
        parser.set("220", "seafolder", out)
        with open('serverconfig.ini', 'w') as configfile:
            parser.write(configfile)
        if os.path.exists('seafolder'):
            os.remove('seafolder')


class LinuxClient(Host):
    def setAutomationScripts(self, path) -> None:
        self.copyLocalToContainer(path, "/home/debian/automation")

    def setPrinterIp(self, path) -> None:
        self.copyLocalToContainer(path, "/home/debian/automation/packages/system/printerip")

    def setSshIpList(self, path) -> None:
        self.copyLocalToContainer(path, "/home/debian/automation/packages/system/sshiplist.ini")

    def setClientBehaviour(self, path) -> None:
        self.copyLocalToContainer(path, "/home/debian/automation/packages/system/config.ini")

    def setServerConfig(self, path) -> None:
        self.copyLocalToContainer(path, "/home/debian/automation/packages/system/serverconfig.ini")

    def setIpListPort80(self, path) -> None:
        self.copyLocalToContainer(path, "/home/debian/automation/packages/attacking/ipListPort80.txt")

    def setIpList(self, path) -> None:
        self.copyLocalToContainer(path, "/home/debian/automation/packages/attacking/ipList.txt")

    def setIpRange(self, path) -> None:
        self.copyLocalToContainer(path, "/home/debian/automation/packages/attacking/iprange.txt")


def setLinuxClientFileConfig(node: LinuxClient, subnet: str, behaviour: str):
    printTerm(f"[LFT] Copying Configuration Files to Container {node.getNodeName()}")
    if subnet != external_subnet:
        aux = "internal"
    else:
        aux = "external"
    node.setAutomationScripts("automation")
    node.setPrinterIp(f"printersip/{subnet.split('.')[2]}")
    node.setSshIpList("sshiplist.ini")
    node.setClientBehaviour(f"client_behaviour/{behaviour}.ini")
    node.setServerConfig("serverconfig.ini")
    node.setIpListPort80(f"attack/{aux}_ipListPort80.txt")
    node.setIpList(f"attack/{aux}_ipList.txt")
    node.setIpRange(f"attack/{aux}_iprange.txt")


def setNetworkConfig(node: Node, bridge: Node, subnet: str, address: int, setFiles=True) -> Node:
    n_name = node.getNodeName()[:6]
    b_name = bridge.getNodeName()[:6]
    node_iface = f"{n_name}_{b_name}"
    bridge_iface = f"{b_name}_{n_name}"

    node.connect(bridge, node_iface, bridge_iface)
    printTerm(f"[LFT] ... Connecting to {bridge.getNodeName()} ({node_iface} <-> {bridge_iface})")

    node.setIp(subnet + str(address), 24, node_iface)
    printTerm(f"[LFT] ... Setting IP {subnet + str(address)}")

    # Define default gateway of nodes
    if bridge == nodes['brint']:
        node.setDefaultGateway(int_gateway, node_iface)
    if bridge == nodes['brex']:
        node.setDefaultGateway(ex_gateway, node_iface)
    printTerm(f"[LFT] ... Setting Default Gateway")

    # Add routes to enable nodes within internal subnet to communicate with other subnets
    if subnet != server_subnet:
        node.addRoute(server_subnet + '0', 24, node_iface)
    if subnet != management_subnet:
        node.addRoute(management_subnet + '0', 24, node_iface)
    if subnet != office_subnet:
        node.addRoute(office_subnet + '0', 24, node_iface)
    if subnet != developer_subnet:
        node.addRoute(developer_subnet + '0', 24, node_iface)
    if subnet != external_subnet:
        node.addRoute(external_subnet + '0', 24, node_iface)
    printTerm(f"[LFT] ... Adding new routes")

    if setFiles:
        subprocess.run(f"docker cp serverconfig.ini {node.getNodeName()}:/home/debian/serverconfig.ini", shell=True)
        subprocess.run(f"docker cp backup.py {node.getNodeName()}:/home/debian/backup.py", shell=True)


def createBridge(name: str, ip: str, gatewayIp: str) -> None:
    printTerm(f"[LFT] Creating Switch {name}")
    flows_dir = os.path.join(os.getcwd(), 'flows', name)
    os.makedirs(flows_dir, exist_ok=True)

    nodes[name] = Switch(name, flows_dir, '/home/pcap')
    nodes[name].instantiate()
    printTerm("[LFT] ... Instantiating container")

    nodes[name].setIp(ip, 24, name)
    printTerm(f"[LFT] ... Setting IP {ip}")

    switch_host_iface = f"{name}_host"
    host_switch_iface = f"h_{name}"
    nodes[name].connectToInternet(gatewayIp, 24, switch_host_iface, host_switch_iface)
    printTerm(f"[LFT] ... Connecting to Internet through Host ({switch_host_iface} <-> {host_switch_iface})")


def createController(name: str, bridgeName: str, controllerIp: str, controllerPort: int) -> None:
    printTerm(f"[LFT] Creating Controller {name}")
    nodes[name] = Controller(name)
    nodes[name].instantiate()
    printTerm("[LFT] ... Instantiating container")

    c_iface = f"{name[:6]}_{bridgeName[:6]}"
    b_iface = f"{bridgeName[:6]}_{name[:6]}"
    nodes[name].connect(nodes[bridgeName], c_iface, b_iface)
    printTerm(f"[LFT] ... Connecting to Node {bridgeName}")

    nodes[name].setIp(controllerIp, 24, c_iface)
    printTerm(f"[LFT] ... Setting IP {controllerIp}")

    nodes[name].initController(controllerIp, controllerPort)
    printTerm(f"[LFT] ... Initiating Ryu Controller at {controllerIp}:{controllerPort}")

    nodes[bridgeName].setController(controllerIp, controllerPort)
    printTerm(f"[LFT] ... Connecting Switch {bridgeName} to controller")


def createServer(name: str, serverImage: str, subnet: str, address: int) -> None:
    printTerm(f"[LFT] Creating Server {name}")
    nodes[name] = Host(name)
    printTerm("[LFT] ... Instantiating container")
    nodes[name].instantiate(serverImage)
    setNetworkConfig(nodes[name], nodes['brint'], subnet, address)


def createLinuxClient(name, bridge: Node, subnet: str, address: int) -> None:
    printTerm(f"[LFT] Creating Client {name}")
    nodes[name] = LinuxClient(name)
    nodes[name].instantiate(linuxclient)
    printTerm("[LFT] ... Instantiating container")
    setNetworkConfig(nodes[name], bridge, subnet, address)


def createPrinter(name: str, subnet: str) -> None:
    printTerm(f"[LFT] Creating Printer {name}")
    nodes[name] = Host(name)
    nodes[name].instantiate(printerserver)
    printTerm("[LFT] ... Instantiating container")
    setNetworkConfig(nodes[name], nodes['brint'], subnet, 1)


def unmakeChanges():
    printTerm(f"[LFT] Unmaking Experiment. Deleting Containers")
    for name, node in list(nodes.items()):
        try:
            node.delete()
        except Exception:
            subprocess.run(f"docker rm -f {name} > /dev/null 2>&1", shell=True)
    subprocess.run("ip link del h_brint 2>/dev/null || true", shell=True)
    subprocess.run("ip link del h_brex 2>/dev/null || true", shell=True)


def signal_handler(sig, frame):
    print('\nYou pressed Ctrl+C!')
    unmakeChanges()
    sys.exit(0)


def collectLogs():
    printTerm(f"[LFT] Collecting Client Logs")
    os.makedirs('logs', exist_ok=True)
    hosts = ['m1', 'm2', 'm3', 'm4']
    ips = ['200.2', '200.3', '200.4', '200.5']

    def getLog(ip, host):
        subprocess.run(f'docker cp {host}:/home/debian/log/192.168.{ip}.log logs/192.168.{ip}.log > /dev/null 2>&1', shell=True)

    [getLog(ip, host) for ip, host in zip(ips, hosts)]


def printTerm(string: str) -> None:
    print(string, flush=True)


# Capture the ctrl+c
signal.signal(signal.SIGINT, signal_handler)

try:
    printTerm("===================================================================")
    printTerm(" LFT - Security Attack Scenario (CIDDS / UNBCA Environment)")
    printTerm("===================================================================\n")
    printTerm("[LFT] Starting Experiment Topology Setup")

    os.makedirs('flows/brint', exist_ok=True)
    os.makedirs('flows/brex', exist_ok=True)
    os.makedirs('logs', exist_ok=True)

    # 1. Create Bridges and connect them
    createBridge('brint', brint_ip, int_gateway)
    createBridge('brex', brex_ip, ex_gateway)
    nodes['brex'].connect(nodes['brint'], 'brex_brint', 'brint_brex')

    # 2. Host routes for internal subnets
    subprocess.run("ip route replace 192.168.200.0/24 dev h_brint", shell=True)
    subprocess.run("ip route replace 192.168.210.0/24 dev h_brint", shell=True)
    subprocess.run("ip route replace 192.168.220.0/24 dev h_brint", shell=True)

    # 3. Create seafile server
    nodes['seafile'] = Seafile('seafile')
    nodes['seafile'].instantiate()
    setNetworkConfig(nodes['seafile'], nodes['brint'], external_subnet, 1, setFiles=False)
    nodes['seafile'].updateServerConfig()

    # 4. Create controllers
    createController('c1', 'brint', c1_ip, c1port)
    createController('c2', 'brex', c2_ip, c2port)

    # 5. Create server subnet
    createServer('mail', mailserver, server_subnet, 1)
    createServer('file', fileserver, server_subnet, 2)
    createServer('web', webserver, server_subnet, 3)
    createServer('backup', backupserver, server_subnet, 4)

    # 6. Set Management Subnet
    createPrinter('mprinter', management_subnet)
    createLinuxClient('m1', nodes['brint'], management_subnet, 2)
    createLinuxClient('m2', nodes['brint'], management_subnet, 3)
    createLinuxClient('m3', nodes['brint'], management_subnet, 4)
    createLinuxClient('m4', nodes['brint'], management_subnet, 5)

    # 7. Configure Client Automation & Behaviors
    [setLinuxClientFileConfig(nodes[f'm{i}'], management_subnet, 'management') for i in range(1, 5)]

    # 8. Start packet sniffing on switches
    nodes['brint'].collectPackets(path='/home/pcap/brint.pcap')
    nodes['brex'].collectPackets(path='/home/pcap/brex.pcap')

    printTerm("\n[LFT] Experiment is RUNNING successfully!")
    printTerm("[LFT] Press CTRL+C to finish experiment and tear down containers.")

except Exception as ex:
    printTerm(f"\n[LFT] Error during experiment: {ex}")
    collectLogs()
    unmakeChanges()
    raise ex

signal.pause()
