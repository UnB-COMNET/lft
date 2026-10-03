#
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
#


from subprocess import Popen
from configparser import ConfigParser
from datetime import datetime
import subprocess
import socket
import platform
import urllib3
import sys
	
# Configure backup server 
def configBackupServer(parser):
	
	# Read ips from backup servers 	
	backupIP = parser.get("backup", "ip")
			
	# Mount netstorage 
	try:
		cmd = "mount -t cifs -o username=mininet,password=mininet //" + backupIP + "/backup /home/debian/backup"
		subprocess.check_call(cmd, shell=True)
	except Exception as e:
		with open("/home/debian/log.txt", "a") as file:
			file.write(datetime.now().strftime("%y%m%d-%H%M%S") + " | Fehler beim Mount des Backup-Servers | " + str(e) + "\n")

# Init 
def main():
	# Init parser 
	parser = ConfigParser()
	
	# Open ServerConfig file with parser 
	parser.read("/home/debian/serverconfig.ini")
	
	# Configure Backup strategy 
	configBackupServer(parser)

if __name__ == "__main__":
	main()
