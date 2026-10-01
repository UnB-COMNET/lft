# Full API Reference (profissa_lft)

This document provides exhaustive documentation of all classes, methods, arguments, return types, and exceptions in the `profissa_lft` library.

----

## 1. Class: Node

Defined in `profissa_lft.node`. The abstract base class representing any emulated node.

| Method | Signature | Description |
| --- | --- | --- |
| ''__init__'' | ''(nodeName: str, dockerImage: str = "alexandremitsurukaihara/lft:host")'' | Initializes the node representation. |
| ''instantiate'' | ''(dockerImage: str = None, runCommand: str = None)'' | Launches the Docker container in privileged mode, obtains its PID, and symlinks its network namespace in ''/var/run/netns''. |
| ''connect'' | ''(node: Node, ifaceLocal: str, ifaceRemote: str)'' | Creates a ''veth'' pair and places each interface into the respective node's network namespace. |
| ''setIp'' | ''(ip: str, mask: int, iface: str)'' | Configures IPv4 address and CIDR prefix length on the specified interface. |
| ''setDefaultGateway'' | ''(ip: str, iface: str)'' | Sets the default gateway for the node (''ip route add default via <ip> dev <iface>''). |
| ''addRoute'' | ''(network: str, mask: int, iface: str)'' | Adds a static route to a target destination network. |
| ''setInterfaceProperties'' | ''(interfaceName: str, throughput: str, delay: str, jitter: str)'' | Applies traffic shaping (TC netem) for bandwidth rate, latency, and jitter. |
| ''run'' | ''(command: str) -> str'' | Executes a command synchronously inside the container via ''docker exec'' and returns output. |
| ''runBackground'' | ''(command: str)'' | Executes a command asynchronously in the container background without blocking. |
| ''copyContainerToLocal'' | ''(containerPath: str, localPath: str)'' | Copies files or directories from inside the container to the host machine. |
| ''copyLocalToContainer'' | ''(localPath: str, containerPath: str)'' | Copies files or directories from the host machine into the container. |
| ''enableForwarding'' | ''(ifaceIn: str, ifaceOut: str)'' | Enables IPv4 packet forwarding between two interfaces within the node. |
| ''setMtuSize'' | ''(iface: str, mtu: int)'' | Configures Maximum Transmission Unit (MTU) size on an interface (e.g., 9000 for jumbo frames). |
| ''terminate'' / ''delete'' | ''()'' | Stops and removes the Docker container, removes the namespace symlink in ''/var/run/netns'', and cleans up interfaces. |

----

## 2. Class: Host

Defined in `profissa_lft.host`. Inherits from `Node`. Represents general workstations, servers, or endpoints.

```python
from profissa_lft.host import Host

h1 = Host("h1", image="alexandremitsurukaihara/lft:host")
h1.instantiate()
```

----

## 3. Class: Switch

Defined in `profissa_lft.switch`. Inherits from `Node`. Represents an Open vSwitch (OVS) software bridge.

| Method | Signature | Description |
| --- | --- | --- |
| ''instantiate'' | ''(dockerImage="alexandremitsurukaihara/lft:openvswitch")'' | Starts OVS container, waits for ''ovsdb-server.sock'', and creates an OVS bridge named after the switch. |
| ''setController'' | ''(controllerIp: str, controllerPort: int)'' | Connects the OVS bridge to an SDN controller via OpenFlow 1.3 (''tcp:IP:Port''). |
| ''connectToInternet'' | ''(gatewayIp: str, mask: int, ifaceSwitch: str, ifaceHost: str)'' | Creates a veth link between the switch and the host, configuring iptables NAT masquerading. |
| ''collectPackets'' | ''(interfaces: list, outputPath: str, rotateInterval: int = 10)'' | Launches background ''tshark'' sniffing on the specified switch interfaces with time-based PCAP file rotation. |
| ''enableNetflow'' | ''(interface: str, collectorIp: str, collectorPort: str)'' | Configures Open vSwitch to export NetFlow v5 datagrams to a remote or local collector. |

----

## 4. Class: SwitchMeter

Defined in `profissa_lft.switchmeter`. Inherits from `Switch`. Provides inline packet capture and automated feature extraction using CICFlowMeter.

| Method | Signature | Description |
| --- | --- | --- |
| ''collectPacketsCICFlowMeter'' | ''(interfaceName: str, outputPath: str, rotateInterval: int)'' | Captures traffic on the switch interface and processes PCAPs through an embedded CICFlowMeter instance, generating CSV flow files. |

----

## 5. Class: Controller

Defined in `profissa_lft.controller`. Inherits from `Node`. Represents an SDN controller.

| Method | Signature | Description |
| --- | --- | --- |
| ''initController'' | ''(ip: str, port: int, appPath: str = None)'' | Starts the Ryu SDN manager inside the container listening on the given IP and port, optionally loading an application script (default: ''simple_switch_13.py''). |

----

## 6. Class: CICFlowMeter

Defined in `profissa_lft.cicflowmeter`. Inherits from `Node`. Used for offline or post-capture traffic analysis.

| Method | Signature | Description |
| --- | --- | --- |
| ''convertPcapIntoFlows'' | ''(pcapPath: str, outputPath: str)'' | Analyzes a PCAP capture file and extracts 83 bidirectional statistical network flow features into CSV format. |

----

## 7. Cellular 4G/LTE Classes: EPC, EnB, UE

Defined in `profissa_lft.epc`, `profissa_lft.enb`, and `profissa_lft.ue`.

#### Class: EPC (Evolved Packet Core)
  * `setEPCAddress(ip: str)`: Configures the MME/SPGW IP address.
  * `addNewUE(ueName: str, imsi: str, ip: str)`: Provisions a user equipment record in the HSS user database.
  * `start()`: Starts `srsepc` daemons.

#### Class: EnB (E-UTRAN Node B)
  * `setEPCAddress(ip: str)`: Sets target EPC IP address.
  * `setEnBAddress(ip: str)`: Sets the eNodeB local IP address.
  * `setMultiUEEnBAddr(txIp, txPort, rxIp, rxPort)`: Configures RF baseband ZMQ radio ports for multi-UE communication.
  * `starGnuRadioMultiUE()`: Launches the GNU Radio multi-channel frequency broker.
  * `start(txIp, txPort, rxIp, rxPort)`: Starts `srsenb` daemon.

#### Class: UE (User Equipment)
  * `setUEID(imsi: str)`: Configures the IMSI identity for the terminal.
  * `setDeviceName(device: str)`: Sets the RF frontend (e.g., `zmq` or `uhd`).
  * `setDeviceArgs(args: str)`: Sets device parameters (e.g., USRP IP and sample rate).
  * `start(txIp, txPort, rxIp, rxPort)`: Launches `srsue` and establishes the LTE bearer.

----

## 8. Class: Perfsonar

Defined in `profissa_lft.perfsonar`. Inherits from `Host`. Integrates perfSONAR testpoint functionality for automated network benchmarking.

  * `readLimitFile()`: Configures pScheduler test execution limits.
  * `addRouteException(network: str, mask: int)`: Adds routing exceptions for measurement endpoints.
  * `setHost(ip: str)`: Sets the measurement endpoint IP address.
