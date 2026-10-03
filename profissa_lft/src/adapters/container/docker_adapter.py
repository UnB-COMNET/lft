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

import logging
import subprocess
import json
from ....exceptions import NodeInstantiationFailed
from ....constants import *
from ...ports.container_port import ContainerPort

class DockerAdapter(ContainerPort):
    def __init__(self):
        super()
        self.DOCKER = "docker"
        self.EXEC = "exec"
        self.INSPECT = "inspect"
        self.PS = "ps"
        self.CP = "cp"
        self.KILL = "kill"
        self.PULL = "pull"

    def instantiate(self, dockerImage="alexandremitsurukaihara/lst2.0:host", dockerCommand='', dns='8.8.8.8', memory='', cpus='', runCommand='') -> None:
        command = []
        
        def addDockerRun():
            command.append(DOCKER_RUN)

        def addRunOptions():
            command.append("-d")

        def addNetwork():
            command.append(NETWORK + "=none")

        def addContainerName():
            command.append(NAME + '=' + self.getNodeName())

        def addPrivileged():
            command.append(PRIVILEGED)

        def addDNS(dns):
            command.append(DNS + '=' + dns)

        def addContainerMemory(memory):
            if memory != '': 
                command.append(MEMORY + '=' + memory)

        def addContainerCPUs(cpus):
            if cpus != '': 
                command.append(CPUS + '=' + cpus)

        def addContainerImage(image):
            command.append(image)

        def addRunCommand(runCommand):
            command.append(runCommand)

        def buildCommand():
            return " ".join(command)

        if not self.__imageExists(dockerImage):
            logging.info(f"Image {dockerImage} not found, pulling from remote repository...")
            self.__pullImage(dockerImage)
        
        if dockerCommand == '':
            addDockerRun()
            addRunOptions()
            addNetwork()
            addContainerName()
            addPrivileged()
            addDNS(dns)
            addContainerMemory(memory)
            addContainerCPUs(cpus)
            addContainerImage(dockerImage)
            addRunCommand(runCommand)

        if dockerCommand != '':
            subprocess.run(dockerCommand, shell=True, capture_output=True)            
        else:
            subprocess.run(buildCommand(), shell=True, capture_output=True)
    

    def getContainerProcessId(self) -> int:
        out = subprocess.run(f"{self.DOCKER} {self.INSPECT} -f '{{{{.State.Pid}}}}' {self.getNodeName()}", shell=True, capture_output=True)
        return int(out.stdout.decode('utf8').replace('\n', ''))

    def delete(self) -> None:
        subprocess.run(f"{self.DOCKER} kill {self.getNodeName()} && docker rm {self.getNodeName()}", shell=True, capture_output=True)

    def run(self, command: str) -> str:
        command = command.replace('\"', 'DOUBLEQUOTESDELIMITER')
        command = f"{self.DOCKER} {self.EXEC} {self.getNodeName()} bash -c \"" + command + f"\""
        command = command.replace('DOUBLEQUOTESDELIMITER','\\"')
        return subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, text=True)
    
    def copyContainerToLocal(self, path, destPath):
        return subprocess.run(f"{self.DOCKER} {self.CP} {self.getNodeName()}:{path} {destPath}", shell=True, capture_output=True)

    def copyLocalToContainer(self, path, destPath):
        return subprocess.run(f"{self.DOCKER} {self.CP} {path} {self.getNodeName()}:{destPath}", shell=True, capture_output=True)

    def isActive(self):
        if subprocess.run(f"{self.DOCKER} {self.PS} | grep {self.getNodeName()}'", shell=True, capture_output=True).stdout.decode('utf8') != '': return True
        return False

    # Brief: Verifies if the image exists
    # Params:
    #   String image: Tag of the Docker image 
    # Return:
    #   True if the image exists locally
    def __imageExists(self, image: str) -> bool:
        out = subprocess.run(f"{self.DOCKER} {self.INSPECT} --type=image {image}", shell=True, capture_output=True)
        outJson = json.loads(out.stdout.decode('utf-8'))
        if outJson == []: return False
        else: return True

            
    # Brief: Pulls the image from a Docker Hub repository
    # Params:
    #   String image: Tag of the Docker image 
    # Return:
    #   True if the image exists locally
    def __pullImage(self, image):
        try: 
            subprocess.run(f"{self.DOCKER} {self.PULL} {image}", shell=True)
        except Exception as ex:
            logging.error(f"Error pulling non-existing {image} image: {str(ex)}")
            raise NodeInstantiationFailed(f"Error pulling non-existing {image} image: {str(ex)}")
