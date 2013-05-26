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
# Who                   When             What
# -----------------   ----------      ------------
# chen.wu@icrar.org  26/May/2013        Created

"""
This module builds the NGAS MapReduce job for the MWA RTS system running
on a cluster of NGAS servers (e.g. iVEC Fornax)

To implement this module, knowledge of MWA and RTS is hardcoded. So if you want
to have another pipeline (e.g. CASA for VLA), write your own based on the generic MRTask 
framework in ngamsJobProtocol.py
"""

import threading

from ngamsJobProtocol import *

class RTSJob(MapReduceTask):
    """
    A job submitted by an MWA scientist to do the RTS imaging pipeline
    It is the top level of the RTS MRTask tree
    """
    def __init__(self, jobId, rtsParam):
        """
        Constructor
        
        JobId:    (string) identifier uniquely identify this RTSJob (e.g. RTS-cwu-2013-05-29H05:04:03.456)
        rtsParam:    RTS job parameters (class RTSJobParam)
        """
        MapReduceTask.__init__(self, jobId)
        self.__completedObsTasks = 0
        self.__buildRTSTasks(rtsParam)
    
    def __buildRTSTasks(self, rtsParam):
        if (rtsParam.obsList == None or len(rtsParam.obsList) == 0):
            errMsg = 'No observation numbers found in this RTS Job'
            raise Exception, errMsg
        
        num_obs = len(rtsParam.obsList)
        fileIds = []
        for j in range(num_obs):
            obsTask = ObsTask(rtsParam.obsList[j], rtsParam)
            self.addMapper(obsTask)
            
            for k in range(rtsParam.num_subband):
                # TODO - Get the file ids using functions in ngamsJobLib.py
                # fileIds = []
                corrTask = CorrTask(str(k + 1), fileIds, rtsParam)
                obsTask.addMapper(corrTask)
            
            obsTask.setReducer(obsTask) # set reducer to the obstask itself
        
        self.setReducer(self) # set reducer to the jobtask itself
    def combine(self, mapOutput):
        """
        TODO - this should be thread safe
        """
        self.__completedObsTasks += 1
    
    def reduce(self):
        """
        Return urls of each tar file, each of which corresponds to an observation's images
        """
        # TODO - define a 'response info' class to hold all the result information
        pass

class ObsTask(MapReduceTask):
    """
    MWA Observation, the second level of the RTS MRTask tree
    Thus, a RTSJob consists of multiple ObsTasks
    """
    def __init__(self, obsNum, rtsParam):
        """
        Constructor
        
        obsNum:    (string) observation number/id, i.e. the GPS time of each MWA observation
        rtsParam:    RTS job parameters (class RTSJobParam)
        """
        MapReduceTask.__init__(self, str(obsNum)) #in case caller still passes in integer
        self.__completedCorrTasks = 0
        self.__rtsParam = rtsParam
    
    def combine(self, mapOutput):
        """
        TODO - this should be thread safe
        """
        self.__completedCorrTasks += 1
    
    def reduce(self):
        """
        Return results of each correlator, each of which corresponds to images of a subband
        """
        # TODO - define a 'response info' class to hold all the result information
        pass

class CorrTask(MapReduceTask):
    """
    MWA Correlator task, the third level of the RTS MRTask tree
    It is where actual execution happens, and an ObsTask consists of 
    multiple CorrTasks
    Each CorrTask processes all files generated by that
    correlator 
    """
    def __init__(self, corrId, fileIds, rtsParam):
        """
        Constructor
        
        corrId:    (string) Correlator identifier (e.g. 1, 2, ... , 24)
        fileIds:   (list) A list of file ids (string) to be processed by this correlator task
        rtsParam:    RTS job parameters (class RTSJobParam)
        
        """
        MapReduceTask.__init__(self, str(corrId))
        self.__fileIds = fileIds
        self.__rtsParam = rtsParam
    
    def map(self, mapInput = None):
        """
        1. Check each file's location
        2. Stage file from Cortex if necessary
        3. Run RTS executable and archive images back to an NGAS server
        Part 3 is running on remote servers
        Both Part 2 and 3 are asynchronously invoked
        """
        #TODO - deal with timeout!
        pass

class RTSJobParam:
    """
    A class contains essential/optional parameters to 
    run the RTS pipeline
    """
    def __init__(self):
        """
        Constructor
        Set default values to all parameters
        """
        self.obsList = [] # a list of observation numbers
        self.time_resolution = 0.5
        self.fine_channel = 40 # KHz
        self.num_subband = 24 # should be the same as coarse channel
        self.tile = '128T'
        #RTS template prefix (optional, string)
        self.rts_tplpf = '/scratch/astronomy556/MWA/RTS/utils/templates/RTS_template_'
        #RTS template suffix
        self.rts_tplsf = '.in'
        
        #RTS template names for this processing (optional, string - comma separated aliases, e.g.
        #drift,regrid,snapshots, default = 'regrid'). Each name will be concatenated with 
        #rts-tpl-pf and rts-tpl-sf to form the complete template file path, 
        #e.g. /scratch/astronomy556/MWA/RTS/utils/templates/RTS_template_regrid.in
        
        self.rts_tpl_name = 'regrid'
    