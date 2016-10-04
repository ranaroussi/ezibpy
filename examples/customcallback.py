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

# define custom callback
def ibCallback(caller, msg, **kwargs):
    if caller == "handleOrders":
        order = ibConn.orders[msg.orderId]
        if order["status"] == "FILLED":
            print(">>> ORDER FILLED")

# initialize ezIBpy
ibConn = ezibpy.ezIBpy()
ibConn.connect(clientId=100, host="localhost", port=4001)

# assign the custom callback
ibConn.ibCallback = ibCallback

# create a contract
contract = ibConn.createStockContract("AAPL")

# create & place order
order = ibConn.createOrder(quantity=100)
orderId = ibConn.placeOrder(contract, order)

# let order fill
time.sleep(3)

# see the positions
print("Positions")
print(ibConn.positions)

# disconnect
ibConn.disconnect()
