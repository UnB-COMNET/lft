from profissa_lft.ue import UE
from profissa_lft.epc import EPC
from profissa_lft.enb import EnB
import time
import subprocess
from time import sleep
from experiment.constants import *

class EmuEmuWireless:
    def __init__(self):
        self.epc = EPC('epc')
        self.enb = EnB("enb")
        self.ue = UE('ue')

    def setup(self):
        self.epc.instantiate(dockerImage=SRSRAN_PERFSONAR_UHD_IMAGE, runCommand=USR_SBIN_INIT_COMMAND)
        self.enb.instantiate(dockerImage=SRSRAN_PERFSONAR_UHD_IMAGE)
        self.ue.instantiate(dockerImage=SRSRAN_PERFSONAR_UHD_IMAGE, runCommand=USR_SBIN_INIT_COMMAND)

        self.enb.connect(self.epc, "enbepc", "epcenb")
        self.ue.connect(self.enb, "ueenb", "enbue")

        self.epc.connectToInternet('9.0.0.2', 24, "epchost", "hostepc")
        self.ue.connectToInternet('12.0.0.2', 24, "uehost", "hostue")

        self.epc.setIp('9.0.0.1', 24, "epchost")
        self.epc.setIp('10.0.0.1', 24, "epcenb")
        self.enb.setIp('10.0.0.2', 24, "enbepc")
        self.enb.setIp('11.0.0.1', 30, "enbue")
        self.ue.setIp('12.0.0.1', 24, "uehost")
        self.ue.setIp('11.0.0.2', 29, "ueenb")

        self.epc.setDefaultGateway('9.0.0.2', "epchost")
        self.enb.setDefaultGateway('9.0.0.2', "enbepc")
        self.ue.setDefaultGateway('12.0.0.2', "ueenb")

        self.enb.acceptPacketsFromInterface("enbue")

        # Define EPC config
        self.epc.setEPCAddress("10.0.0.1")
        self.epc.addNewUE(self.ue.getNodeName(), "001010123456780", EMU_EMU_WIRELESS_UE_IP_ADDR)

        # Define ENB Config
        self.enb.setEPCAddress("10.0.0.1")
        self.enb.setEnBAddress("10.0.0.2")
        self.enb.setSingleUEEnBAddr("11.0.0.1", 2101, '11.0.0.1', 2100)
        self.enb.setSingleUEUEAddr("11.0.0.2", 2001, "11.0.0.1", 2000)

        # Define UE Config
        self.ue.setUEID("001010123456780")
        self.ue.setCorrectSyncError(True)

        self.epc.start()
        self.enb.starGnuRadioSingleUE()
        self.enb.start("11.0.0.1", 2101, "11.0.0.1", 2100)
        time.sleep(5)

        self.ue.start("--rf.device_name=zmq --rf.device_args=\"tx_port=tcp://11.0.0.2:2001,rx_port=tcp://11.0.0.1:2000,id=ue,base_srate=11.52e6\"")

        self.ue.setHost(EMU_EMU_WIRELESS_UE_IP_ADDR)
        self.epc.setHost(EMU_EMU_WIRELESS_EPC_IP_ADDR)

        self.epc.enableForwarding("epchost", "srs_spgw_sgi")
        self.ue.enableForwarding("uehost", "tun_srsue")

        subprocess.run(f"ip route add {EMU_EMU_WIRELESS_UE_IP_ADDR}/32 via 12.0.0.1 dev hostue", shell=True)
        subprocess.run(f"ip route add {EMU_EMU_WIRELESS_EPC_IP_ADDR}/32 via 9.0.0.1 dev hostepc", shell=True)

        self.__startPerfsonarServices()

    def __startPerfsonarServices(self):
         self.epc.run("service pscheduler-runner start && service pscheduler-ticker start && service pscheduler-scheduler start && service pscheduler-archiver start")
         sleep(5)
         self.ue.run("service pscheduler-runner start && service pscheduler-ticker start && service pscheduler-scheduler start && service pscheduler-archiver start")

    def tearDown(self):
        self.epc.delete()
        self.enb.delete()
        self.ue.delete()

EmuEmuWireless().setup