#!/usr/bin/env python3
import os
import signal
import sys
import subprocess
from glob import glob
from configparser import ConfigParser

from profissa_lft.host import Host
from profissa_lft.switch import Switch
from profissa_lft.controller import Controller
from profissa_lft.node import Node
from profissa_lft.cicflowmeter import CICFlowMeter

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


def convertPcap():
    printTerm(f"[LFT] Converting pcap files with CICFlowMeter")
    pcaps = glob('flows/brint/*.pcap') + glob('flows/brex/*.pcap') + glob('flows/brint/*') + glob('flows/brex/*')
    pcaps = list(set([p for p in pcaps if os.path.isfile(p) and ('.pcap' in p or p.endswith('.pcap'))]))

    if len(pcaps) == 0:
        printTerm("[LFT] No PCAP files found to convert.")
        return

    hostPath = os.path.abspath('flows')
    containerPath = '/home/flows'

    printTerm(f"[LFT] ... Converting {len(pcaps)} PCAP Files with CICFlowMeter")
    cicflowmeter = CICFlowMeter('cic', hostPath, containerPath)
    cicflowmeter.instantiate()
    for pcap in pcaps:
        cicflowmeter.convertPcapIntoFlows('/home/' + pcap, containerPath)
    cicflowmeter.delete()

    printTerm(f"[LFT] ... Merging all CSV Files")
    csvs = glob('flows/*.csv')
    if len(csvs) == 0:
        return

    csv_content = ''
    for csv_file in csvs:
        with open(csv_file, 'r') as f:
            csv_content += f.read()

    printTerm(f"[LFT] ... Removing Duplicate Headers")
    lines = csv_content.split('\n')
    header = lines[0] if lines else ''
    filtered_lines = [l for l in lines if 'Flow ID' not in l and l.strip()]
    final_content = header + '\n' + '\n'.join(filtered_lines) + '\n'

    subprocess.run('rm -f flows/dump*', shell=True)
    report_file = os.path.join(hostPath, 'final_report.csv')
    printTerm(f"[LFT] ... Saving Final Report to {report_file}")
    with open(report_file, 'w') as f:
        f.write(final_content)


def signal_handler(sig, frame):
    print('\nYou pressed Ctrl+C!')
    unmakeChanges()
    convertPcap()
    sys.exit(0)


def collectLogs():
    printTerm(f"[LFT] Collecting Client Logs")
    os.makedirs('logs', exist_ok=True)
    hosts = ['e1', 'e2', 'm1', 'm2', 'm3', 'm4', 'o1', 'o2', 'd1', 'd2', 'd3', 'd4', 'd5', 'd6', 'd7', 'd8', 'd9', 'd10', 'd11', 'd12', 'd13']
    ips = ['50.3', '50.4', '200.2', '200.3', '200.4', '200.5', '210.2', '210.3', '220.2', '220.3', '220.4', '220.5', '220.6', '220.7', '220.8', '220.9', '220.10', '220.11', '220.12', '220.13', '220.14']

    def getLog(ip, host):
        subprocess.run(f'docker cp {host}:/home/debian/log/192.168.{ip}.log logs/192.168.{ip}.log > /dev/null 2>&1', shell=True)

    [getLog(ip, host) for ip, host in zip(ips, hosts)]


def printTerm(string: str) -> None:
    print(string, flush=True)


signal.signal(signal.SIGINT, signal_handler)

try:
    printTerm("===================================================================")
    printTerm(" LFT - Security Attack Scenario (CIDDS Full Multi-Subnet Dataset)")
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

    # 7. Set Office Subnet
    createPrinter('oprinter', office_subnet)
    createLinuxClient('o1', nodes['brint'], office_subnet, 2)
    createLinuxClient('o2', nodes['brint'], office_subnet, 3)

    # 8. Set Developer Subnet
    createPrinter('dprinter', developer_subnet)
    createLinuxClient('d1', nodes['brint'], developer_subnet, 2)
    createLinuxClient('d2', nodes['brint'], developer_subnet, 3)
    createLinuxClient('d3', nodes['brint'], developer_subnet, 4)
    createLinuxClient('d4', nodes['brint'], developer_subnet, 5)
    createLinuxClient('d5', nodes['brint'], developer_subnet, 6)
    createLinuxClient('d6', nodes['brint'], developer_subnet, 7)
    createLinuxClient('d7', nodes['brint'], developer_subnet, 8)
    createLinuxClient('d8', nodes['brint'], developer_subnet, 9)
    createLinuxClient('d9', nodes['brint'], developer_subnet, 10)
    createLinuxClient('d10', nodes['brint'], developer_subnet, 11)
    createLinuxClient('d11', nodes['brint'], developer_subnet, 12)
    createLinuxClient('d12', nodes['brint'], developer_subnet, 13)
    createLinuxClient('d13', nodes['brint'], developer_subnet, 14)

    # 9. Set External Subnet
    createServer('eweb', webserver, external_subnet, 2)
    createLinuxClient('e1', nodes['brex'], external_subnet, 3)
    createLinuxClient('e2', nodes['brex'], external_subnet, 4)

    # 10. Configure Client Automation & Behaviors
    [setLinuxClientFileConfig(nodes[f'm{i}'], management_subnet, 'management') for i in range(1, 5)]
    [setLinuxClientFileConfig(nodes[f'o{i}'], office_subnet, 'office') for i in range(1, 3)]
    [setLinuxClientFileConfig(nodes[f'd{i}'], developer_subnet, 'administrator') for i in range(1, 3)]
    [setLinuxClientFileConfig(nodes[f'd{i}'], developer_subnet, 'developer') for i in range(3, 12)]
    [setLinuxClientFileConfig(nodes[f'd{i}'], developer_subnet, 'attacker') for i in range(12, 14)]
    [setLinuxClientFileConfig(nodes[f'e{i}'], external_subnet, 'external_attacker') for i in range(1, 3)]

    # 11. Start packet sniffing on switches
    nodes['brint'].collectPackets(path='/home/pcap/brint.pcap')
    nodes['brex'].collectPackets(path='/home/pcap/brex.pcap')

    printTerm("\n[LFT] Full Multi-Subnet Experiment is RUNNING successfully!")
    printTerm("[LFT] Press CTRL+C to finish experiment, convert PCAPs to CSV flows, and tear down.")

except Exception as ex:
    printTerm(f"\n[LFT] Error during experiment: {ex}")
    collectLogs()
    unmakeChanges()
    raise ex

signal.pause()
