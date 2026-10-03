import paramiko

from profissa_lft.controller import Controller


class ONOS(Controller):
    def __init__(self, nodeName: str) -> None:
        super().__init__(nodeName)
        self.__cli_ip = ""

    def setCliIp(self, ipa: str):
        self.__cli_ip = ipa
    
    def getCliIp(self):
        return self.__cli_ip

    def instantiate(self, dockerImage="onosproject/onos", mapPorts = False) -> None:
        # -v ./onos_config:/root/onos/config
        if mapPorts: dockerCommand = f"docker run -dit -p 8181:8181 -p 8101:8101 -p 5005:5005 -p 830:830 --privileged --name={self.getNodeName()} {dockerImage}"
        else: dockerCommand = f"docker run -dit --privileged --name={self.getNodeName()} {dockerImage}"
        return super().instantiate(dockerImage, dockerCommand)
    
    # Brief: Activate required ONOS apps automatically
    # Default credentials for ONOS CLI via ssh in default values of username and password parameters
    # Command: String with one ore more commands, with bash syntax. Example: app activate org.onosproject.openflow ; app activate org.onosproject.fwd
    def runOnosCliCommands(self, command, username='karaf', password='karaf') -> None:
        print("[Experiment] Activating OpenFlow Provider Suite and Reactive Forwarding")

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.getCliIp(), port=8101, username=username, password=password)

            stdin, stdout, stderr = ssh.exec_command(command)

            command_output = stdout.read().decode('utf-8')
            error_output = stderr.read().decode('utf-8')

            if command_output != '':
                print("Command Output:")
                print(command_output)
                
            if error_output != '':
                print("Error Output:")
                print(error_output)

        except Exception as e:
            print(f"An error occurred: {str(e)}")
        finally:
            ssh.close()

    # Brief: Activate required ONOS apps automatically
    # Default credentials for ONOS CLI via ssh in default values of username and password parameters
    def activateONOSApps(self, 
                         server_ip, 
                         command='app activate org.onosproject.openflow && app activate org.onosproject.fwd',
                         username='karaf', 
                         password='karaf') -> None:
        print("[Experiment] Activating OpenFlow Provider Suite and Reactive Forwarding")

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(server_ip, port=8101, username=username, password=password)

            stdin, stdout, stderr = ssh.exec_command(command)
            command_output = stdout.read().decode('utf-8')
            error_output = stderr.read().decode('utf-8')

            print("Command Output:")
            print(command_output)

            print("Error Output:")
            print(error_output)

        except Exception as e:
            print(f"An error occurred: {str(e)}")
        finally:
            ssh.close()

    def deactivateONOSApps(self, server_ip, username='karaf', password='karaf') -> None:
        print("[Experiment] Deactivating ONOS apps!")

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(server_ip, port=8101, username=username, password=password)

            command = 'app deactivate org.onosproject.fwd'
            stdin, stdout, stderr = ssh.exec_command(command)

            command_output = stdout.read().decode('utf-8')
            error_output = stderr.read().decode('utf-8')

            print("Command Output:")
            print(command_output)

            print("Error Output:")
            print(error_output)

        except Exception as e:
            print(f"An error occurred: {str(e)}")
        finally:
            ssh.close()


    
