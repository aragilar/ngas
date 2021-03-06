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
# "@(#) $Id: ngamsHelpCmdTest.py,v 1.4 2008/08/19 20:51:50 jknudstr Exp $"
#
# Who       When        What
# --------  ----------  -------------------------------------------------------
# jknudstr  18/11/2003  Created
#
import contextlib

from ngamsLib import ngamsHttpUtils
from ..ngamsTestLib import ngamsTestSuite


class ngamsHelpCmdTest(ngamsTestSuite):
    """Tests for the HELP command"""

    def test_help_online(self):
        self._test_help()

    def test_help_offline(self):
        self._test_help()

    def _test_help(self):
        self.prepExtSrv()
        resp = ngamsHttpUtils.httpGet('localhost', 8888, 'HELP')
        with contextlib.closing(resp):
            self.assertEqual(resp.status, 308)
            self.assertEqual(resp.getheader('location'), 'https://ngas.readthedocs.io')