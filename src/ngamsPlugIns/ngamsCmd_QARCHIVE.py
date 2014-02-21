#
#    ALMA - Atacama Large Millimiter Array
#    (c) European Southern Observatory, 2002
#    Copyright by ESO (in the framework of the ALMA collaboration),
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
#
# "@(#) $Id: ngamsCmd_QARCHIVE.py,v 1.6 2009/12/07 16:36:40 awicenec Exp $"
#
# Who       When        What
# --------  ----------  -------------------------------------------------------
# jknudstr  03/02/2009  Created
#

"""
NGAS Command Plug-In, implementing a Quick Archive Command.

This works in a similar way as the 'standard' ARCHIVE Command, but has been
simplified in a few ways:

  - No replication to a Replication Volume is carried out.
  - Target disks are selected randomly, disregarding the Streams/Storage Set
    mappings in the configuration. This means that 'volume load balancing' is
    provided.
  - Archive Proxy Mode is not supported.
  - No probing for storage availability is supported.
  - In general, less SQL queries are performed and the algorithm is more
    light-weight.
  - crc is computed from the incoming stream
  - ngas_files data is 'cloned' from the source file
"""

from ngams import *
import random
import binascii
import socket
#import pcc, PccUtTime
import ngamsLib, ngamsDbCore, ngamsFileInfo
import ngamsDiskInfo, ngamsHighLevelLib
import ngamsCacheControlThread


GET_AVAIL_VOLS_QUERY = "SELECT %s FROM ngas_disks nd WHERE completed=0 AND " +\
                       "host_id='%s'"


def getTargetVolume(srvObj):
    """
    Get a random target volume with availability.

    srvObj:         Reference to NG/AMS server class object (ngamsServer).

    Returns:        Target volume object or None (ngamsDiskInfo | None).
    """
    T = TRACE()

    sqlQuery = GET_AVAIL_VOLS_QUERY % (ngamsDbCore.getNgasDisksCols(),
                                       getHostId())
    res = srvObj.getDb().query(sqlQuery, ignoreEmptyRes=0)
    if (res == [[]]):
        return None
    else:
        # Shuffle the results.
        random.shuffle(res[0])
        return ngamsDiskInfo.ngamsDiskInfo().unpackSqlResult(res[0][0])


def updateDiskInfo(srvObj,
                   resDapi):
    """
    Update the row for the volume hosting the new file.

    srvObj:    Reference to NG/AMS server class object (ngamsServer).

    resDapi:   Result returned from the DAPI (ngamsDapiStatus).

    Returns:   Void.
    """
    T = TRACE()

    sqlQuery = "UPDATE ngas_disks SET " +\
               "number_of_files=(number_of_files + 1), " +\
               "bytes_stored=(bytes_stored + %d) WHERE " +\
               "disk_id='%s'"
    sqlQuery = sqlQuery % (resDapi.getFileSize(), resDapi.getDiskId())
    srvObj.getDb().query(sqlQuery, ignoreEmptyRes=0)

def saveInStagingFile(ngamsCfgObj,
                      reqPropsObj,
                      stagingFilename,
                      diskInfoObj):
    """
    Save the data ready on the HTTP channel, into the given Staging
    Area file.

    ngamsCfgObj:     NG/AMS Configuration (ngamsConfig).

    reqPropsObj:     NG/AMS Request Properties object (ngamsReqProps).

    stagingFilename: Staging Area Filename as generated by
                     ngamsHighLevelLib.genStagingFilename() (string).

    diskInfoObj:     Disk info object. Only needed if mutual exclusion
                     is required for disk access (ngamsDiskInfo).

    Returns:         Void.
    """
    T = TRACE()

    try:
        blockSize = ngamsCfgObj.getBlockSize()
        return saveFromHttpToFile(ngamsCfgObj, reqPropsObj, stagingFilename,
                                  blockSize, 1, diskInfoObj)
    except Exception, e:
        errMsg = genLog("NGAMS_ER_PROB_STAGING_AREA", [stagingFilename,str(e)])
        error(errMsg)
        raise Exception, errMsg


def saveFromHttpToFile(ngamsCfgObj,
                       reqPropsObj,
                       trgFilename,
                       blockSize,
                       mutexDiskAccess = 1,
                       diskInfoObj = None):
    """
    Save the data available on an HTTP channel into the given file.

    ngamsCfgObj:     NG/AMS Configuration object (ngamsConfig).

    reqPropsObj:     NG/AMS Request Properties object (ngamsReqProps).

    trgFilename:     Target name for file where data will be
                     written (string).

    blockSize:       Block size (bytes) to apply when reading the data
                     from the HTTP channel (integer).

    mutexDiskAccess: Require mutual exclusion for disk access (integer).

    diskInfoObj:     Disk info object. Only needed if mutual exclusion
                     is required for disk access (ngamsDiskInfo).

    Returns:         Tuple. Element 0: Time in took to write
                     file (s) (tuple).
    """
    T = TRACE()

    checkCreatePath(os.path.dirname(trgFilename))
    fdOut = open(trgFilename, "w")
    info(2,"Saving data in file: " + trgFilename + " ...")
    timer = PccUtTime.Timer()
    try:
        # Make mutual exclusion on disk access (if requested).
        if (mutexDiskAccess):
            ngamsHighLevelLib.acquireDiskResource(ngamsCfgObj, diskInfoObj.getSlotId())

        # Distinguish between Archive Pull and Push Request. By Archive
        # Pull we may simply read the file descriptor until it returns "".
        sizeKnown = 0
        if (ngamsLib.isArchivePull(reqPropsObj.getFileUri()) and
            not reqPropsObj.getFileUri().startswith('http://')):
            # (reqPropsObj.getSize() == -1)):
            # Just specify something huge.
            info(3,"It is an Archive Pull Request/data with unknown size")
            remSize = int(1e11)
        elif reqPropsObj.getFileUri().startswith('http://'):
            info(3,"It is an HTTP Archive Pull Request: trying to get Content-length")
            httpInfo = reqPropsObj.getReadFd().info()
            headers = httpInfo.headers
            hdrsDict = ngamsLib.httpMsgObj2Dic(''.join(headers))
            if hdrsDict.has_key('content-length'):
                remSize = int(hdrsDict['content-length'])
            else:
                info(3,"No HTTP header parameter Content-length!")
                info(3,"Header keys: %s" % hdrsDict.keys())
                remSize = int(1e11)
        else:
            remSize = reqPropsObj.getSize()
            info(3,"Archive Push/Pull Request - Data size: %d" % remSize)
            sizeKnown = 1

        # Receive the data.
        buf = "-"
        rdSize = blockSize
        slow = blockSize / (512 * 1024.)  # limit for 'slow' transfers
#        sizeAccu = 0
        lastRecepTime = time.time()
        crc = 0   # initialize CRC value
        rdtt = 0  # total read time
        cdtt = 0  # total CRC time
        wdtt = 0  # total write time
        nb = 0    # number of blocks
        srb = 0   # number of slow read blocks
        scb = 0   # number of slow CRC calcs
        swb = 0   # number of slow write blocks
        tot_size = 0 # total number of bytes
        
        readFd = reqPropsObj.getReadFd()
        rcvBuffSize = ngamsCfgObj.getArchiveRcvBufSize()
        if (rcvBuffSize and str(type(readFd)) == "<class 'socket._fileobject'>" and readFd._sock):   
            dfRcvBuffSize = readFd._sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
            while (rcvBuffSize > dfRcvBuffSize):
                try:
                    readFd._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvBuffSize)
                    info(3, "Rcv buf size reset to %d" % rcvBuffSize)
                    break
                except Exception, exp:
                    if (str(exp) == '[Errno 55] No buffer space available'):
                        rcvBuffSize = int(rcvBuffSize / 2)
                        continue
                    else:
                        warning('Fail to set the socket SO_RCVBUF to %s: %s' % (str(rcvBuffSize), str(exp)))
        
        while ((remSize > 0) and ((time.time() - lastRecepTime) < 30.0)):
            if (remSize < rdSize): rdSize = remSize
            rdt = time.time()
            buf = readFd.read(rdSize)
            rdt = time.time() - rdt
            rdtt += rdt
            if rdt >= slow: rdt += 1
            nb += 1
            sizeRead = len(buf)
#            info(5,"Read %d bytes from HTTP stream in %.3f s" % (sizeRead, rdt))
            if (sizeRead > 0):
                cdt = time.time()
                crc = binascii.crc32(buf, crc)
                cdt = time.time() - cdt
                cdtt += cdt
                if cdt >= slow: scb += 1
#                info(5,"Calculated checksum from stream buffer in %.3f s" % cdt)

            remSize -= sizeRead
            tot_size += sizeRead
#            reqPropsObj.setBytesReceived(reqPropsObj.getBytesReceived() +\
#                                         sizeRead)
            if (sizeRead > 0):
                wdt = time.time()
                fdOut.write(buf)
                wdt = time.time() - wdt
                wdtt += wdt
                if wdt >= slow: swb += 1
#                info(5,"Wrote %d bytes to file in %.3f s" % (sizeRead, wdt))
                lastRecepTime = time.time()
            else:
                info(4,"Unsuccessful read attempt from HTTP stream! Sleeping 50 ms")
                time.sleep(0.050)

        deltaTime = timer.stop()
        reqPropsObj.setBytesReceived(tot_size)
        fdOut.close()
        info(4,"Transfer time: %.3f s; CRC time: %.3f s; write time %.3f s" % (rdtt, cdtt, wdtt))
        msg = "Saved data in file: %s. Bytes received: %d. Time: %.3f s. " +\
              "Rate: %.2f Bytes/s"
        ingestRate = (float(reqPropsObj.getBytesReceived()) / deltaTime)
        info(2,msg % (trgFilename, int(reqPropsObj.getBytesReceived()),
                      deltaTime, ingestRate))
        # Raise a special info message if the transfer speed to disk or over network was
        # slower than 512 kB/s
        if srb > 0:
            warning("Number of slow network reads during this transfer: %d. \
            Consider checking the network!" % srb)
        if swb > 0:
            warning("Number of slow disk writes during this transfer: %d. \
            Consider checking your disks!" % swb)
        # Raise exception if less byes were received as expected.
        if (sizeKnown and (remSize > 0)):
            msg = genLog("NGAMS_ER_ARCH_RECV",
                         [reqPropsObj.getFileUri(), reqPropsObj.getSize(),
                          (reqPropsObj.getSize() - remSize)])
            raise Exception, msg
        
        checksum = reqPropsObj.getHttpHdr(NGAMS_HTTP_HDR_CHECKSUM)
        if (checksum):
            if (checksum != str(crc)):
                msg = 'Checksum error for file %s, local crc = %s, but remote crc = %s' % (reqPropsObj.getFileUri(), str(crc), checksum)
                error(msg)
                raise Exception, msg
            else:
                info(3, "%s CRC checked, OK!" % reqPropsObj.getFileUri())

        # Release disk resouce.
        if (mutexDiskAccess):
            ngamsHighLevelLib.releaseDiskResource(ngamsCfgObj, diskInfoObj.getSlotId())

        return [deltaTime,crc,ingestRate]
    except Exception, e:
        fdOut.close()
        # Release disk resouce.
        if (mutexDiskAccess):
            ngamsHighLevelLib.releaseDiskResource(ngamsCfgObj, diskInfoObj.getSlotId())
        raise Exception, e


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
    if (reqPropsObj.getFileUri() == ""):
        errMsg = genLog("NGAMS_ER_MISSING_URI")
        error(errMsg)
        raise Exception, errMsg

    # Is this NG/AMS permitted to handle Archive Requests?
    info(3, "Is this NG/AMS permitted to handle Archive Requests?")
    if (not srvObj.getCfg().getAllowArchiveReq()):
        errMsg = genLog("NGAMS_ER_ILL_REQ", ["Archive"])
        raise Exception, errMsg
    srvObj.checkSetState("Archive Request", [NGAMS_ONLINE_STATE],
                         [NGAMS_IDLE_SUBSTATE, NGAMS_BUSY_SUBSTATE],
                         NGAMS_ONLINE_STATE, NGAMS_BUSY_SUBSTATE,
                         updateDb=False)

    # Get mime-type (try to guess if not provided as an HTTP parameter).
    info(3, "Get mime-type (try to guess if not provided as an HTTP parameter).")
    if (reqPropsObj.getMimeType() == ""):
        mimeType = ngamsHighLevelLib.\
                   determineMimeType(srvObj.getCfg(), reqPropsObj.getFileUri())
        reqPropsObj.setMimeType(mimeType)
    else:
        mimeType = reqPropsObj.getMimeType()


    ## Set reference in request handle object to the read socket.
    info(3, "Set reference in request handle object to the read socket.")
    if reqPropsObj.getFileUri().startswith('http://'):
        fileUri = reqPropsObj.getFileUri()
        readFd = ngamsHighLevelLib.openCheckUri(fileUri)
        reqPropsObj.setReadFd(readFd)

    # Determine the target volume, ignoring the stream concept.
    info(3, "Determine the target volume, ignoring the stream concept.")
    targDiskInfo = getTargetVolume(srvObj)
    if (targDiskInfo == None):
        errMsg = "No disk volumes are available for ingesting any files."
        error(errMsg)
        raise Exception, errMsg
    reqPropsObj.setTargDiskInfo(targDiskInfo)

    # Generate staging filename.
    info(3, "Generate staging filename from URI: %s" % reqPropsObj.getFileUri())
    if (reqPropsObj.getFileUri().find("file_id=") >= 0):
        file_id = reqPropsObj.getFileUri().split("file_id=")[1]
        baseName = os.path.basename(file_id)
    else:
        baseName = os.path.basename(reqPropsObj.getFileUri())
    stgFilename = os.path.join("/", targDiskInfo.getMountPoint(),
                               NGAMS_STAGING_DIR,
                               genUniqueId() + "___" + baseName)
    if stgFilename.count('.') == 0:  #make sure there is at least one extension
        stgFilename = ngamsHighLevelLib.checkAddExt(srvObj.getCfg(), reqPropsObj.getMimeType(), stgFilename)

    info(3, "Staging filename is: %s" % stgFilename)
    reqPropsObj.setStagingFilename(stgFilename)

    # Retrieve file contents (from URL, archive pull, or by storing the body
    # of the HTTP request, archive push).
    stagingInfo = saveInStagingFile(srvObj.getCfg(), reqPropsObj,
                                    stgFilename, targDiskInfo)
    ioTime = stagingInfo[0]
    reqPropsObj.incIoTime(ioTime)

    # Invoke DAPI.
    plugIn = srvObj.getMimeTypeDic()[mimeType]
    try:
        exec "import " + plugIn
    except Exception, e:
        errMsg = "Error loading DAPI: %s. Error: %s" % (plugIn, str(e))
        raise Exception, errMsg
    info(2, "Invoking DAPI: " + plugIn +\
         " to handle data for file with URI: " + baseName)
    timeBeforeDapi = time.time()
    resDapi = eval(plugIn + "." + plugIn + "(srvObj, reqPropsObj)")
    if (getVerboseLevel() > 4):
        info(3, "Invoked DAPI: %s. Time: %.3fs." %\
             (plugIn, (time.time() - timeBeforeDapi)))
        info(3, "Result DAPI: %s" % str(resDapi.toString()))

    # Move file to final destination.
    info(3, "Moving file to final destination")
    ioTime = mvFile(reqPropsObj.getStagingFilename(),
                    resDapi.getCompleteFilename())
    reqPropsObj.incIoTime(ioTime)

    # Get crc info
    info(3, "Get checksum info")
    crc = stagingInfo[1]
    checksumPlugIn = "ngamsGenCrc32"
    checksum = str(crc)
    info(3, "Invoked Checksum Plug-In: " + checksumPlugIn +\
            " to handle file: " + resDapi.getCompleteFilename() +\
            ". Result: " + checksum)

    # Get source file version
    # e.g.: http://ngas03.hq.eso.org:7778/RETRIEVE?file_version=1&file_id=X90/X962a4/X1
    info(3, "Get file version")
    file_version = resDapi.getFileVersion()
    if reqPropsObj.getFileUri().count("file_version"):
        file_version = int((reqPropsObj.getFileUri().split("file_version=")[1]).split("&")[0])

    # Check/generate remaining file info + update in DB.
    info(3, "Creating db entry")
    ts = PccUtTime.TimeStamp().getTimeStamp()
    creDate = getFileCreationTime(resDapi.getCompleteFilename())
    fileInfo = ngamsFileInfo.ngamsFileInfo().\
               setDiskId(resDapi.getDiskId()).\
               setFilename(resDapi.getRelFilename()).\
               setFileId(resDapi.getFileId()).\
               setFileVersion(file_version).\
               setFormat(resDapi.getFormat()).\
               setFileSize(resDapi.getFileSize()).\
               setUncompressedFileSize(resDapi.getUncomprSize()).\
               setCompression(resDapi.getCompression()).\
               setIngestionDate(ts).\
               setChecksum(checksum).setChecksumPlugIn(checksumPlugIn).\
               setFileStatus(NGAMS_FILE_STATUS_OK).\
               setCreationDate(creDate)
    fileInfo.write(srvObj.getDb())

    # Inform the caching service about the new file.
    info(3, "Inform the caching service about the new file.")
    if (srvObj.getCachingActive()):
        diskId      = resDapi.getDiskId()
        fileId      = resDapi.getFileId()
        fileVersion = file_version
        filename    = resDapi.getRelFilename()
        ngamsCacheControlThread.addEntryNewFilesDbm(srvObj, diskId, fileId,
                                                   fileVersion, filename)

    # Update disk info in NGAS Disks.
    info(3, "Update disk info in NGAS Disks.")
    updateDiskInfo(srvObj, resDapi)

    # Check if the disk is completed.
    # We use an approximate extimate for the remaning disk space to avoid
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


    return (resDapi.getFileId(), '%s/%s' % (targDiskInfo.getMountPoint(), resDapi.getRelFilename()), stagingInfo[2])

# EOF
