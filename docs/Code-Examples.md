# Code Examples Walkthrough (examples/)

The `examples/` directory contains ready-to-run scripts demonstrating every feature of LFT. Below is an exhaustive breakdown of each script.

----

## 1. Simple Host-to-Host Topology (SimpleTopologyExample.py)

Demonstrates the minimal possible topology in LFT: two hosts connected directly via a single `veth` pair without switches.

### Source Code
```python
from profissa_lft.host import Host

# Instantiate two host containers
h1 = Host('h1')
h2 = Host('h2')

h1.instantiate()
h2.instantiate()

# Create direct veth link: h1h2 <-> h2h1
h1.connect(h2, "h1h2", "h2h1")

# Assign IP addresses in 10.0.0.0/24 subnet
h1.setIp('10.0.0.1', 24, "h1h2")
h2.setIp('10.0.0.2', 24, "h2h1")

# Execute ping directly
h1.run("ping -c 3 10.0.0.2")
```

### Execution
```bash
python3 examples/SimpleTopologyExample.py
```

----

## 2. Single-Switch SDN Topology (simpleSDNTopology.py)

Sets up two hosts connected to an Open vSwitch switch controlled by a Ryu OpenFlow controller, with default routing to the host machine for Internet access.

### Key Operations
  1. Instantiates `h1`, `h2`, `s1` (Switch), and `c1` (Controller).
  2. Creates `veth` links connecting all nodes to the switch bridge.
  3. Launches Ryu manager listening on TCP port 9001: `c1.initController('10.0.0.4', 9001)`.
  4. Configures OVS bridge to connect to Ryu: `s1.setController('10.0.0.4', 9001)`.
  5. Configures host NAT masquerading via `s1.connectToInternet('10.0.0.5', 24, ...)`.
  6. Sets default gateway `10.0.0.5` on all nodes.

----

## 3. Dual-Subnet SDN Topology (TwoSubNetSDNExample.py)

Demonstrates inter-subnet routing across two separate Open vSwitch switches managed by a shared Ryu controller.

### Architecture
  * **Subnet 1 (10.0.0.0/24)**: Switch `s1` with host `h1` (10.0.0.1).
  * **Subnet 2 (11.0.0.0/24)**: Switch `s2` with host `h2` (11.0.0.1).
  * **Management Subnet (12.0.0.0/24)**: Controller `c1` (12.0.0.1).
  * **Inter-Switch Trunk Link**: `s1.connect(s2, "s1s2", "s2s1")` connects the two OVS bridges.
  * **Static Inter-Subnet Routes**:
    <code python>
    h1.addRoute("11.0.0.0", 24, "h1s1") # h1 reaches Subnet 2
    h2.addRoute("10.0.0.0", 24, "h2s2") # h2 reaches Subnet 1
```

----

## 4. Multi-Controller Distributed SDN (MultiControllerTwoSubNetExample.py)

Demonstrates a distributed SDN control plane where each switch is managed by its own independent controller:
  * Switch `s1` is governed by Controller `c1` on 12.0.0.1:9001.
  * Switch `s2` is governed by Controller `c2` on 13.0.0.1:9001.
  * Cross-domain traffic traverses the inter-switch trunk link `s1s2 <-> s2s1`.

----

## 5. Packet Capture with Time Rotation (collectPacketsSDNTopology.py)

Starts background packet capturing using `tshark` on the switch interface, rotating PCAP capture files every 10 seconds, and copies the resulting traces to the host.

### Source Code
```python
filePath = "/home/packets"
fileName = "test.pcap"

s1.run(f"mkdir -p {filePath}")

# Start background sniffing with 10-second file rotation
s1.collectPackets(["s1"], f"{filePath}/{fileName}", rotateInterval=10)

# Generate sample traffic
h1.run("ping -c 5 10.0.0.2")
h2.run("ping -c 5 10.0.0.1")
sleep(12)

# Copy captured PCAPs to the host directory
s1.copyContainerToLocal(filePath, "./")
```

----

## 6. SwitchMeter with CICFlowMeter (swtichmeterCollectPackets.py)

Utilizes the specialized `SwitchMeter` class to perform real-time packet capturing and automatic feature extraction into CSV flow records:

```python
from profissa_lft.switchmeter import SwitchMeter

s1 = SwitchMeter('s1')
s1.instantiate()

# Captures on the bridge interface and generates bidirectional CSV flow records
s1.collectPacketsCICFlowMeter(interfaceName="s1", outputPath="/home/packets", rotateInterval=10)
```

----

## 7. NetFlow v5 Export and Analysis (netflowEnablementExample.py)

Configures Open vSwitch to generate and export NetFlow v5 flow records to a host-based `nfcapd` collector on UDP port 2055, and parses them with `nfdump`.

### Source Code
```python
# 1. Start nfcapd collector on the host
subprocess.run("mkdir -p netflow && nfcapd -w -D -l ./netflow -p 2055", shell=True)

# 2. Enable NetFlow export on OVS switch pointing to host IP
s1.enableNetflow("s1", "10.0.0.5", "2055")

# 3. Generate traffic
h1.run("ping -c 10 10.0.0.2")
sleep(20)

# 4. Read and display flows with nfdump
res = subprocess.run("nfdump -r netflow/nfcapd.* -s ip/bytes -n 10", shell=True, capture_output=True, text=True)
print(res.stdout)
```

----

## 8. 4G/LTE Cellular Topology (simple4GTopology.py)

Builds an end-to-end 4G/LTE cellular network with 1 EPC, 1 eNodeB, and 2 UEs communicating over simulated ZMQ radio channels and a GNU Radio multi-UE broker:

```python
from profissa_lft.epc import EPC
from profissa_lft.enb import EnB
from profissa_lft.ue import UE

epc = EPC('epc')
enb = EnB("enb")
ue1 = UE('ue1')
ue2 = UE('ue2')

epc.instantiate()
enb.instantiate()
ue1.instantiate()
ue2.instantiate()

# Interconnect S1 and RF interfaces
enb.connect(epc, "enbepc", "epcenb")
ue1.connect(enb, "ue1enb", "enbue1")
ue2.connect(enb, "ue2enb", "enbue2")

# Provision UEs in the EPC database
epc.addNewUE(ue1.getNodeName(), "001010123456780", "172.16.0.2")
epc.addNewUE(ue2.getNodeName(), "001010123456789", "172.16.0.3")

# Launch services
epc.start()
enb.starGnuRadioMultiUE()
enb.start("11.0.0.1", 2101, "11.0.0.1", 2100)
ue1.start("11.0.0.2", 2001, "11.0.0.1", 2000)
ue2.start("11.0.0.6", 2011, "11.0.0.5", 2010)
```
