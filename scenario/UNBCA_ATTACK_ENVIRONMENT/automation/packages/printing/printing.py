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
from glob import glob
import os
import platform
import sys
import random
import time
import cups

def main():
	echoC(__name__, "Start Printing...")

	# Return value for error detection
	error = 0

	if platform.system() == "Linux":
		
		try:
			# Determine Default printer	
			conn = cups.Connection()
			printers = conn.getPrinters()
			aux = list(printers.keys())
			if len(aux) > 0:
				printer = aux[0]
				echoC(__name__, "Found " + printer + " as default printer.")
			else:
				raise Exception(" 0 printers found")
			time.sleep(5)
		
			# Create print command and call (multiple)
			firstTime = True
			while random.randint(0, 1) != 0 or firstTime == True: # Is not yet quite clean: If the first attempt is directly 0 "rolled" no document is printed
				firstTime = False
				
				# Number of copies to be printed				
				numberOfCopies = random.randint(1, 10)
				
				# Find a random file from the browsing directory (there are a lot of files)
				randFile = random.choice(os.listdir("packages/system/"))
				randFile = "packages/system/" + randFile
		
				# Print file
				cmd = "lpr -P " + printer + " -#" + str(numberOfCopies) + " " + randFile
				try:
					os.system(cmd)
					echoC(__name__, "Print job sent: " + randFile)
					error = 0
					time.sleep(10)
				except Exception as e:
					echoC(__name__, "Print job error: " + str(e))
					error = -1
					
		except Exception as e:
			echoC(__name__, "Printing error: " + str(e))
			error = -1


	elif platform.system() == "Windows":
		
		try:
			# Check if a default printer is configured
			import win32api
			import win32print
			printer = win32print.GetDefaultPrinter()
			if not "XPS" in printer and not "PDF" in printer:
				echoC(__name__, "Found " + printer + " as default printer.")
			
				# Create print order 
				firstTime = True
				while random.randint(0, 1) != 0 or firstTime == True: # Is not yet quite clean: If the first attempt is directly 0 "rolled" no document is printed
					firstTime = False
					
					# Select a file to print from a directory
					randFile = random.choice(glob("M:\\*.log"))
					
					# print
					try:
						os.startfile(randFile, "print")
						echoC(__name__, "Print job sent: " + randFile)
						error = 0
						time.sleep(10)
					except Exception as e:
						echoC(__name__, "Print job error: " + str(e))
						error = -1
			else:
				echoC(__name__, "Error. Maybe wrong default printer.")
				error = -1

		except Exception as e:
			echoC(__name__, "Printing error: " + str(e))
			error = -1
	else:
		echoC(__name__, "Could not determine OS.")
		error = -1

	echoC(__name__, "Done")
	return error

if __name__ == "__main__":
	main()
