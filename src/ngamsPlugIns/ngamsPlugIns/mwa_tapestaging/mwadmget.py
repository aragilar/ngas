#!/usr/bin/env python

#
#    ICRAR - International Centre for Radio Astronomy Research
#    (c) UWA - The University of Western Australia, 2012
#    Copyright by UWA (in the framework of the ICRAR)
#    All rights reserved
#
#    This library is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation; either
#    version 2.1 of the License, or (at your option) any later version.
#
#    This library is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with this library; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston,
#    MA 02111-1307  USA
#

#******************************************************************************
# Who       When        What
# --------  ----------  -------------------------------------------------------
# dpallot  8/08/2014  Created


import socket, json
import sys
import struct
from optparse import OptionParser

class ErrorCode():
   socket_timeout_error = 1
   io_error = 2
   protocol_error = 3
   not_an_mwa_file_error = 4
   files_not_found_error = 5
   database_error = 6
   command_error = 7
   unknown_error = 8
   connection_error = 9
   invalid_args_error = 10
   file_limit_exceeded = 11

class ErrorCodeException(Exception):
   def __init__(self, err, msg):
      self.error_code = err
      self.msg = msg

   def getMsg(self):
      return self.msg

   def __str__(self):
      return repr(self.error_code)


def main():
   PORT = 9898
   sock = None
   try:

      files = []

      parser = OptionParser(usage="usage: %prog -f [mwa files] -s [mwadmgetserver]", version="%prog 1.0")
      parser.add_option('-f', default='', dest='filename', action='store', help="MWA file(s)")
      parser.add_option('-s', default='localhost', action='store', dest='server', help="mwadmgetserver")

      (options, args) = parser.parse_args()

      files = options.filename.split(',')

      sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

      files = {'files' : files}
      jsonoutput = json.dumps(files)

      val = struct.pack('>I', len(jsonoutput))
      val = val + jsonoutput

      # Connect to server and send data
      sock.connect((options.server, PORT))
      sock.sendall(val)

      # Receive return code from server
      return struct.unpack('!H', sock.recv(2))[0]

   finally:
      if sock:
         sock.close()


if __name__ == "__main__":
   try:
      retcode = main()
      if (retcode != 0):
         raise ErrorCodeException(retcode, '')

      sys.exit(retcode)

   except IOError as ioe:
      print ioe
      sys.exit(ErrorCode.io_error)

   except Exception as e:
      print e

      sys.exit(ErrorCode.unknown_error)