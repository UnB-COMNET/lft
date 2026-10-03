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
import sys
import random
import linecache
import platform

if platform.system() == "Linux":
	import nmap
#else:
#	return -1

iprange = 'packages/attacking/iprange.txt'
ipList = 'packages/attacking/ipList.txt'

def getIPRange():
	try:
		with open(iprange) as f:
			content = [x.strip('\n') for x in f.readlines()]
	except Exception as e:
		echoC(__name__, "Error reading IP ranges: " + str(e))
		content = -1
	return content

def main():

	echoC(__name__, "Starting a scan")
	
	# Determine subnets 
	ipRangeList = getIPRange()
	if ipRangeList == -1:
		return -1
	
	# Select a random subnet 
	rand = random.randint(0, len(ipRangeList)-1) 
	ipRange = ipRangeList[rand]
	
	# Define arguments 
	scanOptions = ["-sF", "-sA", "-sU", "-sS", "-n -sP -PE"]
	myArguments = random.choice(scanOptions) + " -T " + str(random.randint(1, 3))
	
	echoC(__name__, "Scanning " + str(ipRange) + " with arguments: " + myArguments)
	
	# Execute Scan 
	nm = nmap.PortScanner()
	nm.scan(hosts=ipRangeList[rand], arguments=myArguments)
	
	# Store the found IPs 
	# At first, delete old IPs 
	open(ipList, 'w').close()
	for i in nm.all_hosts():
		with open(ipList, 'a') as myfile:
			myfile.write(str(i) + '\n')
			
	echoC(__name__, "Done")
	
	returnval = "0,nmap args: " + myArguments
	return returnval

if __name__ == "__main__":
	main()
