#
#    ICRAR - International Centre for Radio Astronomy Research
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
"""
NGAS Command Plug-In, implementing a Archive PULL Command using BBCP

This works by calling archiveFromFile, which in turn takes care of all the handling

Usgae example with wget:

wget -O BARCHIVE.xml "http://ngas.ddns.net:7777/BBCPARC?fileUri=/home/ngas/NGAS/log/LogFile.nglog"

Usage example with curl to send file from Pawsey to MIT:

curl --connect-timeout 7200 eor-12.mit.edu:7777/BBCPARC?fileUri=ngas%40146.118.84.67%3A/mnt/mwa01fs/MWA/testfs/KNOPPIX_V7.2.0DVD-2013-06-16-EN.iso\&bport=7790\&bwinsize=%3D32m\&bnum_streams=12\&mimeType=application/octet-stream
"""

from collections import namedtuple
import commands
import os
import time
import subprocess
import struct

from ngamsLib import ngamsHighLevelLib, ngamsPlugInApi
from ngamsLib.ngamsCore import info, checkCreatePath, genLog, alert, TRACE, \
    NGAMS_SUCCESS, NGAMS_HTTP_GET, NGAMS_ARCHIVE_CMD, NGAMS_HTTP_FILE_URL, \
    NGAMS_NOTIF_NO_DISKS, setLogCache, mvFile, notice, NGAMS_FAILURE, error, \
    NGAMS_PICKLE_FILE_EXT, rmFile, NGAMS_ONLINE_STATE, NGAMS_IDLE_SUBSTATE, \
    NGAMS_BUSY_SUBSTATE, getDiskSpaceAvail, NGAMS_HTTP_SUCCESS, NGAMS_STAGING_DIR, \
    loadPlugInEntryPoint, genUniqueId
from ngamsServer import ngamsArchiveUtils, ngamsCacheControlThread
from pccUt import PccUtTime


bbcp_param = namedtuple('bbcp_param', 'port, winsize, num_streams, checksum')

def bbcpFile(srcFilename, targFilename, bparam):
    """
    Use bbcp tp copy file <srcFilename> to <targFilename>

    NOTE: This requires remote access to the host as well as
         a bbcp installation on both the remote and local host.
    """
    info(3, "Copying file: %s to filename: %s" % (srcFilename, targFilename))

    # Make target file writable if existing.
    if (os.path.exists(targFilename)):
        os.chmod(targFilename, 420)

    checkCreatePath(os.path.dirname(targFilename))

    if bparam.port:
        pt = ['-Z', str(bparam.port)]
    else:
        pt = ['-z']

    fw = []
    if bparam.winsize:
        fw = ['-w', str(bparam.winsize)]

    ns = []
    if (bparam.num_streams):
        ns = ['-s', str(bparam.num_streams)]

    # perform checksum on host and compare to target. If it's different bbcp will fail.
    cmd_checksum = ['-e', '-E', 'c32z=/dev/stdout']
    cmd_list = ['bbcp', '-f', '-V'] + cmd_checksum + fw + ns + ['-P', '2'] + pt + [srcFilename, targFilename]

    info(3, "Executing external command: %s" % subprocess.list2cmdline(cmd_list))

    p1 = subprocess.Popen(cmd_list, stdout = subprocess.PIPE, stderr = subprocess.PIPE)
    checksum_out, out = p1.communicate()

    if p1.returncode != 0:
        raise Exception, "bbcp returncode: %d error: %s" % (p1.returncode, out)

    # extract c32 zip variant checksum from output and convert to signed 32 bit integer
    bbcp_checksum = struct.unpack('!i', checksum_out.split(' ')[2].decode('hex'))

    info(3, 'BBCP final message: %s' % out.split('\n')[-2]) # e.g. "1 file copied at effectively 18.9 MB/s"
    info(3, "File: %s copied to filename: %s" % (srcFilename, targFilename))

    return str(bbcp_checksum[0]), 'ngamsGenCrc32'


def archiveFromFile(srvObj,
                    bparam,
                    reqPropsObj):
    """
    Archive a file directly from a file as source.

    srvObj:          Reference to NG/AMS Server Object (ngamsServer).

    filename:        Name of file to archive (string).

    bparam:          BBCP parameter (named tuple)

    reqPropsObj:     Request Property object to keep track of actions done
                     during the request handling (ngamsReqProps).

    Returns:         Execution result object of DAPI
    """
    T = TRACE()

    reqPropsObjLoc = reqPropsObj
    filename = reqPropsObj.getFileUri()

    info(2, "Archiving file: %s" % filename)

    # If no target disk is defined, find one suitable disk.
    if reqPropsObjLoc.getTargDiskInfo() is None:
        trgDiskInfo = ngamsArchiveUtils.ngamsDiskUtils.\
                        findTargetDisk(srvObj.getHostId(),
                                         srvObj.getDb(),
                                         srvObj.getCfg(),
                                         reqPropsObjLoc.getMimeType(),
                                         0)

        reqPropsObjLoc.setTargDiskInfo(trgDiskInfo)

    stagingFile = os.path.join('/',
                               reqPropsObjLoc.getTargDiskInfo().getMountPoint(),
                               NGAMS_STAGING_DIR,
                               '{0}{1}{2}'.format(genUniqueId(), '___', os.path.basename(filename)))

    reqPropsObjLoc.setStagingFilename(stagingFile)

    st = time.time()

    # perform the bbcp transfer, we will always return the checksum
    bbcp_checksum = bbcpFile(filename, stagingFile, bparam)

    reqPropsObjLoc.setSize(os.path.getsize(stagingFile))
    reqPropsObjLoc.setBytesReceived(reqPropsObjLoc.getSize())

    iorate = reqPropsObjLoc.getSize()/(time.time() - st)

    plugIn = srvObj.getMimeTypeDic()[reqPropsObjLoc.getMimeType()]
    info(2, "Invoking DAPI: %s to handle file: %s" % (plugIn, stagingFile))
    plugInMethod = loadPlugInEntryPoint(plugIn)
    resMain = plugInMethod(srvObj, reqPropsObjLoc)

    mvFile(reqPropsObjLoc.getStagingFilename(), resMain.getCompleteFilename())

    diskInfo = ngamsArchiveUtils.postFileRecepHandling(srvObj, reqPropsObjLoc, resMain, bbcp_checksum)

    return (resMain, trgDiskInfo, iorate)


def handleCmd(srvObj,
              reqPropsObj,
              httpRef):
    """
    Handle the Quick Archive (QARCHIVE) Command.

    srvObj:         Reference to NG/AMS server class object (ngamsServer).

    reqPropsObj:    Request Property object to keep track of actions done
                    during the request handling (ngamsReqProps).

    httpRef:        Reference to the HTTP request handler
                    object (ngamsHttpRequestHandler).

    Returns:        (fileId, filePath) tuple.
    """
    T = TRACE()

    # Check if the URI is correctly set.
    info(3, "Check if the URI is correctly set.")
    info(3,"ReqPropsObj status: {0}".format(reqPropsObj.getObjStatus()))

    parsDic = reqPropsObj.getHttpParsDic()

    if not parsDic.has_key('fileUri') or not parsDic['fileUri']:
        errMsg = genLog("NGAMS_ER_MISSING_URI")
        error(errMsg)
        raise Exception, errMsg

    # should not be allowed to pull files from these base locations
    invalid_paths = ('/dev', '/var', '/usr', '/opt', '/etc')
    file_uri = parsDic['fileUri']

    if file_uri.lower().startswith(invalid_paths):
        errMsg = genLog("NGAMS_ER_ILL_URI", [file_uri,
                                            "Archive Pull Request"])
        error(errMsg)
        raise Exception, errMsg

    reqPropsObj.setFileUri(file_uri)

    if not parsDic.has_key('mimeType') or not parsDic['mimeType']:
        mimeType = ngamsHighLevelLib.determineMimeType(srvObj.getCfg(), 
                                                       reqPropsObj.getFileUri())
        reqPropsObj.setMimeType(mimeType)
    else:
        reqPropsObj.setMimeType(parsDic['mimeType'])

    # Is this NG/AMS permitted to handle Archive Requests?
    info(3, "Is this NG/AMS permitted to handle Archive Requests?")

    if not srvObj.getCfg().getAllowArchiveReq():
        errMsg = genLog("NGAMS_ER_ILL_REQ", ["Archive"])
        raise Exception, errMsg

    srvObj.checkSetState("Archive Request", [NGAMS_ONLINE_STATE],
                         [NGAMS_IDLE_SUBSTATE, NGAMS_BUSY_SUBSTATE],
                         NGAMS_ONLINE_STATE, NGAMS_BUSY_SUBSTATE,
                         updateDb=False)

    reqPropsObj.incIoTime(0)
    reqPropsObj.setNoReplication(1)

    port = None
    winsize = None
    num_streams = None
    checksum = None

    if parsDic.has_key('bport'):
        port = int(parsDic['bport'])

    if parsDic.has_key('bwinsize'):
        winsize = parsDic['bwinsize']

    if parsDic.has_key('bnum_streams'):
        num_streams = int(parsDic['bnum_streams'])

    if parsDic.has_key('bchecksum'):
        checksum = parsDic['bchecksum']

    bparam = bbcp_param(port, winsize, num_streams, checksum)

    (resDapi, targDiskInfo, iorate) = archiveFromFile(srvObj, bparam, reqPropsObj)

    # Inform the caching service about the new file.
    info(3, "Inform the caching service about the new file.")
    if (srvObj.getCachingActive()):
        diskId      = resDapi.getDiskId()
        fileId      = resDapi.getFileId()
        fileVersion = 1
        filename    = resDapi.getRelFilename()
        ngamsCacheControlThread.addEntryNewFilesDbm(srvObj, diskId, fileId,
                                                   fileVersion, filename)

    # Update disk info in NGAS Disks.
    info(3, "Update disk info in NGAS Disks.")
    srvObj.getDb().updateDiskInfo(resDapi.getFileSize(), resDapi.getDiskId())

    # Check if the disk is completed.
    # We use an approximate estimate for the remaning disk space to avoid
    # to read the DB.
    info(3, "Check available space in disk")
    availSpace = getDiskSpaceAvail(targDiskInfo.getMountPoint(), smart=False)
    if (availSpace < srvObj.getCfg().getFreeSpaceDiskChangeMb()):
        complDate = PccUtTime.TimeStamp().getTimeStamp()
        targDiskInfo.setCompleted(1).setCompletionDate(complDate)
        targDiskInfo.write(srvObj.getDb())

    # Request after-math ...
    srvObj.setSubState(NGAMS_IDLE_SUBSTATE)
    msg = "Successfully handled Archive Pull Request for data file " +\
          "with URI: " + reqPropsObj.getSafeFileUri()
    info(1, msg)
    srvObj.ingestReply(reqPropsObj, httpRef, NGAMS_HTTP_SUCCESS,
                       NGAMS_SUCCESS, msg, targDiskInfo)

    # Trigger Subscription Thread. This is a special version for MWA, in which we simply swapped MIRRARCHIVE and QARCHIVE
    # chen.wu@icrar.org
    msg = "triggering SubscriptionThread for file %s" % resDapi.getFileId()
    info(3, msg)
    srvObj.addSubscriptionInfo([(resDapi.getFileId(),
                                 resDapi.getFileVersion())], [])
    srvObj.triggerSubscriptionThread()


    return (resDapi.getFileId(), '%s/%s' % (targDiskInfo.getMountPoint(), resDapi.getRelFilename()),
            iorate)
