<p align="center"><img src="../logos/lft-github.png" width="450" alt="LFT Logo"></p>

# Lightweight Fog Testbed (LFT)

The **Lightweight Fog Testbed (LFT)** (evolution of *LST 2.0*) is a high-performance, containerized emulation framework developed in Python. It is designed to orchestrate, emulate, benchmark, and evaluate complex and heterogeneous network topologies for **Fog Computing**, **Edge Computing**, **Software-Defined Networking (SDN)**, **4G/LTE Cellular Networks**, and **Network Security / Intrusion Detection**.

By leveraging lightweight Docker containers, Linux network namespaces (`netns`), virtual Ethernet (`veth`) pairs, **Open vSwitch (OVS)**, **Ryu SDN Controllers**, and **srsRAN**, LFT allows researchers and developers to deploy arbitrary network topologies on a single host machine or virtual machine with minimal CPU and memory overhead.

LFT also features built-in support for network performance characterization via **perfSONAR** and **pScheduler**, as well as labeled dataset generation for machine learning-based intrusion detection via **CICFlowMeter**.

----

## Documentation Table of Contents

  * [1. System Requirements & Installation](Installation.md)
    * System requirements (Ubuntu 24.04 LTS and macOS via OrbStack/Docker)
    * Python package installation (`profissa_lft`) and system dependencies
    * Docker images setup
  * [2. LFT Core Architecture](Architecture.md)
    * Linux Network Namespaces isolation
    * Virtual Ethernet (`veth`) pairs and inter-container switching
    * Open vSwitch & SDN Controller integration
    * Host gateway, routing, and NAT masquerading
    * Link emulation and traffic control (`tc netem`)
  * [3. Full API Reference (profissa_lft)](API-Reference.md)
    * Core class `Node` (lifecycle, networking, traffic control, execution, file transfers)
    * Class `Host`
    * Class `Switch` and `SwitchMeter`
    * Class `Controller`
    * Class `CICFlowMeter`
    * 4G/LTE Cellular Classes: `EPC`, `EnB`, `UE`
    * Class `Perfsonar`
    * Exceptions and constants
  * [4. SDN Topology Engineering](SDN-Topologies.md)
    * Building programmable SDN networks
    * Connecting Open vSwitch to Ryu OpenFlow controllers
    * Internet access via host NAT and default gateways
    * Link property emulation (bandwidth, latency, jitter, loss)
  * [5. Code Examples Walkthrough (examples/)](Code-Examples.md)
    * Simple direct host-to-host topology (`SimpleTopologyExample.py`)
    * Single-switch SDN topology with Ryu and Internet NAT (`simpleSDNTopology.py`)
    * Multi-subnet SDN network with inter-switch trunk (`TwoSubNetSDNExample.py`)
    * Distributed multi-controller SDN architecture (`MultiControllerTwoSubNetExample.py`)
    * Packet capture with time-based rotation (`collectPacketsSDNTopology.py`)
    * SwitchMeter with inline CICFlowMeter extraction (`swtichmeterCollectPackets.py`)
    * Open vSwitch NetFlow v5 export & analysis (`netflowEnablementExample.py`)
    * Complete 4G/LTE mobile network emulation (`simple4GTopology.py`)
  * [6. Experiments and Benchmarks (experiment/)](Experiments-and-Benchmarks.md)
    * Deployment & scalability benchmarks: LFT vs Containernet/Mininet (`measure_deploy_time.py`)
    * perfSONAR / pScheduler testbed integration (`pschedulerWrapper.py`, `experiment.py`)
    * Wired benchmarking: Emu-Emu, Emu-Phy, and Phy-Phy (`wired_experiment.py`)
    * Wireless 4G benchmarking: Emu-Emu, Emu-Phy with USRP SDR, and Phy-Phy (`wireless_experiment.py`)
    * Performance metrics: throughput, round-trip time (RTT), latency, memory and CPU overhead
  * [7. Security Scenario: UNBCA / CIDDS (scenario/)](Security-Scenario-UNBCA.md)
    * Realistic enterprise topology (DMZ, Server Farm, Office LAN, Management LAN, Attacker LAN)
    * Automated benign user behaviors (browsing, email, printing, file syncing, SSH)
    * Automated malicious attack vectors (port scanning, SYN/HTTP DoS, brute-force dictionary attacks)
    * PCAP packet capture and conversion to 83-feature bidirectional flow datasets (CIDDS-001 benchmark)
  * [8. 4G/LTE Cellular Emulation (srsRAN)](Wireless-4G-Emulation.md)
    * Evolved Packet Core (EPC): MME, HSS, SPGW, user database provisioning
    * E-UTRAN Node B (eNodeB): RF frontend, ZMQ virtual radio, GNU Radio broker
    * User Equipment (UE): IMSI, USIM credentials, APN, TUN interface setup
  * [9. Docker Image Catalog](Docker-Images.md)
    * Technical specification of all 11 Docker images (base images, OVS, Ryu, servers, attack clients, meters)
  * [10. Troubleshooting & Teardown](Troubleshooting.md)
    * Resolving OVSDB database socket connection issues
    * Interface name length limitations (`IFNAMSIZ = 15`)
    * Cleaning orphaned network namespaces and lingering containers
  * [11. Complete Master Manual (All-in-One)](Master-Manual.md)
    * Unified documentation reference compiled into a single document

----

## Project Metadata

| Attribute | Value |
| --- | --- |
| **Package Name** | ''profissa_lft'' |
| **Current Version** | 1.0.9 |
| **Language** | Python >= 3.9 |
| **License** | GNU General Public License v3 (GPLv3) |
| **Institution** | University of Brasília (UnB) - COMNET Laboratory |
| **Repository** | [[https://github.com/UnB-COMNET/lft | github.com/UnB-COMNET/lft]] |
| **Wiki** | [[https://github.com/UnB-COMNET/lft/wiki | github.com/UnB-COMNET/lft/wiki]] |
| **Original Author** | Alexandre Mitsuru Kaihara |
