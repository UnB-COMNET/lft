# Troubleshooting and Teardown

This guide covers common issues encountered when running LFT and provides standard troubleshooting and cleanup commands.

----

## 1. Common Issues and Solutions

### Issue 1: OVS Database Connection Failed
**Symptom**:
`ovs-vsctl: unix:/var/run/openvswitch/db.sock: database connection failed (No such file or directory)`
**Cause**:
The switch container started, but the `ovsdb-server` daemon has not yet finished creating the UNIX domain socket before `ovs-vsctl add-br` was executed.
**Solution**:
LFT version 1.0.9+ includes an active retry loop in `Switch.instantiate()`. If running older code, ensure `Switch.instantiate()` pauses until the socket exists.

### Issue 2: Interface Name Too Long (IFNAMSIZ)
**Symptom**:
`RTNETLINK answers: Numerical result out of range`
**Cause**:
Linux kernel enforces a strict 15-character limit on network interface names. Names like `veth-switch-internal-mprinter` exceed this limit.
**Solution**:
Use compact naming conventions (e.g., `m1_brint` and `brint_m1`).

### Issue 3: Address Already in Use (IP / Port Collision)
**Symptom**:
`bind: address already in use` or IP collision on network bridge.
**Cause**:
Containers from a previous execution were not properly torn down and are still bound to the network.
**Solution**:
Run the global teardown procedure below.

----

## 2. Complete Environment Cleanup Procedure

To forcefully clean all LFT containers, network namespace symlinks, and orphaned `veth` interfaces, run:

```bash
# 1. Stop and remove all running Docker containers
docker rm -f $(docker ps -aq) 2>/dev/null || true

# 2. Clean up dangling network namespace links
sudo rm -rf /var/run/netns/*

# 3. Clean up orphaned Open vSwitch bridges on the host
sudo ovs-vsctl list-br | xargs -r -n 1 sudo ovs-vsctl del-br

# 4. Flush dangling iptables NAT rules
sudo iptables -t nat -F

# 5. Prune unused Docker network bridges
docker network prune -f
```

----

## 3. Diagnostic Commands

Useful commands for inspecting live network state:
```bash
# List all active network namespaces registered with LFT
ip netns list

# Run command inside a node's namespace directly from the host
sudo ip netns exec <nodeName> ip addr show
sudo ip netns exec <nodeName> ip route show

# View live traffic on a virtual interface
sudo tcpdump -i <interfaceName> -n -v
```
