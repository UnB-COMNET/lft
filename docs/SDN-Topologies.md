# SDN Topology Engineering

This guide explains how to construct programmable Software-Defined Networks (SDN) using LFT, Open vSwitch (OVS), and Ryu controllers.

----

## 1. Architecture of a Standard SDN Setup

```text
               [ Internet / Host Gateway (10.0.0.5) ]
                                 |
                          (hosts1 / s1host)
                                 |
                              [ s1 ] (OVS Bridge - 10.0.0.3)
                             /  |                   (s1h1)     /   |   \  (s1h2)
                   (h1s1)  /    |    \  (h2s1)
                          /     |                            [ h1 ]   |    [ h2 ]
                    10.0.0.1    |   10.0.0.2
                                |
                             (s1c1)
                             (c1s1)
                                |
                             [ c1 ] (Ryu Controller - 10.0.0.4:9001)
```

In this architecture:
  * **Switch (s1)**: Forwards traffic between hosts according to OpenFlow 1.3 rules pushed by the controller.
  * **Controller (c1)**: Runs the Ryu OpenFlow manager. In learning-switch mode, unknown MAC addresses trigger OpenFlow Packet-In messages to the controller, which installs flow rules on the switch.
  * **Hosts (h1, h2)**: Generate and consume network traffic.
  * **Host Gateway (10.0.0.5)**: Connects the emulated network to the physical host with NAT, granting external Internet access.

----

## 2. Complete Python Implementation

```python
from profissa_lft.host import Host
from profissa_lft.switch import Switch
from profissa_lft.controller import Controller

# 1. Instantiate nodes
h1 = Host('h1')
h2 = Host('h2')
s1 = Switch('s1')
c1 = Controller('c1')

h1.instantiate()
h2.instantiate()
s1.instantiate()
c1.instantiate()

# 2. Interconnect nodes using veth pairs
h1.connect(s1, "h1s1", "s1h1")
h2.connect(s1, "h2s1", "s1h2")
c1.connect(s1, "c1s1", "s1c1")

# 3. Assign IP addresses
h1.setIp('10.0.0.1', 24, "h1s1")
h2.setIp('10.0.0.2', 24, "h2s1")
s1.setIp('10.0.0.3', 24, 's1')
c1.setIp('10.0.0.4', 24, 'c1s1')

# 4. Start the Ryu Controller and bind the switch
c1.initController('10.0.0.4', 9001)
s1.setController('10.0.0.4', 9001)

# 5. Connect the switch to the host Internet gateway
s1.connectToInternet('10.0.0.5', 24, "s1host", "hosts1")

# 6. Configure default gateways
h1.setDefaultGateway('10.0.0.5', "h1s1")
h2.setDefaultGateway('10.0.0.5', "h2s1")
s1.setDefaultGateway('10.0.0.5', "s1")

print("SDN Topology is up and running!")
```

----

## 3. Traffic Shaping & Link Emulation

LFT makes it easy to introduce real-world impairments on any link:
```python
# Apply 40ms latency, 4ms jitter, and 20 Mbps rate limit on h1's interface
h1.setInterfaceProperties(
    interfaceName="h1s1",
    throughput="20mbit",
    delay="40ms",
    jitter="4ms"
)
```

----

## 4. Verification and Diagnostics

Inspect the active Open vSwitch state directly from the terminal:
```bash
# Check OVS bridge configuration and connected ports
docker exec s1 ovs-vsctl show

# Inspect active OpenFlow 1.3 flow tables
docker exec s1 ovs-ofctl -O OpenFlow13 dump-flows s1

# Test end-to-end ping between hosts
docker exec h1 ping -c 3 10.0.0.2

# Test external Internet connectivity
docker exec h1 ping -c 3 8.8.8.8
```
