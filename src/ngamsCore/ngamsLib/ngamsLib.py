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
#
# "@(#) $Id: ngamsLib.py,v 1.13 2008/08/19 20:51:50 jknudstr Exp $"
#
# Who       When        What
# --------  ----------  -------------------------------------------------------
# jknudstr  12/05/2001  Created
#
"""
Base module that contains various utility functions used for the
NG/AMS implementation.

The functions in this module can be used in all the NG/AMS code.
"""

import cPickle
import contextlib
import httplib
import logging
import os
import re
import shutil
import socket
import string
import time
import urllib
import urllib2
import urlparse

from ngamsCore import genLog, getHostName, \
    NGAMS_HTTP_SUCCESS, NGAMS_CONT_MT, \
    NGAMS_HTTP_POST, NGAMS_HTTP_HDR_FILE_INFO, NGAMS_HTTP_HDR_CHECKSUM, \
    getFileSize, NGAMS_ARCH_REQ_MT, getUniqueNo, \
    NGAMS_MAX_FILENAME_LEN, NGAMS_UNKNOWN_MT, rmFile, toiso8601
import ngamsMIMEMultipart


logger = logging.getLogger(__name__)

def hidePassword(fileUri):
    """
    Hide password in a URI by replacing it by asterix characters.

    fileUri:   File URI (string).

    Returns:   URI with password blanked out (string).
    """
    if (not fileUri): return fileUri
    tmpUri = urllib.unquote(fileUri)
    if (string.find(tmpUri, "ftp://") != -1):
        # ARCHIVE?filename="ftp://jknudstr:*****@arcus2.hq.eso.org//home/...
        lst1 = string.split(tmpUri,"@")
        if (len(lst1) == 1):
            errMsg = genLog("NGAMS_ER_ILL_URI", [fileUri,
                                                 "Archive Pull Request"])
            raise Exception, errMsg
        lst2 = string.split(lst1[0], ":")
        retVal = lst2[0] + ":" + lst2[1] + ":*****@" + lst1[1]
    else:
        retVal = tmpUri
    return retVal


def isArchivePull(uri):
    """
    Return 1 if the request is referring to an Archive Pull Request.

    Returns:    1 = Archive Pull Request, 0 otherwise (integer).
    """
    logger.debug("isArchivePull() - File URI is: %s", uri)
    return 'http:' in uri or 'ftp:' in uri or 'file:' in uri


def parseHttpHdr(httpHdr):
    """
    Parse an HTTP header like this:

      <par>=<val>; <par>=<val>

    httpHdr:     HTTP header (string).

    Returns:     List with the contents:

                 [[<par>, <value>], [<par>, <value>], ...]
    """
    retDic = {}
    els = string.split(httpHdr, ";")
    for el in els:
        subEls = string.split(el, "=")
        key = subEls[0].strip("\" ")
        if (len(subEls) > 1):
            value = subEls[1].strip("\" ")
        else:
            value = ""
        retDic[key] = value
    return retDic


def httpMsgObj2Dic(httpMessageObj):
    """
    Stores the HTTP header information of mimetools.Message object
    in a dictionary, whereby the header names are keys.

    httpMessageObj:     Message object (mimetools.Message).

    Returns:            Dictionary with HTTP header information (dictionary).
    """
    httpHdrDic = {}
    for httpHdr in str(httpMessageObj).split("\r\n"):
        if (httpHdr != ""):
            idx = httpHdr.index(":")
            hdr, val = [httpHdr[0:idx].lower(), httpHdr[(idx + 2):]]
            httpHdrDic[hdr] = val
    return httpHdrDic


def getCompleteHostName():
    """
    Return the complete host name, i.e., including the name of the domain.

    Returns:   Host name for this NGAS System (string).
    """
    return socket.getfqdn()


def getDomain():
    """
    Return the name of the domain.

    Returns: Domain name or "" if unknown (string).
    """
    fqdn = socket.getfqdn()
    if '.' not in fqdn:
        return ""
    return '.'.join(fqdn.split('.')[1:])


def makeFileReadOnly(completeFilename):
    """
    Make a file read-only.

    completeFilename:    Complete name of file (string).

    Returns:             Void.
    """
    os.chmod(completeFilename, 0444)
    logger.debug("File: %s made read-only", completeFilename)


def fileWritable(filename):
    """
    Return 1 if file is writable, otherwise return 0.

    filename:   Name of file (path) to check (string).

    Returns:    1 if file is writable, otherwise 0 (integer).
    """
    return os.access(filename, os.W_OK)


_http_fmt = "%a, %d %b %Y %H:%M:%S GMT"
def httpTimeStamp():
    """
    Generate a time stamp in the 'HTTP format', e.g.:

        'Mon, 17 Sep 2001 09:21:38 GMT'

    Returns:  Timestamp (string).
    """
    return time.strftime(_http_fmt, time.gmtime(time.time()))


def _httpHandleResp(fileObj,
                    dataTargFile,
                    blockSize,
                    timeOut = None):
    """
    Handle the response to an HTTP request. If specified, the data returned
    will be either returned in a buffer or stored in a target file specified.

    fileObj:          File object returned from urllib2.urlopen()
                      (file object).

    dataTargFile:     Target file in which the possible data returned
                      will be stored (string)

    blockSize:        Block size in bytes to apply when handling data
                      (integer).

    timeOut:          Timeout to wait for reply from the server seconds
                      (double).

    Returns:          List with information from reply from contacted
                      NG/AMS Server (reply, msg, hdrs, data|File Object)
                      (list).
    """
    # Handle the response + data.
    code   = NGAMS_HTTP_SUCCESS
    msg    = "OK"
    hdrs   = fileObj.headers
    hdrDic = httpMsgObj2Dic(hdrs)

    if not hdrDic:
        logger.warning("No headers received from HTTP request!")

    dataSize = 0
    if (hdrDic.has_key("content-length")):
        dataSize = int(hdrDic["content-length"])

    logger.debug("Size of data returned by remote host: %d", dataSize)

    if not dataTargFile:
        data = []
        toRead = dataSize
        readIn = 0
        while readIn < toRead:
            buff = fileObj.read(toRead - readIn)
            if not buff:
                raise Exception('error reading data')
            data.append(buff)
            readIn += len(buff)
        data = ''.join(data)

    # It's a container
    elif (NGAMS_CONT_MT == hdrDic['content-type']):
        handler = ngamsMIMEMultipart.FilesystemWriterHandler(1024, basePath=dataTargFile)
        parser = ngamsMIMEMultipart.MIMEMultipartParser(handler, fileObj, dataSize, 1024)
        parser.parse()
        data = handler.getRootSavingDirectory()

    else:
        # If the 'target file' specified in fact is a directory, we take the
        # filename contained in the Content-Disposition of the HTTP header.
        if (os.path.isdir(dataTargFile)):
            if (hdrDic.has_key("content-disposition")):
                tmpLine = hdrDic["content-disposition"]
                filename = string.split(string.split(tmpLine, ";")[1], "=")[1]
            else:
                filename = genUniqueFilename("HTTP-RESPONSE-DATA")
            trgFile = os.path.normpath(dataTargFile + "/" + filename.strip(' "'))
        else:
            trgFile = dataTargFile

        data = trgFile
        toRead = dataSize
        readIn = 0
        with open(trgFile, 'wb') as fd:
            while readIn < toRead:
                buff = fileObj.read(toRead - readIn)
                if not buff:
                    raise Exception('error reading data')
                fd.write(buff)
                readIn += len(buff)

    # Dump HTTP headers if Verbose Level >= 4.
    logger.debug("HTTP Header: HTTP/1.0 %s %s", str(code), msg)
    if logger.isEnabledFor(logging.DEBUG):
        for hdr in hdrs.keys():
            logger.debug("HTTP Header: %s: %s", hdr, hdrs[hdr])

    return code, msg, hdrs, data


def httpPostUrl(url,
                mimeType,
                contDisp = "",
                dataRef = "",
                dataSource = "BUFFER",
                dataTargFile = "",
                blockSize = 65536,
                suspTime = 0.0,
                timeOut = None,
                authHdrVal = "",
                dataSize = -1,
                fileInfoHdr = None,
                sendBuffer = None,
                checkSum = None,
                moreHdrs = []):
    """
    Post the the data referenced on the given URL.

    The data send back from the remote server + the HTTP header information
    is return in a list with the following contents:

      [<HTTP status code>, <HTTP status msg>, <HTTP headers (list)>, <data>]

    url:          URL to where data is posted (string).

    mimeType:     Mime-type of message (string).

    contDisp:     Content-Disposition of the data (string).

    dataRef:      Data to post or name of file containing data to send
                  (string).

    dataSource:   Source where to pick up the data (string/BUFFER|FILE|FD|FILESLIST).

    dataTargFile: If a filename is specified with this parameter, the
                  data received is stored into a file of that name (string).

    blockSize:    Block size (in bytes) used when sending the data (integer).

    suspTime:     Time in seconds to suspend between each block (double).

    timeOut:      Timeout in seconds to wait for replies from the server
                  (double).

    authHdrVal:   Authorization HTTP header value as it should be sent in
                  the query (string).

    dataSize:     Size of data to send if read from a socket (integer).

    fileInfoHdr:  File info serialised as an XML doc for command REARCHIVE (string)

    moreHdrs:     A list of key-value pairs, each kv pair is a tuple with two elements (k and v)

    Returns:      List with information from reply from contacted
                  NG/AMS Server (reply, msg, hdrs, data) (list).
    """
    urlres = urlparse.urlparse(url)

    if urlres.scheme.lower() == 'houdt':
        import ngamsUDTSender
        return ngamsUDTSender.httpPostUrl(url, mimeType, contDisp, dataRef, dataSource, dataTargFile, blockSize, suspTime, timeOut, authHdrVal, dataSize)

    cmd = urlres.path.strip('/')

    with contextlib.closing(httplib.HTTPConnection(urlres.netloc, timeout = timeOut)) as http:
        logger.debug("Sending HTTP header ...")
        logger.debug("HTTP Header: %s: %s", NGAMS_HTTP_POST, cmd)
        http.putrequest(NGAMS_HTTP_POST, cmd)

        logger.debug("HTTP Header: Content-Type: %s", mimeType)
        http.putheader("Content-Type", mimeType)
        if (contDisp != ""):
            logger.debug("HTTP Header: Content-Disposition: %s", contDisp)
            http.putheader("Content-Disposition", contDisp)
        if (authHdrVal):
            if (authHdrVal[-1] == "\n"):
                authHdrVal = authHdrVal[:-1]
            logger.debug("HTTP Header: Authorization: %s", authHdrVal)
            http.putheader("Authorization", authHdrVal)
        if (fileInfoHdr):
            http.putheader(NGAMS_HTTP_HDR_FILE_INFO, fileInfoHdr)
        if (checkSum):
            http.putheader(NGAMS_HTTP_HDR_CHECKSUM, checkSum)

        for k,v in moreHdrs:
            http.putheader(k, v)

        if dataSource == "FILE":
            dataSize = getFileSize(dataRef)
        elif dataSource == "BUFFER":
            dataSize = len(dataRef)

        if dataSize == -1:
            raise Exception('Could not determine length of content')

        logger.debug("HTTP Header: Content-Length: %s", str(dataSize))
        http.putheader("Content-Length", str(dataSize))
        logger.debug("HTTP Header: Host: %s", getHostName())
        http.putheader("Host", getHostName())
        http.endheaders()
        logger.debug("HTTP header sent")

        if dataSource == "FILE":
            with open(dataRef) as fdIn:
                toSend = dataSize
                sent = 0
                while sent < toSend:
                    buff = fdIn.read(toSend - sent)
                    if not buff:
                        raise Exception('error reading data')
                    http.sock.sendall(buff)
                    sent += len(buff)

        elif dataSource == "FILESLIST":
            writer = dataRef[0]
            allPaths = dataRef[1]
            writer.setOutput(http.sock.makefile("w"))
            writeDirContents(writer, allPaths[1], blockSize, suspTime)

        elif dataSource == "FD":
            toSend = dataSize
            sent = 0
            while sent < toSend:
                buff = dataRef.read(toSend - sent)
                if not buff:
                    raise Exception('error reading data')
                http.sock.sendall(buff)
                sent += len(buff)

        elif dataSource == "BUFFER":
            http.sock.sendall(dataRef)

        else:
            raise Exception('Unknown data source: ' + dataSource)

        logger.debug("Data sent, waiting for reply")

        # Receive + unpack reply.
        response = http.getresponse()
        reply, msg, hdrs = response.status, response.reason, response.getheaders()

        hdrs = {h[0]: h[1] for h in hdrs}

        dataSize = 0
        if (hdrs.has_key("content-length")):
            dataSize = int(hdrs["content-length"])

        if not dataTargFile:
            data = []
            toRead = dataSize
            readIn = 0
            while readIn < toRead:
                buff = response.read(toRead - readIn)
                if not buff:
                    raise Exception('error reading data')
                data.append(buff)
                readIn += len(buff)
            data = ''.join(data)
        else:
            data = dataTargFile
            toRead = dataSize
            readIn = 0
            with open(dataTargFile, 'wb') as out:
                while readIn < toRead:
                    buff = response.read(toRead - readIn)
                    if not buff:
                        raise Exception('error reading data')
                    out.write(buff)
                    readIn += len(buff)

        # Dump HTTP headers if Verbose Level >= 4.
        logger.debug("HTTP Header: HTTP/1.0 %s %s", str(reply), msg)
        if logger.isEnabledFor(logging.DEBUG):
            for hdr in hdrs.keys():
                logger.debug("HTTP Header: %s: %s", hdr, hdrs[hdr])

        return [reply, msg, hdrs, data]

def writeDirContents(writer, paths, blockSize, suspTime):

    writer.startContainer()
    for absPath in paths:
        if isinstance(absPath, list):
            writeDirContents(writer, absPath[1], blockSize, suspTime)
        else:
            writer.startNextFile()
            fdIn = open(absPath)
            block = '-'
            while (block != ""):
                block = fdIn.read(blockSize)
                writer.writeData(block)
                if (suspTime > 0.0): time.sleep(suspTime)
            fdIn.close()
    writer.endContainer()

def httpPost(host,
             port,
             cmd,
             mimeType,
             dataRef = "",
             dataSource = "BUFFER",
             pars = [],
             dataTargFile = "",
             timeOut = None,
             authHdrVal = "",
             fileName = "",
             dataSize = -1):
    """
    Sends an HTTP POST command with the given mime-type and the given
    data to the NG/AMS Server with the host + port given.

    The data send back from the remote server + the HTTP header information
    is return in a list with the following contents:

      [<HTTP status code>, <HTTP status msg>, <HTTP headers (list)>, <data>]

    host:         Host where remote NG/AMS Server is running (string).

    port:         Port number used by remote NG/AMS Server (integer).

    cmd:          NG/AMS command to send (string).

    mimeType:     Mime-type of message (string).

    dataRef:      Data to send to remote NG/AMS Server or name of
                  file/directory containing data to send (string).

    dataSource:   Source where to pick up the data (string/BUFFER|FILE|FD).

    pars:         List of sub-lists containing parameters + values.
                  Format is:

                    [[<par 1>, <val par 1>], ...]

                  These are send as 'Content-Disposition' in the HTTP
                  command (list).

    dataTargFile: If a filename is specified with this parameter, the
                  data received is stored into a file of that name (string).

    timeOut:      Timeout in seconds to wait for replies from the server
                  (double).

    authHdrVal:   Authorization HTTP header value as it should be sent in
                  the query (string).

    fileName:     Filename if data sent within the request (string).

    dataSize:     Size of data to send if read from a socket (integer).

    Returns:      List with information from reply from contacted
                  NG/AMS Server (reply, msg, hdrs, data) (list).
    """
    # If the dataRef is a directory, scan the directory
    # and build up a list of files contained directly within
    # Start preparing a mutipart MIME message that will contain
    # all of them
    if isinstance(dataRef, basestring) and os.path.isdir(dataRef):

        absDirname = os.path.abspath(dataRef)
        logger.debug('Request is to archive directory %s', absDirname)
        mimeType = NGAMS_CONT_MT

        # Recursively collect all files
        # TODO: Probably here we can reuse the filesInformation
        # structure instead of having the absPaths separately
        filesInformation, absPaths = collectFiles(absDirname)

        writer = ngamsMIMEMultipart.MIMEMultipartWriter(filesInformation)
        dataSize = writer.getTotalSize()

        dataRef = [writer, absPaths]
        dataSource = 'FILESLIST'

        fileName = 'mimemessage'
        if pars[0][0] == 'attachment; filename': pars[0][0] = 'attachment'

    contDisp = []
    for parInfo in pars:
        if parInfo[0] == "attachment":
            if fileName:
                contDisp.append('attachment; filename="%s"; ' % fileName)
        else:
            contDisp.append('%s="%s"; ' % (parInfo[0], urllib.quote(str(parInfo[1]))))
    contDisp = ''.join(contDisp)

    msg = "Sending: %s using HTTP POST with mime-type: %s " + \
          "to NG/AMS Server with host: %s:%d"
    logger.debug(msg, cmd, mimeType, host, port)

    url = "http://%s:%d/%s" % (host, port, cmd)
    return httpPostUrl(url, mimeType, contDisp, dataRef, dataSource,
                       dataTargFile, 65536, 0, timeOut, authHdrVal, dataSize)

def collectFiles(absDirname):

    dirname = os.path.basename(os.path.abspath(absDirname))
    absPaths = []
    filesInfo = []

    for filename in os.listdir(absDirname):
        # Include only files for the time being
        path = os.path.join(absDirname, filename)
        if os.path.isdir(path):
            childrenFiles, childrenPaths = collectFiles(path)
            filesInfo.append(childrenFiles)
            absPaths.append(childrenPaths)
        elif os.path.isfile(path):
            logger.debug('Including "%s" in the to-be-generated container', path)
            absPaths.append(path)
            filesInfo.append([NGAMS_ARCH_REQ_MT, filename, os.path.getsize(path), path])
        else:
            logger.debug('Not including "%s" because it\'s neither a file nor a directory', path)

    return [[dirname, filesInfo], [absDirname, absPaths]]


def httpGetUrl(url,
               dataTargFile = "",
               blockSize = 65536,
               timeOut = None,
               authHdrVal = "",
               additionalHdrs = []):
    """
    Sends an HTTP GET request to the server specified by the URL.

    The data send back from the remote server + the HTTP header information
    is return in a list with the following contents:

      [<HTTP status code>, <HTTP status msg>, <HTTP headers (list)>, <data>]

    url:              URL to query (string/URL).

    dataTargFile:     If a filename is specified with this parameter, the
                      data received is stored into a file of that name
                      (string).

    blockSize:        Block size in bytes used when handling the data
                      (integer).

    timeOut:          Timeout to apply when communicating with the server in
                      seconds (double).

    authHdrVal:       Authorization HTTP header value as it should be sent in
                      the query (string).

    additionalHdrs:   Additional HTTP headers to send with the request. Must
                      be formatted as:

                        [[<hdr>, <val>], ...]                      (list).

    Returns:          List with information from reply from contacted
                      NG/AMS Server (list).
    """

    # Issue request + handle result.
    req = create_request(url, authHdrVal, additionalHdrs)

    try:
        with contextlib.closing(urllib2.urlopen(req, timeout=timeOut)) as f:
            return _httpHandleResp(f, dataTargFile, blockSize, timeOut)
    except urllib2.HTTPError, e:
        logger.exception("error while sending GET request")
        code, msg, hdrs, data = e.code, str(e), e.headers, e.read()
        return code, msg, hdrs, data


def get_url(host, port, cmd, pars):
    """
    Creates the URL for the given combination of inputs
    """
    parDic = {p[0]: p[1] for p in pars}
    url = "http://" + host + ":" + str(port) + "/" + cmd
    pars = urllib.urlencode(parDic)
    if pars:
        url += '?' + pars
    return url

def create_request(url, auth, hdrs):
    """
    Creates a request for the given combination of inputs
    """
    logger.debug("Issuing request with URL: %s", url)
    req = urllib2.Request(url)
    if auth:
        req.add_header("Authorization", auth)
    req.add_header("Host", getHostName())

    # Send additional HTTP headers, if any.
    for hdr in hdrs:
        req.add_header(hdr[0], hdr[1])

    return req

def httpGet(host,
            port,
            cmd,
            pars = [],
            dataTargFile = "",
            blockSize = 65536,
            timeOut = None,
            authHdrVal = "",
            additionalHdrs = []):
    """
    Sends an HTTP GET command to the NG/AMS Server with the
    host + port given.

    The data send back from the remote server + the HTTP header information
    is return in a list with the following contents:

      [<HTTP status code>, <HTTP status msg>, <HTTP headers (list)>, <data>]

    host:             Host where remote NG/AMS Server is running (string).

    port:             Port number used by remote NG/AMS Server (integer).

    cmd:              NG/AMS command to send (string).

    wait:             Wait for the command to finish execution (integer).

    pars:             List of sub-lists containing parameters + values.
                      Format is:

                        [[<par 1>, <val par 1>], ...]

                      These are send as 'Content-Disposition' in the HTTP
                      command (list).

    dataTargFile:     If a filename is specified with this parameter, the
                      data received is stored into a file of that name
                      (string).

    blockSize:        Block size in bytes used when handling the data
                      (integer).

    timeOut:          Timeout to apply when communicating with the server in
                      seconds (double).

    authHdrVal:       Authorization HTTP header value as it should be sent in
                      the query (string).

    additionalHdrs:   Additional HTTP headers to send with the request. Must
                      be formatted as:

                        [[<hdr>, <val>], ...]                      (list).

    Returns:          List with information from reply from contacted
                      NG/AMS Server (list).
    """
    if (not blockSize): blockSize = 65536

    # Prepare URL + parameters.
    url = get_url(host, port, cmd, pars)

    # Submit the request.
    code, msg, hdrs, data = httpGetUrl(url, dataTargFile,
                                       blockSize, timeOut,
                                       authHdrVal, additionalHdrs)

    return (code, msg, hdrs, data)

def httpGetConnection(host, port, cmd, pars = [], blockSize = 65536,
                      timeOut=None, authHdrVal = "",
                      additionalHdrs = []):
    """
    Similar to httpGet but returns the HTTP connection directly
    """
    url = get_url(host, port, cmd, pars)
    req = create_request(url, authHdrVal, additionalHdrs)
    return urllib2.urlopen(req, timeout=timeOut)


def genUniqueFilename(filename):
    """
    Generate a unique filename of the form:

        <timestamp>-<unique index>-<filename>.<ext>

    filename:   Original filename (string).

    Returns:    Unique filename (string).
    """
    # Generate a unique ID: <time stamp>-<unique index>
    ts = toiso8601()
    tmpFilename = ts + "-" + str(getUniqueNo()) + "-" +\
                  os.path.basename(filename)
    tmpFilename = re.sub("\?|=|&", "_", tmpFilename)

    # We ensure that the length of the filename does not exceed
    # NGAMS_MAX_FILENAME_LEN characters
    nameLen = len(tmpFilename)
    if (nameLen > NGAMS_MAX_FILENAME_LEN):
        lenDif = (nameLen - NGAMS_MAX_FILENAME_LEN)
        tmpFilename = tmpFilename[0:(nameLen - lenDif -\
                                     (NGAMS_MAX_FILENAME_LEN / 2))] +\
                      "__" +\
                      tmpFilename[(nameLen - (NGAMS_MAX_FILENAME_LEN / 2)):]

    return tmpFilename


def parseRawPlugInPars(rawPars):
    """
    Parse the plug-in parameters given in the NG/AMS Configuration
    and return a dictionary with the values.

    rawPars:    Parameters given in connection with the plug-in in
                the configuration file (string).

    Returns:    Dictionary containing the parameters from the plug-in
                parameters as keys referring to the corresponding
                value of these (dictionary).
    """
    # Plug-In Parameters. Expect:
    # "<field name>=<field value>[,field name>=<field value>]"
    parDic = {}
    pars = string.split(rawPars, ",")
    for par in pars:
        if (par != ""):
            try:
                parVal = string.split(par, "=")
                par = parVal[0].strip()
                parDic[par] = parVal[1].strip()
                logger.debug("Found plug-in parameter: %s with value: %s",
                             par, parDic[par])
            except:
                errMsg = genLog("NGAMS_ER_PLUGIN_PAR", [rawPars])
                raise Exception, errMsg
    logger.debug("Generated parameter dictionary: %s", str(parDic))
    return parDic


def detMimeType(mimeTypeMaps,
                filename,
                noException = 0):
    """
    Determine mime-type of a file, based on the information in the
    NG/AMS Configuration and the filename (extension) of the file.

    mimeTypeMaps:  See ngamsConfig.getMimeTypeMappings() (list).

    filename:      Filename (string).

    noException:   If the function should not throw an exception
                   this parameter should be 1. In that case it
                   will return NGAMS_UNKNOWN_MT (integer).

    Returns:       Mime-type (string).
    """
    # Check if the extension as ".<ext>" is found in the filename as
    # the last part of the filename.
    logger.debug("Determining mime-type for file with URI: %s ...", filename)
    found = 0
    mimeType = ""
    for map in mimeTypeMaps:
        ext = "." + map[1]
        idx = string.find(filename, ext)
        if ((idx != -1) and ((idx + len(ext)) == len(filename))):
            found = 1
            mimeType = map[0]
            break
    if ((not found) and noException):
        return NGAMS_UNKNOWN_MT
    elif (not found):
        errMsg = genLog("NGAMS_ER_UNKNOWN_MIME_TYPE1", [filename])
        raise Exception, errMsg
    else:
        logger.debug("Mime-type of file with URI: %s determined: %s",
                     filename, mimeType)

    return mimeType


def getSubscriberId(subscrUrl):
    """
    Generate the Subscriber ID from the Subscriber URL.

    subscrUrl:   Subscriber URL (string).

    Returns:     Subscriber ID (string).
    """
    return subscrUrl.split("?")[0]


def fileRemovable(filename):
    """
    The function checks if a file is removable or not. In case yes, 1 is
    returned otherwise 0 is returned. If the file is not available 0 is
    returned. If the file is not existing 2 is returned.

    filename:     Complete name of file (string).

    Returns:      Indication if file can be removed or not (integer/0|1|2).
    """
    # We simply carry out a temporary move of the file.
    tmpFilename = filename + "_tmp"
    try:
        if (not os.path.exists(filename)): return 2
        shutil.move(filename, tmpFilename)
        shutil.move(tmpFilename, filename)
        return 1
    except:
        return 0


def createObjPickleFile(filename,
                        object):
    """
    Create a file containing the pickled image of the object given.

    filename:    Name of pickle file (string).

    object:      Object to be pickled (<object>)

    Returns:     Void.
    """
    logger.debug("createObjPickleFile() - creating pickle file %s ...", filename)
    rmFile(filename)
    with open(filename, "w") as pickleFo:
        cPickle.dump(object, pickleFo)


def loadObjPickleFile(filename):
    """
    Load/create a pickled object from a pickle file.

    filename:    Name of pickle file (string).

    Returns:     Reconstructed object (<object>).
    """
    with open(filename, "r") as pickleFo:
        return cPickle.load(pickleFo)

def genFileKey(diskId,
               fileId,
               fileVersion):
    """
    Generate a unique key identifying a file.

    diskId:         Disk ID (string).

    fileId:         File ID (string).

    fileVersion:    File Version (integer).

    Returns:        File key (string).
    """
    if (diskId):
        return str("%s_%s_%s" % (diskId, fileId, str(fileVersion)))
    else:
        return str("%s_%s" % (fileId, str(fileVersion)))


def trueArchiveProxySrv(cfgObj):
    """
    Return 1 if an NG/AMS Server is configured as a 'TrueT Archive Proxy
    Server'. I.e., no local archiving will take place, all Archive Requests
    received, will be forwarded to the sub-nodes specified.

    The exact criterias for classifying a node as a True Archive Proxy Server
    are as follows:

      - No Storage Sets are defined.
      - All Streams definition have a set of NAUs defined.

    cfgObj:   Instance of NG/AMS Configuration Object (ngamsConfig).

    Returns:   1 if the server is a True Archive Proxy Server (integer/0|1).
    """
    trueArchProxySrv = 1
    if (cfgObj.getStorageSetList() != []):
        trueArchProxySrv = 0
    else:
        for streamObj in cfgObj.getStreamList():
            if (streamObj.getStorageSetIdList() != []):
                trueArchProxySrv = 0
                break
            elif (streamObj.getHostIdList() == []):
                trueArchProxySrv = 0
                break
    return trueArchProxySrv


def logicalStrListSort(strList):
    """
    Sort a list of strings, such that strings in the list that might be
    lexigraphically smaller than other, but logically larger, are found
    in the end of the list. E.g.:

       ['3','11','1','10','2']

    - becomes:

      ['1','2','3','10','11']

    - end not:

      ['1','10,'11','2','3']

    Returns:   Sorted list (list).
    """
    maxLen = max(map(len, strList))
    estretched_strings = [(maxLen - len(s)) * " " + s for s in strList]
    estretched_strings.sort()
    return estretched_strings

# EOF
