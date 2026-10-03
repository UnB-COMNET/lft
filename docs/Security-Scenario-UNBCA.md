# Security Scenario: UNBCA / CIDDS

Located in `scenario/UNBCA_ATTACK_ENVIRONMENT`, this scenario emulates a realistic corporate enterprise network designed to reproduce the **CIDDS-001** intrusion detection evaluation benchmark.

It simulates background benign employee traffic alongside targeted cyberattacks, capturing full packet traces and extracting 83 bidirectional flow features using CICFlowMeter.

----

## 1. Enterprise Network Topology

The scenario orchestrates 14 Docker containers distributed across 4 segregated subnets connected by Open vSwitch bridges (`br_int` and `br_ext`):

```text
               [ External Attacker LAN (192.168.50.0/24) ]
                                    |
                            [ attacker_ext ]
                                    |
                        (External OVS: br_ext)
                                    |
                           [ Gateway / DMZ ]
                        (192.168.100.0/24: gwext)
                                    |
                        (Internal OVS: br_int)
                                    |
      +-----------------------------+-----------------------------+
      |                             |                             |
[ Server Farm ]             [ Office Workstations ]       [ Management ]
(192.168.200.0/24)          (192.168.210.0/24)            (192.168.220.0/24)
- web (HTTP / HTTPS)        - office1 (Client)            - admin (IT Admin)
- mail (SMTP / IMAP)        - office2 (Client)            - dev (Developer)
- fileserver (NFS / SMB)    - printer1 (CUPS Printer)
- backup (Backup server)    - attacker_int (Rogue insider)
- seafile (Private Cloud)
```

----

## 2. Benign Traffic Generation Engine

Employees within the office and management subnets follow realistic behavioral models defined in `client_behaviour/*.ini` (`office.ini`, `developer.ini`, `management.ini`, `administrator.ini`).

The automation framework in `automation/packages/` orchestrates:
  * **Web Browsing (`browsing.py`)**: Emulates visits to internal web applications and external search engines with variable think times.
  * **Email Exchange (`mailing.py`)**: Sends and receives messages with attachments between internal clients and the mail server.
  * **Printing (`printing.py`)**: Dispatches print spool jobs to `printer1`.
  * **File Synchronization (`copyFiles.py`, `copySea.py`)**: Syncs and retrieves documents from Seafile and SMB file shares.
  * **Administrative SSH (`sshConnections.py`)**: Simulates administrative management sessions to server nodes.
  * **Working Schedules (`setupWorkingSchedule.py`)**: Replicates human office hours, lunch breaks, and intermittent idle periods.

----

## 3. Attack Vectors & Malicious Automation

Attacks are launched from both an external attacker (`attacker_ext`) and a compromised internal workstation (`attacker_int`):

  * **Reconnaissance & Port Scanning (`scan.py`)**:
    * TCP SYN scans across subnet IP ranges.
    * Port sweeps against common server ports (22, 80, 443, 8082, 9100).
  * **Denial of Service (DoS) (`dos.py`)**:
    * SYN Flood against the web and mail servers.
    * HTTP Stress and Slowloris attacks.
    * High-volume UDP flooding.
  * **Brute-Force Authentication (`bruteForce.py`)**:
    * Dictionary-based credential guessing against SSH and Web logins using password lists (`password.txt`, `password-long.txt`).

----

## 4. Execution Scripts & Dataset Generation

The scenario provides two primary entry points:

### 1. Real-Time Packet Sniffing (cids.py)
```bash
python3 scenario/UNBCA_ATTACK_ENVIRONMENT/cids.py
```
  * Instantiates all 14 containers and configures IP subnets and OVS bridges.
  * Starts automated benign user schedules and attack scripts.
  * Launches `tshark` sniffing on switch interfaces, saving live PCAP files.

### 2. Inline CICFlowMeter Dataset Generation (cidds.py)
```bash
python3 scenario/UNBCA_ATTACK_ENVIRONMENT/cidds.py
```
  * Generates network traffic while running the CICFlowMeter engine.
  * Converts captured packets into labeled CSV flow files containing 83 statistical flow features (duration, packet counts, inter-arrival times, flags, flow bytes/s).
  * Flow records are saved in `scenario/UNBCA_ATTACK_ENVIRONMENT/flows/`.

### 3. Teardown & Environment Cleanup
```bash
./scenario/UNBCA_ATTACK_ENVIRONMENT/cleanup.sh
```
Removes all 14 containers, deletes OVS bridges, and clears namespace symlinks.
