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

# connect to IB (7496/7497 = TWS, 4001 = IBGateway)
ibConn.connect(clientId=100, host="localhost", port=4001)

# create some contracts using dedicated methods
put  = ibConn.createOptionContract("AAPL", expiry="20161021", strike=117.0, otype="PUT")
call = ibConn.createOptionContract("AAPL", expiry="20161021", strike=117.0, otype="CALL")

# request market data for all created contracts
ibConn.requestMarketData()

# wait 30 seconds
time.sleep(30)

# print market data
print("Options Data")
print(ibConn.optionsData)

# cancel market data request & disconnect
ibConn.cancelMarketData()
ibConn.disconnect()
