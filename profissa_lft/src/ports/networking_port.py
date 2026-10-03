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
from abc import ABCMeta, abstractmethod

class NetworkingPort(metaclass=ABCMeta):    
    @abstractmethod
    def createVethPair(self, vethPairName1: str, vethPairName2: str):
        pass

    @abstractmethod
    def setIp(self, ip: str, mask: int, interfaceName: str, namespace=''):
        pass

    @abstractmethod
    def setLinkToNetns(self, linkName: str, namespace: str):
        pass

    @abstractmethod
    def setLinkUp(self, linkName: str, namespace=''):
        pass

    @abstractmethod
    def addRoute(self, ip: str, mask: int, linkName: str, gateway: str, namespace=''):
        pass