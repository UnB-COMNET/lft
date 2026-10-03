# Copyright (C) 2022 Alexandre Mitsuru Kaihara
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.


import logging
import subprocess
from .node import Node
from .exceptions import NodeInstantiationFailed


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
    def instantiate(self, image='alexandremitsurukaihara/lst2.0:openvswitch', controllerIP='', controllerPort=-1) -> None:
        mount = ''
        if self.__mount: mount = f'-v {self.__hostPath}:{self.__containerPath}'
        super().instantiate(dockerCommand=f"docker run -d --network=none --privileged {mount} --name={self.getNodeName()} {image}")
        import time
        for _ in range(30):
            res = subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl show", shell=True, capture_output=True)
            if res.returncode == 0:
                break
            time.sleep(0.5)
        try:
            # Create bridge and set it up
            subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl add-br {self.getNodeName()}", shell=True)
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
    def __createPort(self, nodeName, peerInterfaceName) -> None:
        try:
            subprocess.run(f"docker exec {nodeName} ovs-vsctl add-port {nodeName} {peerInterfaceName}", shell=True)
        except Exception as ex:
            logging.error(f"Error while creating port {peerInterfaceName} in switch {nodeName}: {str(ex)}")
            raise Exception(f"Error while creating port {peerInterfaceName} in switch {nodeName}: {str(ex)}")

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
    

    def enableNetflow(self, bridgeName: str, destIp: str, destPort: int, activeTimeout=60)  -> None:
        try:
            subprocess.run(f"docker exec {self.getNodeName()} ovs-vsctl -- set Bridge {bridgeName} netflow=@nf --  --id=@nf create  NetFlow  targets=\\\"{destIp}:{destPort}\\\"  active-timeout={activeTimeout}", shell=True)
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
    #   List<str> interfaceNames: Name of interfaces to sniff packets
    #   str path: Path to where the file will be placed
    # Return:
    def collectPackets(self, interfaceNames=[], path='', rotateInterval=60) -> None:
        if ".pcap" not in path:
            raise Exception("Path should contain the file name and extension .pcap")
        try:
            interfaces = interfaceNames
            if len(interfaceNames) == 0:
                interfaces = self._Node__getAllInterfaces()
            interfaces = list(set(interfaces) - set(['lo', 'ovs-system']))
            options = ['-i ' + interface for interface in interfaces]
            options = ' '.join(options)
            subprocess.run(f"docker exec {self.getNodeName()} tshark {options} -b duration:{rotateInterval} -w {path} > /dev/null 2>&1 &", shell=True)
        except Exception as ex:
            logging.error(f"Error set the collector on {self.getNodeName()}: {str(ex)}")
            raise Exception(f"Error set the collector on {self.getNodeName()}: {str(ex)}")

    # Brief: Set default route to forward all incoming packets to s1 bridge and let the bridge handle the forwarding
    # Params:
    # Return:
    def __addDefaultRoute(self) -> None:
        try:
            subprocess.run(f"docker exec {self.getNodeName()} ip route add 0.0.0.0/0 dev {self.getNodeName()}", shell=True)
        except Exception as ex:
            logging.error(f"Error adding route default route for switch {self.getNodeName()}: {str(ex)}")
            raise Exception(f"Error adding route default route for switch {self.getNodeName()}: {str(ex)}")
