# Lightweight Fog Testbed (LFT) - Complete Master Manual

*The comprehensive technical guide and reference manual for LFT (Lightweight Fog Testbed)*\
*COMNET Laboratory, University of Brasília (UnB)*

----

## Chapter 1: Introduction & Overview

The **Lightweight Fog Testbed (LFT)** is a Python-based emulation platform designed to orchestrate complex, heterogeneous network topologies for Fog and Edge computing, Software-Defined Networking (SDN), 4G/LTE mobile networks, and cybersecurity research.

LFT combines Docker containerization with Linux network namespaces, Open vSwitch, Ryu OpenFlow controllers, and srsRAN cellular emulation. It provides researchers with reproducible, high-fidelity network experimentation capabilities on commodity hardware.

----

## Chapter 2: System Architecture

LFT achieves isolation and control using four core pillars:
  1. **Linux Network Namespaces (netns)**: Containers run with `--net=none`, while LFT registers their network namespaces under `/var/run/netns/<nodeName>`.
  2. **Virtual Ethernet (veth) Pairs**: Point-to-point virtual links connect nodes across namespaces. Interface names must strictly not exceed 15 characters (Linux `IFNAMSIZ` limit).
  3. **Open vSwitch Switching**: Programmable OpenFlow 1.3 datapaths controlled by SDN controllers.
  4. **Traffic Control (tc netem)**: Emulates latency, jitter, packet loss, and rate limits directly inside the kernel scheduler.

----

## Chapter 3: Installation & Quick Start

Install prerequisites on Ubuntu 24.04 LTS:
```bash
sudo apt update && sudo apt install -y python3-pip docker.io openvswitch-switch iproute2 iptables tshark
pip3 install profissa_lft
```

To run on macOS, utilize OrbStack (`orbctl create ubuntu:24.04 lft`).

----

## Chapter 4: API Quick Reference

  * **Node**: Core base class providing `instantiate()`, `connect()`, `setIp()`, `setDefaultGateway()`, `addRoute()`, `setInterfaceProperties()`, `run()`, and `terminate()`.
  * **Host**: Workstations and server nodes.
  * **Switch**: Open vSwitch bridge supporting `setController()`, `connectToInternet()`, and `collectPackets()`.
  * **Controller**: Ryu SDN controller via `initController(ip, port)`.
  * **SwitchMeter**: Switch with inline CICFlowMeter flow extraction.
  * **EPC, EnB, UE**: Cellular 4G/LTE emulation suite based on srsRAN and ZMQ radio channels.
  * **Perfsonar**: Automated network benchmarking testpoint using pScheduler.

----

## Chapter 5: Code Examples

LFT includes 8 functional examples in `examples/`:
  * `SimpleTopologyExample.py`: Direct host-to-host veth connection.
  * `simpleSDNTopology.py`: Ryu controller + OVS switch + 2 hosts + NAT Internet gateway.
  * `TwoSubNetSDNExample.py`: Inter-subnet routing across dual OVS switches.
  * `MultiControllerTwoSubNetExample.py`: Distributed multi-controller SDN control plane.
  * `collectPacketsSDNTopology.py`: Packet capture with time rotation.
  * `swtichmeterCollectPackets.py`: Inline CICFlowMeter flow extraction.
  * `netflowEnablementExample.py`: NetFlow v5 export to host nfcapd.
  * `simple4GTopology.py`: Complete 4G/LTE cellular network with EPC, eNodeB, and UEs.

----

## Chapter 6: Experiments and Benchmarking Suite

The `experiment/` package provides automated benchmarks:
  * **Deployment Scalability (measure_deploy_time.py)**: Measures node provisioning time and memory footprint (RSS/VSZ) from 1 to N nodes, comparing LFT against Containernet/Mininet.
  * **Wired Benchmarks (wired_experiment.py)**: Compares Emu-Emu, Emu-Phy, and Phy-Phy setups measuring Throughput, RTT, and one-way Latency via perfSONAR.
  * **Wireless 4G Benchmarks (wireless_experiment.py)**: Compares Emu-Emu, Emu-Phy with Ettus USRP X300 SDR hardware, and Phy-Phy.

----

## Chapter 7: Security Scenario (UNBCA / CIDDS)

Located in `scenario/UNBCA_ATTACK_ENVIRONMENT`, this scenario emulates a 14-node corporate network across 4 subnets (DMZ, Server Farm, Office LAN, Management LAN, Attacker LAN):
  * **Benign Traffic Engine**: Simulates human employee workday schedules (web browsing, emails, network printing, file synchronization, administrative SSH).
  * **Malicious Attacks**: Automated port scanning, DoS (SYN flood, HTTP flood), and password brute-forcing.
  * **Data Generation**: Produces labeled CSV flow datasets with 83 statistical attributes using CICFlowMeter (CIDDS-001 evaluation benchmark).

----

## Chapter 8: Troubleshooting & Teardown

Global cleanup script:
```bash
docker rm -f $(docker ps -aq) 2>/dev/null || true
sudo rm -rf /var/run/netns/*
sudo ovs-vsctl list-br | xargs -r -n 1 sudo ovs-vsctl del-br
sudo iptables -t nat -F
```
