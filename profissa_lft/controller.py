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


class Controller(Node):
    kind = "controller"

    def __init__(self, nodeName: str) -> None:
        super().__init__(nodeName)
        self.__process = 0

    # Brief: Instantiate a controller container
    # Params:
    # Return:
    #   None
    def instantiate(self, dockerImage='alexandremitsurukaihara/lst2.0:ryucontroller', dockerCommand='') -> None:
        super().instantiate(dockerImage=dockerImage, dockerCommand=dockerCommand)

    # Brief: Instantiate a controller container, the ip and port will only be used if the command parameter is an empty list. In this case, will be instantiated a Ryu controller.
    # Params:
    #   String ip: Ip address to which the controller will be listening to
    #   int port: Number of the port that the controller will be listening to
    #   List<String> command: List of commands to execute in the controller to instantiate the controller
    # Return:
    #   None
    def initController(self, ip:str, port: int, command=[]):
        try:
            if len(command) == 0:
                subprocess.run(f"docker exec {self.getNodeName()} ryu-manager --ofp-listen-host={ip} --ofp-tcp-listen-port={port} /home/controller.py > /dev/null 2>&1 &", shell=True)
            else:
                for c in command: subprocess.run(c, shell=True)
        except Exception as ex:
            logging.error(f"Error while setting up controller {self.getNodeName()} in {ip}/{port}: {str(ex)}")
            raise Exception(f"Error while setting up controller {self.getNodeName()} in {ip}/{port}: {str(ex)}")

    def instantiate_local(self, controllerIp, controllerPort):
        process = self.__getProcess()
        if process == 0:
            try:
                self.__process = subprocess.Popen(f"ryu-manager --ofp-listen-host={controllerIp} --ofp-tcp-listen-port={controllerPort} controller.py > controller.log", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            except Exception as ex:
                logging.error(f"Error while creating the switch {self.getNodeName()}: {str(ex)}")
                raise NodeInstantiationFailed(f"Error while creating the switch {self.getNodeName()}: {str(ex)}")
        else:
            logging.error(f"Controller {self.getNodeName()} already instantiated")
            raise Exception(f"Controller {self.getNodeName()} already instantiated")
        
    def delete_local(self):
        process = self.__getProcess()
        if process != 0:
            try:
                self.__process.kill()
                _, stderr = self.__process.communicate()
            except Exception as ex:
                logging.error(f"Error while deleting the switch {self.getNodeName()}: {str(ex)}\nThreads error: {stderr}")
                raise NodeInstantiationFailed(f"Error while deleting the switch {self.getNodeName()}: {str(ex)}\nThreads error: {stderr}")
        else:
            logging.error(f"Can't delete {self.getNodeName()}. {self.getNodeName()} was not instantiated.")
            raise Exception(f"Can't delete {self.getNodeName()}. {self.getNodeName()} was not instantiated.")
        
    def __getProcess(self):
        return self.__process