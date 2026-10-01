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


from datetime import datetime
from configparser import ConfigParser
import time
import sys

# Output of date and time, runtime, calling module, and text passed
# Since the module is passed with path and file transfer, these must be truncated (split)
def echoC(modul, text):

	# An forward and backward Slash splits 
	modulName = modul.split("/")[-1].split("\\")[-1]
	
	# Remove file ending 	
	modulName = modulName.split(".")[-1]

	# Log text: date and time, runtime, module name (field always 11 characters), text passed (without whitespaces)
	outputText = datetime.now().strftime("%y%m%d-%H%M%S") + " | " + str(getRuntime()) + " | " + "{0:15s}".format(modulName) + " | " + str(text).rstrip()
	print(outputText)
	
	# Save in Logfile 
	with open("packages/system/tracelog.txt", "a") as myFile:
		myFile.write(outputText + "\n")

# Determination of the running time using the stored start time
def getRuntime():
	
	# Read start time from configuration 
	parser = ConfigParser()
	parser.read("packages/system/config.ini")
	startTime = datetime.strptime(parser.get("starttime", "starttime"), "%y%m%d-%H%M%S%f")
	
	# Set runtime and return it
	runtime = datetime.now() - startTime
	return runtime
