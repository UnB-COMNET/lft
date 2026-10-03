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


from packages.system import mainscript
from packages.system.echoX import echoC
from packages.system import setupWorkingSchedule
from subprocess import Popen, check_output
from configparser import ConfigParser
from datetime import datetime
from shutil import copyfile
from uuid import getnode
from urllib.request import URLopener
import subprocess
import random
import socket
import platform
import sys
import socket
from shutil import copyfile

# ID of the instance consisting of the host name and the int value of the MAC address
myID = "emtpy"

# Fetch the start time of the script
def setStartTime(parser):
	parser.set("starttime", "starttime", datetime.now().strftime("%y%m%d-%H%M%S%f"))
	# "flush" 
	with open("packages/system/config.ini", "w") as config:
		parser.write(config)

# Determine working days and working times randomly
def setWorkingSchedule(parser):
	# If the corresponding flag set finds the determination instead
	if parser.get("workingschedule", "random_generated_schedule") == "1":
		# Deactivate the flag for the random determination of working time and days 
		# This means that only the very first start of the script the settings are carried out 
		parser.set("workingschedule", "random_generated_schedule", "0")
		# "flush" 
		with open("packages/system/config.ini", "w") as config:
			parser.write(config)
		# Determination of working time and days has been outsourced to a separate module
		setupWorkingSchedule.main(parser)

# Private and break levels
def setRandomPrivateAndBreak(parser):
	# If the corresponding flag set finds the determination instead
	if parser.get("actions", "random_generated_private_and_break") == "1":
		# Disable the flag for random determination
		# This means that only the very first start of the script the settings are carried out 
		parser.set("actions", "random_generated_private_and_break", "0")
		parser.set("actions", "private", str(random.randint(5, 10)))
		parser.set("actions", "breaks", str(random.randint(5, 10)))
		# "flush"
		with open("packages/system/config.ini", "w") as config:
			parser.write(config)

def getAndSetSubnetHostAndHostname(parser):
	# Determine IP 
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.connect(("www.google.com", 80))
		ip = (s.getsockname()[0])
		s.close()
		echoC(__name__, "My IP is " + ip)
	except Exception as e:
		echoC(__name__, "getandSetSubnetHostAndHostname job error: " + str(e))
		echoC(__name__, "Trying again to connect to google.com")
		return -1, -1, -1
	# Determine subnet using the IP Address 
	subnet = ip.split('.')[2]
	# Determine the host part of the IP 
	host = ip.split('.')[3]
	hostname = socket.gethostname()
	parser.set("network", "hostname", hostname)
	parser.set("network", "subnet", subnet)
	parser.set("network", "host", host)
	# "flush" 
	with open("packages/system/config.ini", "w") as config:
		parser.write(config)
	return subnet, host, hostname

# Configure different server services 
def configServers(parser, subnet, host):
	# Determine the server ips using the subnet information 
	try:
		printIP = parser.get(subnet, "print")
	except Exception as e:
		printIP = "0.0.0.0"
		echoC(__name__, "configServers() NoSectionError. Setting default IPs for printer")
	try:
		mailIP = parser.get(subnet, "mail")
	except Exception as e:
		echoC(__name__, "configServers() NoSectionError. Setting default IPs for printer")
		mailIP = "0.0.0.0"
	try:
		fileIP = parser.get(subnet, "file")
	except Exception as e:
		echoC(__name__, "configServers() NoSectionError. Setting default IPs for printer")
		fileIP = "0.0.0.0"
	try:
		webIP = parser.get(subnet, "web")
	except Exception as e:
		echoC(__name__, "configServers() NoSectionError. Setting default IPs for printer")
		webIP = "0.0.0.0"
	try:
		seaIP = parser.get(subnet, "seafile")
	except Exception as e:
		echoC(__name__, "configServers() NoSectionError. Setting default IPs for printer")
		seaIP = "0.0.0.0"
	try:
		seaFolder = parser.get(subnet, "seaFolder")
	except Exception as e:
		echoC(__name__, "configServers() NoSectionError. Setting default IPs for printer")
		seaFolder = "0.0.0.0"
	# Adapt mail.ini for Mail-Server 
	with open("packages/mailing/mail.ini", "w") as file:
		file.write("# Login-Informationen fuer mailing.py anlegen\n")
		file.write("[mailconfig]\n")
		# Determine user name and fill ip parts with zeros 
		user = "user." + subnet.zfill(3) + "." + host.zfill(3)
		file.write("user = " + user + "@mailserver.example\n")
		file.write("pw = hollahe23\n")
		# Mail-Server IP from ServerConfig-file
		file.write("smtp = " + mailIP + "\n")
	# Mount Netstorage 
	if platform.system() == "Linux":
		try:
			cmd = 'umount /home/debian/netstorage'
			subprocess.check_call(cmd, shell=True)
		except:
			pass
		try:
			cmd = "mount -t cifs -o username=mininet,password=mininet //" + fileIP + "/netstorage /home/debian/netstorage"
			subprocess.check_call(cmd, shell=True)
		except Exception as e:
			echoC(__name__, "Mount netstorage error: " + str(e))
	elif platform.system() == "Windows":
		try:			
			cmd = "net use N: /delete"
			subprocess.check_call(cmd, shell=True)
		except Exception as e:
			echoC(__name__, "Unmount error: " + str(e))
		try:
			cmd = "net use N: \\\\" + fileIP + "\\netstorage"
			subprocess.check_call(cmd, shell=True)
		except Exception as e:
			echoC(__name__, "Mount netstorage error: " + str(e))
	# Configure printer 
	# On Linux, the printer is determined by default before each printing
	# For Windows, a batch script must be prepared and executed
	if platform.system() == "Windows":
		with open("C:\skripte\\requirements\printer.bat", "w") as file:
			file.write("rundll32 printui.dll,PrintUIEntry /if /q /b \"nw-druck\" /f C:\Windows\inf\\ntprint.inf /r \"http://" + printIP + ":631/printers/pdf\" /m \"HP Color LaserJet 2800 Series PS\"\n")
			file.write("timeout 30\n")
			file.write("rundll32 printui.dll,PrintUIEntry /y /q /n \"nw-druck\"\n")
			file.write("timeout 30\n")
		instPrinter = Popen(["C:\skripte\\requirements\printer.bat"])
		instPrinter.wait()
	# Configure IP of the web server (intranet)
	parserBrowsing = ConfigParser()
	parserBrowsing.read("packages/browsing/browser.ini")
	parserBrowsing.set("internWeb", "url", "http://" + webIP)
	# "flush" 
	with open("packages/browsing/browser.ini", "w") as config:
		parserBrowsing.write(config)
	# Configure Seafile (works only for linux, windows must be configured manually)
	if platform.system() == "Linux":
		cmd = "seaf-cli sync -l '" + seaFolder + "' -s  'http://" + seaIP + ":80' -d '/home/debian/sea' -u 'alexandreamk1@gmail.com' -p 'Password123' -c '/home/debian/.ccnet'"
		cntErrors = 0
		output=0
		while cntErrors < 3:
			try:
				subprocess.check_call(cmd, shell=True)
				echoC(__name__, "Set up Seafile")
				continue
			except Exception as e:
				cntErrors += 1
				echoC(__name__, "Setting up Seafile error (" + str(cntErrors) + "): " + str(e))

# Init scripts 
def main():

	# Init Parser 
	parser = ConfigParser()

	# Read configuration file 
	parser.read("packages/system/config.ini")
	
	# Save the start automation time 
	# This should always be the first task of the script, otherwise no protocol can be used
	setStartTime(parser)
	
	# Set working times (only if the script is the first time)
	setWorkingSchedule(parser)
	
	# Create private and break levels (only if the script is the first time)
	setRandomPrivateAndBreak(parser)
	
	# Load actions 
	browsing = parser.getint("actions", "browsing")
	mailing = parser.getint("actions", "mailing")
	printing = parser.getint("actions", "printing")
	copyfiles = parser.getint("actions", "copyfiles")
	copysea = parser.getint("actions", "copysea")
	ssh = parser.getint("actions", "ssh")
	meeting = parser.getint("actions", "meeting")
	offline = parser.getint("actions", "offline")
	private = parser.getint("actions", "private")
	breaks = parser.getint("actions", "breaks")
	attacking = parser.getint("actions", "attacking")
	
	t = parser.getint("time", "counter")
	
	# Determine Subnet- and Host Part of the IP 
	subnet = host = hostname =-1
	while (subnet == -1 and host == -1 and hostname == -1):
		subnet, host, hostname = getAndSetSubnetHostAndHostname(parser)
	
	# Determine ID of the instance (MAC-Address as Integer)
	global myID
	myID = "192.168." + subnet +'.'+ host

	# Configure the servers using the IPs in the ServerConfig file
	parser.read("packages/system/serverconfig.ini")
	configServers(parser, subnet, host)
	
	#echoC(__name__, "Call mainscript with %d, %d, %d, %d, %d, %d" %(actLvl, busLvl, act1, act2, act3, act4, t))
	mainscript.init(browsing, mailing, printing, copyfiles, copysea, ssh, meeting, offline, private, breaks, attacking, t)

if __name__ == "__main__":
	main()
