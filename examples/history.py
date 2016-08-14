#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# ezIBpy: Pythonic Wrapper for IbPy
# https://github.com/ranaroussi/ezibpy
#
# Copyright 2015 Ran Aroussi
#
# Licensed under the GNU Lesser General Public License, v3.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.gnu.org/licenses/lgpl-3.0.en.html
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ezibpy
import time

# initialize ezIBpy
ibConn = ezibpy.ezIBpy()
ibConn.connect(clientId=100, host="localhost", port=4001)

# create a contract
contract = ibConn.createStockContract("AAPL")

# request 30 days of 1 minute data and save it to ~/Desktop
ibConn.requestHistoricalData(resolution="1 min", lookback="2 D", csv_path='~/Desktop/')

# wait until stopped using Ctrl-c
try:
    while True:
        time.sleep(1)

except (KeyboardInterrupt, SystemExit):
    # cancel request & disconnect
    ibConn.cancelHistoricalData()
    ibConn.disconnect()
