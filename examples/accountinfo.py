#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# ezIBpy: Pythonic Wrapper for Troy Melhase's IbPy
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

# subscribe to account/position updates
ibConn.requestPositionUpdates(subscribe=True)
ibConn.requestAccountUpdates(subscribe=True)

# wait 30 seconds
time.sleep(30)

# available variables (auto-updating)
print("Account Information")
print(ibConn.account)

print("Positions")
print(ibConn.positions)

print("Portfolio")
print(ibConn.portfolio)

print("Contracts")
print(ibConn.contracts)

print("Orders (by TickId)")
print(ibConn.orders)

print("Orders (by Symbol)")
print(ibConn.symbol_orders)

# subscribe to account/position updates
ibConn.requestPositionUpdates(subscribe=False)
ibConn.requestAccountUpdates(subscribe=False)

# disconnect
ibConn.disconnect()
