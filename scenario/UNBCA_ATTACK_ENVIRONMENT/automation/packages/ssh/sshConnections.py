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


from configparser import ConfigParser
from packages.system.echoX import echoC
import getpass
import subprocess
import random
import linecache
import getpass
import sys
import time
import os
import platform

# Quick and Dirty so Windows does not complain about the package
# SSH is never run on Windows anyway
if platform.system() == "Linux":
	from pexpect import pxssh

user = 'mininet'
secret = 'mininet'
ssh_cmdList = 'packages/ssh/sshOrders.txt'
ipList = ['mail', 'file', 'web', 'backup']

# Find the number of lines of the transferred file
def file_len(myfile):
	with open(myfile) as f:
		for i, l in enumerate(f):
			pass
	return i + 1


def main():
	
	# Set to -1 if errors occur
	# Used as return parameter
	error = 0
	
	# Config file which contains all the IPs of the server
	parser = ConfigParser()
	parser.read('packages/system/sshiplist.ini')
	
	# Randomly select a subnet
	# Except the first, this is the backup server
	rand_subnet = 'ssh'
	
	# Randomly select an IP
	ip = parser.get(rand_subnet, random.choice(ipList))
	echoC(__name__, "Opening SSH connection to " + str(ip))
	
	try:
	
		# Start SSH connection 
		s = pxssh.pxssh()
		s.login(ip, user, secret)
		
		# Execute several orders 
		firstTime = True
		while random.randint(0, 4) != 0 or firstTime == True:
			firstTime = False
		
			# Determine the number of possible commands and randomly select one
			try:
				nb = file_len(ssh_cmdList)
				rand = random.randint(1, nb)
				cmd = linecache.getline(ssh_cmdList, rand)
				error = 0
			except Exception as e:
				# If the file can not be read, simply specify a command
				echoC(__name__, "SSH: Error retrieving a command from the given file")
				cmd = "ls -lah"
				error = -1
			
			# Send command
			s.sendline(cmd)
			s.prompt()
			echoC(__name__, "SSH output on " + str(ip) +  ": " + s.before.decode("utf8"))
			
			# Wait a bit before it goes on
			time.sleep(random.randint(3, 60))
		
		# Disconnect
		s.logout()
	except pxssh.ExceptionPxssh as e:
		echoC(__name__, "No Host found: " + str(e))
		error = -1
		
	return error

if __name__ == "__main__":
	# only possible for linux 
	if platform.system() == "Linux":
		main()
