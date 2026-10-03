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

from ...exceptions import *
from ...constants import *
from abc import ABCMeta, abstractmethod
from subprocess import CompletedProcess


class ContainerPort(metaclass=ABCMeta):
    def __init__(self):
        self.__nodeName = ''

    def getNodeName(self) -> str:
        return self.__nodeName
    
    def setNodeName(self, nodeName: str) -> str:
        self.__nodeName = nodeName

    @abstractmethod
    def instantiate(self, dockerImage: str, dockerCommand: str, dns: str, memory: str, cpus: str, runCommand: str) -> None:
        pass

    @abstractmethod
    def getContainerProcessId(self) -> int:
        pass

    @abstractmethod
    def delete(self) -> None:
        pass

    @abstractmethod
    def run(self, command: str) -> CompletedProcess:
        pass

    @abstractmethod
    def copyContainerToLocal(self, path: str, destPath: str) -> None:
        pass

    @abstractmethod
    def copyLocalToContainer(self, path: str, destPath: str) -> None:
        pass

    @abstractmethod
    def isActive(self) -> bool:
        pass