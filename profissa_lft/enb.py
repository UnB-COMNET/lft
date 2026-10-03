# Copyright (C) 2023 Alexandre Mitsuru Kaihara
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

from .perfsonar import Perfsonar
from .constants import *

class EnB(Perfsonar):
    def __init__(self, name: str, eNBConfigPath = '/etc/srsran/enb.conf'):
        super().__init__(name)
        self.defaultEnBConfigPath = eNBConfigPath
        self.buildDir = '/srsRAN/build'
        self.config = None
        self.defaultMultiUEPath = self.buildDir + '/multiUE.py'
        self.defaultSingleUEPath = self.buildDir + '/singleUE.py'

    def instantiate(self, dockerImage='alexandremitsurukaihara/lft:srsran-perfsonar-uhd4', dockerCommand = '', dns='8.8.8.8', runCommand='') -> None:
        super().instantiate(dockerImage=dockerImage, dockerCommand=dockerCommand, dns=dns, runCommand=runCommand)
        self.config = self.readConfigFile(self.defaultEnBConfigPath)

    def start(self, transmitterIp="*", transmitterPort=2000, receiverIp="localhost", receiverPort=2001) -> None:
        super().run(f"{self.buildDir}/srsenb/src/srsenb --rf.device_name=zmq --rf.device_args=\'fail_on_disconnect=true,tx_port=tcp://{transmitterIp}:{transmitterPort},rx_port=tcp://{receiverIp}:{receiverPort},id=enb,base_srate=11.52e6\' > enb.log")

    def stop(self) -> None:
        super().run("pkill -f -9 srsenb")

    def setDefaultEnBConfigPath(self, path: str) -> None:
        self.defaultEnBConfigPath = path

    def getdefaultEnBConfigPath(self) -> None:
        return self.defaultEnBConfigPath

    def setConfigurationFile(self, filePath: str, destinationPath='') -> None:
        if destinationPath == '':
            destinationPath = self.defaultEnBConfigPath
        super().copyLocalToContainer(filePath, destinationPath)

    # This option make sense only for emulated radio
    def starGnuRadioMultiUE(self, multiUEPath='') -> None:
        if multiUEPath == '':
            multiUEPath = self.defaultMultiUEPath
        super().run(f"python3 {multiUEPath}")

    def starGnuRadioSingleUE(self, singleUEPath='') -> None:
        if singleUEPath == '':
            singleUEPath = self.defaultSingleUEPath
        super().run(f"python3 {singleUEPath}")

    def stopGnuRadioMultiUE(self) -> None:
        super().run(f"pkill -f -9 multiUE")

    def setMultiUEEnBAddr(self, txIP: str, txPort: int, rxIP: str, rxPort: int, multiUEPath='') -> None:
        if multiUEPath == '':
            multiUEPath = self.defaultMultiUEPath
        self.run(f"sed -i \"/zeromq_req_source_2/s@\'tcp://.*\'@\'tcp://{txIP}:{txPort}\'@\" {multiUEPath}")
        self.run(f"sed -i \"/zeromq_rep_sink_0/s@'tcp://.*'@'tcp://{rxIP}:{rxPort}'@\" {multiUEPath}")

    def setMultiUEUE1Addr(self, UEIP: str, txPort: int, eNBIP: str, rxPort: int, multiUEPath='') -> None:
        if multiUEPath == '':
            multiUEPath = self.defaultMultiUEPath
        self.run(f"sed -i \"/zeromq_req_source_1/s@'tcp://.*'@'tcp://{UEIP}:{txPort}'@\" {multiUEPath}")
        self.run(f"sed -i \"/zeromq_rep_sink_2/s@'tcp://.*'@'tcp://{eNBIP}:{rxPort}'@\" {multiUEPath}")

    def setMultiUEUE2Addr(self, UEIP: str, txPort: int, eNBIP: str, rxPort: int, multiUEPath='') -> None:
        if multiUEPath == '':
            multiUEPath = self.defaultMultiUEPath
        self.run(f"sed -i \"/zeromq_req_source_0/s@'tcp://.*'@'tcp://{UEIP}:{txPort}'@\" {multiUEPath}")
        self.run(f"sed -i \"/zeromq_rep_sink_1/s@'tcp://.*'@'tcp://{eNBIP}:{rxPort}'@\" {multiUEPath}")

    def setSingleUEEnBAddr(self, txIP: str, txPort: int, rxIP: str, rxPort: int) -> None:
        self.run(f"sed -i \"/zeromq_req_source_enb/s@\'tcp://.*\'@\'tcp://{txIP}:{txPort}\'@\" {self.defaultSingleUEPath}")
        self.run(f"sed -i \"/zeromq_rep_sink_enb/s@'tcp://.*'@'tcp://{rxIP}:{rxPort}'@\" {self.defaultSingleUEPath}")

    def setSingleUEUEAddr(self, UEIP: str, txPort: int, eNBIP: str, rxPort: int) -> None:
        self.run(f"sed -i \"/zeromq_req_source_ue/s@'tcp://.*'@'tcp://{UEIP}:{txPort}'@\" {self.defaultSingleUEPath}")
        self.run(f"sed -i \"/zeromq_rep_sink_ue/s@'tcp://.*'@'tcp://{eNBIP}:{rxPort}'@\" {self.defaultSingleUEPath}")

    def setDeviceArgs(self, deviceArgs: str) -> None:
        self.config[RF_SECTION][DEVICE_ARGS_ATTR] = deviceArgs
        self.saveConfig(self.config, self.defaultEnBConfigPath)

    def setDeviceName(self, deviceName: str) -> None:
        self.config[RF_SECTION][DEVICE_NAME_ATTR] = deviceName
        self.saveConfig(self.config, self.defaultEnBConfigPath)

    def setEPCAddress(self, ip: str) -> None:
        self.config[ENB_SECTION][MME_ADDR] = ip
        self.saveConfig(self.config, self.defaultEnBConfigPath)

    def setEnBAddress(self, ip: str) -> None:
        self.config[ENB_SECTION][GTP_BIND_ADDR] = ip
        self.config[ENB_SECTION][S1C_BIND_ADDR] = ip
        self.saveConfig(self.config, self.defaultEnBConfigPath)
