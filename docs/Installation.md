# Installation and Requirements

This guide provides step-by-step instructions for installing LFT and configuring its dependencies on native Linux environments and macOS.

----

## 1. System Requirements

LFT relies directly on Linux kernel networking primitives (network namespaces, virtual Ethernet pairs, `iptables`, and traffic control). 

### Recommended Environment
  * **Operating System**: Ubuntu 24.04 LTS (Desktop or Server) or Ubuntu 22.04 LTS.
  * **Kernel**: Linux 5.15+ (x86_64 or arm64).
  * **Python**: Python 3.9 or higher with `pip`.
  * **Docker**: Docker Engine 24.0+ (Docker Desktop or Docker CE).
  * **Hardware**: Minimum 4 CPU cores, 8 GB RAM, and 20 GB free disk space.

### macOS Compatibility (Apple Silicon & Intel)
Because macOS uses the Darwin kernel (which lacks native Linux network namespaces, Open vSwitch kernel datapaths, and `tc netem`), LFT cannot run natively on Darwin. 

However, LFT runs seamlessly on macOS using **OrbStack** (lightweight Linux VM technology):
```bash
# Install OrbStack on macOS
brew install orbstack

# Create and start an Ubuntu 24.04 virtual machine named "lft"
orbctl create ubuntu:24.04 lft

# Enter the virtual machine shell
orb -m lft
```
Inside the OrbStack VM, your macOS files are directly mounted at their native path (e.g., `/Users/marotta/...`), allowing native-speed development with full Linux kernel capabilities.

----

## 2. Installing System Dependencies

Before installing the Python package, ensure the required networking tools and Open vSwitch are installed on your Linux machine:

```bash
sudo apt update
sudo apt install -y \
    python3-pip \
    python3-dev \
    python3-pandas \
    python3-matplotlib \
    docker.io \
    openvswitch-switch \
    openvswitch-common \
    iproute2 \
    iptables \
    firewalld \
    net-tools \
    nfdump \
    tshark \
    tcpdump

# Start and enable the Open vSwitch service
sudo systemctl enable --now openvswitch-switch

# Add your user to the docker group
sudo usermod -aG docker $USER
newgrp docker
```

----

## 3. Installing LFT via Pip

Install the published package directly from PyPI:
```bash
pip3 install profissa_lft
```

Alternatively, for active development or source modification, clone the repository and install in editable mode:
```bash
git clone https://github.com/UnB-COMNET/lft.git
cd lft
chmod +x dependencies.sh
./dependencies.sh
pip3 install -e .
```

----

## 4. Pulling Required Docker Images

LFT uses specialized Docker images for its nodes, switches, controllers, and services. Pull the base images from Docker Hub:

```bash
# Core infrastructure
docker pull alexandremitsurukaihara/lst2.0:host
docker pull alexandremitsurukaihara/lst2.0:openvswitch
docker pull alexandremitsurukaihara/lst2.0:ryucontroller

# Security and monitoring tools
docker pull alexandremitsurukaihara/lst2.0:cicflowmeter
docker pull alexandremitsurukaihara/lft:perfsonar-testpoint-ubuntu

# Enterprise servers for attack/security scenarios
docker pull alexandremitsurukaihara/lst2.0:backup
docker pull alexandremitsurukaihara/lst2.0:file
docker pull alexandremitsurukaihara/lst2.0:web
docker pull alexandremitsurukaihara/lst2.0:mail
docker pull alexandremitsurukaihara/lst2.0:printer
docker pull alexandremitsurukaihara/lst2.0:seafile
docker pull alexandremitsurukaihara/lst2.0:linuxclient
```

----

## 5. Verifying the Installation

Run a quick test using the direct host-to-host topology example:
```bash
python3 examples/SimpleTopologyExample.py
```
If the command prints ping responses between `10.0.0.1` and `10.0.0.2`, your LFT environment is fully functional!
