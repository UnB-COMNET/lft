# Copyright (C) 2024 Alexandre Mitsuru Kaihara
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

from ...ports.networking_port import NetworkingPort
from subprocess import run

class IpRouteAdapter(NetworkingPort):
    def createVethPair(self, vethPairName1, vethPairName2):
        return run(f"ip link add {vethPairName1} type veth peer name {vethPairName2}", shell=True)
    
    def setIp(self, ip, mask, interfaceName, namespace=''):
        return run(f"ip {self.__getRunNetns(namespace)} addr add {ip}/{mask} dev {interfaceName}", shell=True)

    def setLinkToNetns(self, linkName, namespace):
        return run(f"ip link set {linkName} netns {namespace}", shell=True)

    def setLinkUp(self, linkName, namespace=''):
        return run(f"ip {self.__getRunNetns(namespace)} link set {linkName} up", shell=True)

    def addRoute(self, ip, mask, linkName, gateway, namespace=''):
        return run(f"ip {self.__getRunNetns(namespace)} route add {ip}/{mask} via {gateway} dev {linkName}", shell=True)

    def __getRunNetns(self, namespace):
        if (namespace != ''):
            return f"-n {namespace}"
        return ''