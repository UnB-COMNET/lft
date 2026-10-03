# Copyright (C) 2022 Alexandre Mitsuru Kaihara
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>

import logging
import shlex
import subprocess
import time

from profissa_lft.exceptions import NodeInstantiationFailed
from profissa_lft.node import Node


class Switch(Node): 
    kind = "switch"

    # Brief: Instantiate a switch class, where it can be defined to capture flow data of each interface added
    # Params:
    # Return:
    #   None
    def __init__(self, name: str, hostPath='', containerPath=''):
        super().__init__(name)
        if hostPath == '' and containerPath == '':
            self.__mount = False
        elif hostPath != '' and containerPath != '':
            self.__hostPath = hostPath
            self.__containerPath = containerPath
            self.__mount = True
        else: 
            raise Exception(f"Invalid hostPath and containerPath mount point on {self.getNodeName()}. hostPath and containerPath cannot be null")

    # Brief: Instantiate an OpenvSwitch switch container
    # Params:
    # Return:
    #   None
    def instantiate(self, 
                    image='alexandremitsurukaihara/lst2.0:openvswitch', 
                    controllerIP='', 
                    controllerPort=-1, 
                    networkMode='none', 
                    protocols='OpenFlow13',
                    datapath_id=None,
                    sw_desc=None) -> None:
        mount = ''
        if self.__mount: mount = f'-v {self.__hostPath}:{self.__containerPath}'
        
        super().instantiate(dockerCommand=f"docker run -d --privileged --cap-add=NET_ADMIN --network={networkMode} {mount} --name={self.getNodeName()} {image}")
        br = self.getNodeName()
        try:
            # ovsdb-server needs a moment inside the fresh container. add-br against
            # a missing db.sock fails silently and only surfaces two lines below as
            # 'no row "sN" in table Bridge'.
            for _ in range(50):
                if subprocess.run(f"docker exec {br} ovs-vsctl show", shell=True,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                    break
                time.sleep(0.2)

            # Create bridge and set it up
            subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl add-br {self.getNodeName()}",
                           shell=True, check=True)
            subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl set bridge {self.getNodeName()} protocols={protocols}", shell=True)

            if datapath_id:
                # fixes the deviceId in ONOS (derived from de DPID)
                subprocess.run(
                    f"docker exec {br} ovs-vsctl set bridge {br} "
                    f"other-config:datapath-id={shlex.quote(datapath_id)}",
                    shell=True, check=True
                )
            
            if sw_desc:
                # switch annotation to easily identify switches. ONOS shows it in device annotations
                subprocess.run(
                    f"docker exec {br} ovs-vsctl set bridge {br} "
                    f"other-config:dp-desc={shlex.quote(sw_desc)}",
                    shell=True, check=True
                )

            subprocess.run(f"docker exec {self.getNodeName()} ip link set {self.getNodeName()} up", shell=True)
        except Exception as ex:
            logging.error(f"Error while creating the switch {self.getNodeName()}: {str(ex)}")
            raise NodeInstantiationFailed(f"Error while creating the switch {self.getNodeName()}: {str(ex)}")
        # Link it to a controller
        if controllerIP != '' and controllerPort != -1:
            self.setController(controllerIP, controllerPort)

    # Brief: Set the controller to which the switch will be connecting to
    # Params:
    #   String ip: Controller's IP address
    #   String port: Controller's port
    # Return:
    #   None
    def setController(self, ip:str, port: int) -> None:
        try:
            subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl set-controller {self.getNodeName()} tcp:{ip}:{str(port)}", shell=True)
        except Exception as ex:
            logging.error(f"Error connecting switch {self.getNodeName()} to controller on IP {ip}/{port}: {str(ex)}")
            raise Exception(f"Error connecting switch {self.getNodeName()} to controller on IP {ip}/{port}: {str(ex)}")

    # Brief: Creates a port in OpenvSwitch bridge
    # Params:
    #   String nodeName: The name of the bridge is for default the same name of the switch container
    #   String peerName: Name of the interface to connect to the switch
    # Return:
    #   None
    def __createPort(self, nodeName, peerName) -> None:
        try:
            subprocess.run(f"docker exec {nodeName} ovs-vsctl add-port {nodeName} {peerName}", shell=True)
        except Exception as ex:
            logging.error(f"Error while creating port {peerName} in switch {nodeName}: {str(ex)}")
            raise Exception(f"Error while creating port {peerName} in switch {nodeName}: {str(ex)}")

    # Brief: Set Ip to an interface (the ip must be set only after connecting it to a container)
    # Params:
    #   String ip: IP address to be set to peerName interface
    #   int mask: Integer that represents the network mask
    #   String node: Reference to the node it is connected to this container to discover the intereface to set the ip to
    # Return:
    def setIp(self, ip: str, mask: int, interfaceName='') -> None:
        if interfaceName == '':
            interfaceName = self.getNodeName()
        self._Node__setIp(ip, mask, interfaceName)
    
    def enableNetflow(self, destIp: str, destPort: int, activeTimeout=60)  -> None:
        try:
            subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl -- set Bridge {self.getNodeName()} netflow=@nf --  --id=@nf create  NetFlow  targets=\\\"{destIp}:{destPort}\\\"  active-timeout={activeTimeout}", shell=True)
        except Exception as ex:
            logging.error(f"Error setting Netflow on {self.getNodeName()} switch: {str(ex)}")
            raise Exception(f"Error setting Netflow on {self.getNodeName()} switch: {str(ex)}")

    def clearNetflow(self) -> None:
        try:
            subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl clear Bridge {self.getNodeName()} netflow", shell=True)
        except Exception as ex:
            logging.error(f"Error clearing Netflow on {self.getNodeName()} switch: {str(ex)}")
            raise Exception(f"Error clearing Netflow on {self.getNodeName()} switch: {str(ex)}")

    def enablesFlow(self, destIp: str, destPort: int, header=128, sampling=64, polling=10)  -> None:
        try:
            subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl -- --id=@s create sFlow agent={self.getNodeName()} target=\\\"{destIp}:{destPort}\\\" header={str(header)} sampling={str(sampling)} polling={str(polling)} -- set Bridge {self.getNodeName()} sflow=@s", shell=True)
        except Exception as ex:
            logging.error(f"Error setting sFlow on {self.getNodeName()} switch: {str(ex)}")
            raise Exception(f"Error setting sFlow on {self.getNodeName()} switch: {str(ex)}")

    def clearsFlow(self) -> None:
        try:
            subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl clear Bridge {self.getNodeName()} sflow", shell=True)
        except Exception as ex:
            logging.error(f"Error clearing sFlow on {self.getNodeName()} switch: {str(ex)}")
            raise Exception(f"Error clearing sFlow on {self.getNodeName()} switch: {str(ex)}")

    def enableIPFIX(self, destIp: str, destPort: int, obsDomainId=123, obsPointId=456, cacheActiveTimeout=60, cacheMaxFlow=60, enableInputSampling=False, enableTunnelSampling=True) -> None:
        try:    
            subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl -- set Bridge {self.getNodeName()} ipfix=@i -- --id=@i create IPFIX targets=\\\"{destIp}:{destPort}\\\" obs_domain_id={str(obsDomainId)} obs_point_id={str(obsPointId)} cache_active_timeout={str(cacheActiveTimeout)} cache_max_flows={str(cacheMaxFlow)} other_config:enable-input-sampling={str(enableInputSampling).lower()} other_config:enable-tunnel-sampling={str(enableTunnelSampling).lower()}", shell=True)
        except Exception as ex:
            logging.error(f"Error setting IPFIX on {self.getNodeName()} switch: {str(ex)}")
            raise Exception(f"Error setting IPFIX on {self.getNodeName()} switch: {str(ex)}")

    def clearIPFIX(self) -> None:
        try:
            subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl clear Bridge {self.getNodeName()} ipfix", shell=True)
        except Exception as ex:
            logging.error(f"Error clearing IPFIX on {self.getNodeName()} switch: {str(ex)}")
            raise Exception(f"Error clearing IPFIX on {self.getNodeName()} switch: {str(ex)}")

    # Brief: Set up the tshark to sniff all the packets into pcap files
    # Params:
    #   List<Node> nodes: References of the nodes connected to this switch to sniff packets
    #   boolean sniffAll: If sniff all is set  
    # Return:
    def collectFlows(self, nodes=[], path="", rotateInterval=60, sniffAll=False) -> None:
        try:
            interfaces = self._Node__getAllInterfaces()
            if sniffAll is False:
                if len(nodes) > 0:
                    interfaces = [self._Node__getThisInterfaceName(node) for node in nodes]
                    interfaces.append(self.getNodeName())
                else:
                    raise Exception(f"Expected at least one node reference to sniff packets on {self.getNodeName()} switch")
            interfaces = sorted(set(interfaces) - {"lo", "ovs-system"})
            if not interfaces:
                raise Exception(f"No interfaces found to capture on {self.getNodeName()}")
            opts = " ".join([f"-i {iface}" for iface in interfaces])
            pidfile = f"{path}/tshark.pid"
            errfile = f"{path}/tshark.err"
            cmd = (
                f"docker exec {self.getNodeName()} sh -lc "
                f"\"mkdir -p '{path}' && "
                f"nohup tshark -n {opts} "
                f"-b duration:{int(rotateInterval)} -b files:10 "
                f"-w '{path}/dump.pcapng' "
                f">/dev/null 2>'{errfile}' & echo $! > '{pidfile}'\""
            )
            subprocess.run(cmd, shell=True, check=False)
        except Exception as ex:
            logging.error(f"Error set the collector on {self.getNodeName()}: {str(ex)}")
            raise

    def collectFlowsTcpdump(
        self,
        nodes=[],
        path="",
        rotateInterval=600,
        sniffAll=False,
        bpf_filter="(tcp port 80 or tcp port 443 or icmp)",
        snapshot_idx: int | None = None,
    ) -> None:
        swname = self.getNodeName()

        interfaces = self._Node__getAllInterfaces()
        if not sniffAll:
            if not nodes:
                logging.info(f"[tcpdump] {swname}: skipping (no nodes passed and sniffAll=False)")
                return
            interfaces = [self._Node__getThisInterfaceName(n) for n in nodes]

        interfaces = sorted(set(interfaces) - {"lo", "ovs-system"})
        if not interfaces:
            logging.info(f"[tcpdump] {swname}: skipping (no capture interfaces after filtering)")
            return

        outdir = f"{path}"

        # Use filter only if not empty/None
        filter_part = f" {shlex.quote(bpf_filter)}" if bpf_filter else ""

        for iface in interfaces:
            pcapfile = f"{outdir}/{snapshot_idx}%{iface}.pcap"

            inner = (
                f"mkdir -p {shlex.quote(outdir)} && chmod 777 {shlex.quote(outdir)}; "
                f"nohup timeout -s INT {int(rotateInterval)} "
                f"tcpdump -Z root -i {shlex.quote(iface)} -nn -U -s 0 "
                f"-w {shlex.quote(pcapfile)}"
                f"{filter_part} "
                f">/dev/null 2>&1 &"
            )

            cmd = ["docker", "exec", swname, "sh", "-lc", inner]
            res = subprocess.run(cmd, capture_output=True, text=True)

            if res.returncode != 0:
                logging.warning(
                    f"[tcpdump] FAIL {swname}:{iface} rc={res.returncode} "
                    f"stderr={res.stderr.strip()} stdout={res.stdout.strip()}"
                )
            else:
                logging.info(f"[tcpdump] {swname}:{iface} -> {outdir}")

