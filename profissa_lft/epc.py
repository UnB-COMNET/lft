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
from configparser import ConfigParser
from .constants import *
import pandas as pd

class EPC(Perfsonar):
    def __init__(self, name: str):
        super().__init__(name)
        self.defaultEPCConfigPath = '/etc/srsran/epc.conf'
        self.configEPC = None
        self.defaultEPCUserDbPath = '/etc/srsran/user_db.csv'
        self.userDb = None 
        self.buildDir = "/srsRAN/build"

    def instantiate(self, dockerImage='alexandremitsurukaihara/lft:srsran-perfsonar-uhd4', runCommand='') -> None:
        super().instantiate(dockerImage=dockerImage, runCommand=runCommand)
        self.configEPC = self.readConfigFile(self.defaultEPCConfigPath)
        self.userDb = self.createUserDb()

    def start(self) -> None:
        self.run(f"{self.buildDir}/srsepc/src/srsepc > {self.buildDir}/epc.out &")

    def stop(self) -> None:
        self.run("pkill -f -9 srsepc")

    def setDefaultEPCConfigPath(self, path: str) -> None:
        self.defaultEPCConfigPath = path

    def getDefaultEPCConfigPath(self) -> str:
        return self.defaultEPCConfigPath

    def setEPCAddress(self, ip='127.0.1.100') -> None:
        self.configEPC[MME_SECTION][MME_BIND_ADDR] = ip
        self.configEPC[SPGW_SECTION][GTPU_BIND_ADDR] = ip
        self.saveConfig(self.configEPC, self.defaultEPCConfigPath)
        
    def setSgiInterfaceAddress(self, ip='172.16.0.1') -> None:
        self.configEPC[SPGW_SECTION][SGI_IF_ADDR] = ip
        self.saveConfig(self.configEPC, self.defaultEPCConfigPath)
        
    # Each UE ID must be unique and must be set in "imsi" parameter located inside the ue.conf
    def addNewUE(self, name: str, ID: str, IP="dynamic") -> None:
        newRow = {
            "Name": name,
            "Auth": "mil",
            "IMSI": ID,
            "Key": "00112233445566778899aabbccddeeff",
            "OP_Type": "opc",
            "OP/OPc": "63bfa50ee6523365ff14c1f45f88737d",
            "AMF": "9001",
            "SQN": "000000001234",
            "QCI": "7",
            "IP_alloc": IP
        }
        self.userDb.loc[len(self.userDb)] = newRow
        self.saveUserDb()
        #self.run(f"echo \'{name},mil,{ID},00112233445566778899aabbccddeeff,opc,63bfa50ee6523365ff14c1f45f88737d,9001,000000001234,7,{IP}\' >> {self.defaultEPCUserDbPath}")

    def createUserDb(self) -> None:
        return pd.DataFrame(columns=["Name","Auth","IMSI","Key","OP_Type","OP/OPc","AMF","SQN","QCI","IP_alloc"]) 
    
    def saveUserDb(self) -> None:
        randomTmpName = self.getHashFromString(self.defaultEPCUserDbPath)
        self.userDb.to_csv(f"/tmp/lft/{randomTmpName}", header=None, index=False)
        self.copyLocalToContainer(f"/tmp/lft/{randomTmpName}", self.defaultEPCUserDbPath)
