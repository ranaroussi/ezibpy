#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# ezIBpy: a Pythonic Client for Interactive Brokers API
# https://github.com/ranaroussi/ezibpy
#
# Copyright 2015-2019 Ran Aroussi
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import atexit
import os
import time
import logging
import sys

from datetime import datetime
from pandas import DataFrame, concat as pd_concat
from stat import S_IWRITE

from ib.opt import Connection
from ib.ext.Contract import Contract
from ib.ext.Order import Order
from ib.ext.ComboLeg import ComboLeg

# from ibapi.connection import Connection
# from ibapi.contract import Contract, ComboLeg
# from ibapi.order import Order

from .utils import (
    dataTypes, createLogger, local_to_utc
)

import copy

# =============================================
# check min, python version
if sys.version_info < (3, 4):
    raise SystemError("ezIBPy requires Python version >= 3.4")
# =============================================

# ---------------------------------------------
createLogger('ezibpy')
# ---------------------------------------------


class ezIBpy():

    # trailch = False  # (used for debugging)

    # -----------------------------------------
    @staticmethod
    def roundClosestValid(val, res=0.01, decimals=None):
        if val is None:
            return None
        """ round to closest resolution """
        if decimals is None and "." in str(res):
            decimals = len(str(res).split('.')[1])

        return round(round(val / res) * res, decimals)

    # -----------------------------------------
    # https://www.interactivebrokers.com/en/software/api/apiguide/java/java_eclientsocket_methods.htm
    def __init__(self):
        """Initialize a new ezIBpy object."""
        self.clientId  = 1
        self.port      = 4001  # 7496/7497 = TWS, 4001 = IBGateway
        self.host      = "localhost"
        self.ibConn    = None
        self.connected = False

        self.time        = 0
        self.commission  = 0
        self.orderId     = int(time.time()) - 1553126400  # default
        self.default_account = None

        # auto-construct for every contract/order
        self.tickerIds     = {0: "SYMBOL"}
        self.contracts     = {}
        self.orders        = {}
        self.account_orders= {}
        self.account_symbols_orders= {}
        self.symbol_orders = {}

        self._accounts     = {}
        self._positions    = {}
        self._portfolios   = {}
        self._contract_details = {}  # multiple expiry/strike/side contracts

        self.contract_details  = {}
        self.localSymbolExpiry = {}

        # do not reconnect if diconnected by user
        # only try and reconnect if disconnected by network/other issues
        self._disconnected_by_user = False

        # -------------------------------------
        self.log = logging.getLogger('ezibpy')  # get logger
        # -------------------------------------

        # holds market data
        tickDF = DataFrame({
            "datetime": [0], "bid": [0], "bidsize": [0],
            "ask": [0], "asksize": [0], "last": [0], "lastsize": [0]
        })
        tickDF.set_index('datetime', inplace=True)
        self.marketData = {0: tickDF}  # idx = tickerId

        # holds orderbook data
        l2DF = DataFrame(index=range(5), data={
            "bid": 0, "bidsize": 0,
            "ask": 0, "asksize": 0
        })
        self.marketDepthData = {0: l2DF}  # idx = tickerId

        # trailing stops
        self.trailingStops = {}
        # "tickerId" = {
        #     orderId: ...
        #     lastPrice: ...
        #     trailPercent: ...
        #     trailAmount: ...
        #     quantity: ...
        # }

        # triggerable trailing stops
        self.triggerableTrailingStops = {}
        # "tickerId" = {
        #     parentId: ...
        #     stopOrderId: ...
        #     triggerPrice: ...
        #     trailPercent: ...
        #     trailAmount: ...
        #     quantity: ...
        # }

        # holds options data
        optionsDF = DataFrame({
            "datetime": [0], "oi": [0], "volume": [0], "underlying": [0], "iv": [0],
            "bid": [0], "bidsize": [0], "ask": [0], "asksize": [0], "last": [0], "lastsize": [0],
            # opt field
            "price": [0], "dividend": [0], "imp_vol": [0], "delta": [0],
            "gamma": [0], "vega": [0], "theta": [0],
            "last_price": [0], "last_dividend": [0], "last_imp_vol": [0], "last_delta": [0],
            "last_gamma": [0], "last_vega": [0], "last_theta": [0],
            "bid_price": [0], "bid_dividend": [0], "bid_imp_vol": [0], "bid_delta": [0],
            "bid_gamma": [0], "bid_vega": [0], "bid_theta": [0],
            "ask_price": [0], "ask_dividend": [0], "ask_imp_vol": [0], "ask_delta": [0],
            "ask_gamma": [0], "ask_vega": [0], "ask_theta": [0],
        })
        optionsDF.set_index('datetime', inplace=True)
        self.optionsData = {0: optionsDF}  # idx = tickerId

        # historical data contrainer
        self.historicalData = {}  # idx = symbol
        self.utc_history = False

        # register exit
        atexit.register(self.disconnect)

        # fire connected/disconnected callbacks/errors once per event
        self.connection_tracking = {
            "connected": False,
            "disconnected": False,
            "errors": []
        }

    # -----------------------------------------
    def log_msg(self, title, msg):
        # log handler msg
        logmsg = copy.copy(msg)
        if hasattr(logmsg, "contract"):
            logmsg.contract = self.contractString(logmsg.contract)
        self.log.info("[" + str(title).upper() + "]: %s", str(logmsg))

    # -----------------------------------------
    def connect(self, clientId=0, host="localhost", port=4001, account=None):
        """ Establish connection to TWS/IBGW """
        if account is not None:
            self.default_account = account
        self.clientId = clientId
        self.host = host
        self.port = port
        self.ibConn = Connection.create(
            host=self.host,
            port=int(self.port),
            clientId=self.clientId
        )

        # Assign server messages handling function.
        self.ibConn.registerAll(self.handleServerEvents)

        # connect
        self.log.info("[CONNECTING TO IB]")
        self.ibConn.connect()

        # get server time
        self.getServerTime()

        # subscribe to position and account changes
        self.subscribeAccount = False
        self.requestAccountUpdates(subscribe=True)

        self.subscribePositions = False
        self.requestPositionUpdates(subscribe=True)

        # load working orders
        self.requestOpenOrders()

        # force refresh of orderId upon connect
        self.handleNextValidId(self.orderId)

        self._disconnected_by_user = False
        time.sleep(1)

    # -----------------------------------------
    def disconnect(self):
        """ Disconnect from TWS/IBGW """
        if self.ibConn is not None:
            self.log.info("[DISCONNECT FROM IB]")
            self.ibConn.disconnect()
            self._disconnected_by_user = True

    # -----------------------------------------
    def reconnect(self):
        while not self.connected:
            self.connect(self.clientId, self.host, self.port)
            time.sleep(1)

    # -----------------------------------------
    def getServerTime(self):
        """ get the current time on IB """
        self.ibConn.reqCurrentTime()

    # -----------------------------------------
    @staticmethod
    def contract_to_tuple(contract):
        return (contract.m_symbol, contract.m_secType,
                contract.m_exchange, contract.m_currency, contract.m_expiry,
                contract.m_strike, contract.m_right)

    # -----------------------------------------
    def registerContract(self, contract):
        """ used for when callback receives a contract
        that isn't found in local database """

        if contract.m_exchange == "":
            return

        """
        if contract not in self.contracts.values():
            contract_tuple = self.contract_to_tuple(contract)
            self.createContract(contract_tuple)

        if self.tickerId(contract) not in self.contracts.keys():
            contract_tuple = self.contract_to_tuple(contract)
            self.createContract(contract_tuple)
        """

        if self.getConId(contract) == 0:
            contract_tuple = self.contract_to_tuple(contract)
            self.createContract(contract_tuple)

    # -----------------------------------------
    # Start event handlers
    # -----------------------------------------
    def handleErrorEvents(self, msg):
        """ logs error messages """
        # https://www.interactivebrokers.com/en/software/api/apiguide/tables/api_message_codes.htm
        if msg.errorCode is not None and msg.errorCode != -1 and \
                msg.errorCode not in dataTypes["BENIGN_ERROR_CODES"]:

            log = True

            # log disconnect errors only once
            if msg.errorCode in dataTypes["DISCONNECT_ERROR_CODES"]:
                log = False
                if msg.errorCode not in self.connection_tracking["errors"]:
                    self.connection_tracking["errors"].append(msg.errorCode)
                    log = True

            if log:
                self.log.error("[#%s] %s" % (msg.errorCode, msg.errorMsg))
                self.ibCallback(caller="handleError", msg=msg)

    # -----------------------------------------
    def handleServerEvents(self, msg):
        """ dispatch msg to the right handler """

        self.log.debug('MSG %s', msg)
        self.handleConnectionState(msg)

        if msg.typeName == "error":
            self.handleErrorEvents(msg)

        elif msg.typeName == dataTypes["MSG_CURRENT_TIME"]:
            if self.time < msg.time:
                self.time = msg.time

        elif (msg.typeName == dataTypes["MSG_TYPE_MKT_DEPTH"] or
                msg.typeName == dataTypes["MSG_TYPE_MKT_DEPTH_L2"]):
            self.handleMarketDepth(msg)

        elif msg.typeName == dataTypes["MSG_TYPE_TICK_STRING"]:
            self.handleTickString(msg)

        elif msg.typeName == dataTypes["MSG_TYPE_TICK_PRICE"]:
            self.handleTickPrice(msg)

        elif msg.typeName == dataTypes["MSG_TYPE_TICK_GENERIC"]:
            self.handleTickGeneric(msg)

        elif msg.typeName == dataTypes["MSG_TYPE_TICK_SIZE"]:
            self.handleTickSize(msg)

        elif msg.typeName == dataTypes["MSG_TYPE_TICK_OPTION"]:
            self.handleTickOptionComputation(msg)

        elif (msg.typeName == dataTypes["MSG_TYPE_OPEN_ORDER"] or
                msg.typeName == dataTypes["MSG_TYPE_OPEN_ORDER_END"] or
                msg.typeName == dataTypes["MSG_TYPE_ORDER_STATUS"]):
            self.handleOrders(msg)

        elif msg.typeName == dataTypes["MSG_TYPE_HISTORICAL_DATA"]:
            self.handleHistoricalData(msg)

        elif msg.typeName == dataTypes["MSG_TYPE_ACCOUNT_UPDATES"]:
            self.handleAccount(msg)

        elif msg.typeName == dataTypes["MSG_TYPE_PORTFOLIO_UPDATES"]:
            self.handlePortfolio(msg)

        elif msg.typeName == dataTypes["MSG_TYPE_POSITION"]:
            self.handlePosition(msg)

        elif msg.typeName == dataTypes["MSG_TYPE_NEXT_ORDER_ID"]:
            self.handleNextValidId(msg.orderId)

        elif msg.typeName == dataTypes["MSG_CONNECTION_CLOSED"]:
            self.handleConnectionClosed(msg)

        # elif msg.typeName == dataTypes["MSG_TYPE_MANAGED_ACCOUNTS"]:
        #     self.accountCode = msg.accountsList

        elif msg.typeName == dataTypes["MSG_COMMISSION_REPORT"]:
            self.commission = msg.commissionReport.m_commission

        elif msg.typeName == dataTypes["MSG_CONTRACT_DETAILS"]:
            self.handleContractDetails(msg, end=False)

        elif msg.typeName == dataTypes["MSG_CONTRACT_DETAILS_END"]:
            self.handleContractDetails(msg, end=True)

        elif msg.typeName == dataTypes["MSG_TICK_SNAPSHOT_END"]:
            self.ibCallback(caller="handleTickSnapshotEnd", msg=msg)

        else:
            # log handler msg
            self.log_msg("server", msg)

    # -----------------------------------------
    # generic callback function - can be used externally
    # -----------------------------------------
    def ibCallback(self, caller, msg, **kwargs):
        pass

    # -----------------------------------------
    # Start admin handlers
    # -----------------------------------------
    def handleConnectionState(self, msg):
        """:Return: True if IBPy message `msg` indicates the connection is unavailable for any reason, else False."""
        self.connected = not (msg.typeName == "error" and
                              msg.errorCode in dataTypes["DISCONNECT_ERROR_CODES"])

        if self.connected:
            self.connection_tracking["errors"] = []
            self.connection_tracking["disconnected"] = False

            if msg.typeName == dataTypes["MSG_CURRENT_TIME"] and not self.connection_tracking["connected"]:
                self.log.info("[CONNECTION TO IB ESTABLISHED]")
                self.connection_tracking["connected"] = True
                self.ibCallback(caller="handleConnectionOpened", msg="<connectionOpened>")
        else:
            self.connection_tracking["connected"] = False

            if not self.connection_tracking["disconnected"]:
                self.connection_tracking["disconnected"] = True
                self.log.info("[CONNECTION TO IB LOST]")

    # -----------------------------------------
    def handleConnectionClosed(self, msg):
        self.connected = False
        self.ibCallback(caller="handleConnectionClosed", msg=msg)

        # retry to connect
        if not self._disconnected_by_user:
            self.reconnect()

    # -----------------------------------------
    def handleNextValidId(self, orderId):
        """
        handle nextValidId event
        https://www.interactivebrokers.com/en/software/api/apiguide/java/nextvalidid.htm
        """
        if orderId > self.orderId:
            self.orderId = orderId

    # -----------------------------------------
    def handleContractDetails(self, msg, end=False):
        """ handles contractDetails and contractDetailsEnd """

        if end:
            # mark as downloaded
            self._contract_details[msg.reqId]['downloaded'] = True

            # move details from temp to permanent collector
            self.contract_details[msg.reqId] = self._contract_details[msg.reqId]
            del self._contract_details[msg.reqId]

            # adjust fields if multi contract
            if len(self.contract_details[msg.reqId]["contracts"]) > 1:
                self.contract_details[msg.reqId]["m_contractMonth"] = ""
                # m_summary should hold closest expiration
                expirations = self.getExpirations(self.contracts[msg.reqId], expired=0)
                contract = self.contract_details[msg.reqId]["contracts"][-len(expirations)]
                self.contract_details[msg.reqId]["m_summary"] = vars(contract)
            else:
                self.contract_details[msg.reqId]["m_summary"] = vars(
                    self.contract_details[msg.reqId]["contracts"][0])

            # update local db with correct contractString
            for tid in self.contract_details:
                oldString = self.tickerIds[tid]
                newString = self.contractString(self.contract_details[tid]["contracts"][0])

                if len(self.contract_details[msg.reqId]["contracts"]) > 1:
                    self.tickerIds[tid] = newString
                    if newString != oldString:
                        if oldString in self._portfolios:
                            self._portfolios[newString] = self._portfolios[oldString]
                        if oldString in self._positions:
                            self._positions[newString] = self._positions[oldString]

            # fire callback
            self.ibCallback(caller="handleContractDetailsEnd", msg=msg)

            # exit
            return

        # continue...

        # collect data on all contract details
        # (including those with multiple expiry/strike/sides)
        details  = vars(msg.contractDetails)
        contract = details["m_summary"]

        if msg.reqId in self._contract_details:
            details['contracts'] = self._contract_details[msg.reqId]["contracts"]
        else:
            details['contracts'] = []

        details['contracts'].append(contract)
        details['downloaded'] = False
        self._contract_details[msg.reqId] = details

        # add details to local symbol list
        if contract.m_localSymbol not in self.localSymbolExpiry:
            self.localSymbolExpiry[contract.m_localSymbol] = details["m_contractMonth"]

        # add contract's multiple expiry/strike/sides to class collectors
        contractString = self.contractString(contract)
        tickerId = self.tickerId(contractString)
        self.contracts[tickerId] = contract

        # continue if this is a "multi" contract
        if tickerId == msg.reqId:
            self._contract_details[msg.reqId]["m_summary"] = vars(contract)
        else:
            # print("+++", tickerId, contractString)
            self.contract_details[tickerId] = details.copy()
            self.contract_details[tickerId]["m_summary"] = vars(contract)
            self.contract_details[tickerId]["contracts"] = [contract]

        # fire callback
        self.ibCallback(caller="handleContractDetails", msg=msg)

    # -----------------------------------------
    # Account handling
    # -----------------------------------------
    def handleAccount(self, msg):
        """
        handle account info update
        https://www.interactivebrokers.com/en/software/api/apiguide/java/updateaccountvalue.htm
        """

        # parse value
        try:
            msg.value = float(msg.value)
        except Exception:
            msg.value = msg.value
            if msg.value in ['true', 'false']:
                msg.value = (msg.value == 'true')

        try:
            # log handler msg
            self.log_msg("account", msg)

            # new account?
            if msg.accountName not in self._accounts.keys():
                self._accounts[msg.accountName] = {}

            # set value
            self._accounts[msg.accountName][msg.key] = msg.value

            # fire callback
            self.ibCallback(caller="handleAccount", msg=msg)
        except Exception:
            pass

    def _get_active_account(self, account):
        account = None if account == "" else None
        if account is None:
            if self.default_account is not None:
                return self.default_account
            elif len(self._accounts) > 0:
                return self.accountCodes[0]
        return account

    @property
    def accounts(self):
        return self._accounts

    @property
    def account(self):
        return self.getAccount()

    @property
    def accountCodes(self):
        return list(self._accounts.keys())

    @property
    def accountCode(self):
        return self.accountCodes[0]

    def getAccount(self, account=None):
        if len(self._accounts) == 0:
            return {}

        account = self._get_active_account(account)

        if account is None:
            if len(self._accounts) > 1:
                raise ValueError("Must specify account number as multiple accounts exists.")
            return self._accounts[list(self._accounts.keys())[0]]

        if account in self._accounts:
            return self._accounts[account]

        raise ValueError("Account %s not found in account list" % account)

    # -----------------------------------------
    # Position handling
    # -----------------------------------------
    def handlePosition(self, msg):
        """ handle positions changes """

        # log handler msg
        self.log_msg("position", msg)

        # contract identifier
        contract_tuple = self.contract_to_tuple(msg.contract)
        contractString = self.contractString(contract_tuple)

        # try creating the contract
        self.registerContract(msg.contract)

        # new account?
        if msg.account not in self._positions.keys():
            self._positions[msg.account] = {}

        # if msg.pos != 0 or contractString in self.contracts.keys():
        self._positions[msg.account][contractString] = {
            "symbol":        contractString,
            "position":      int(msg.pos),
            "avgCost":       float(msg.avgCost),
            "account":       msg.account
        }

        # fire callback
        self.ibCallback(caller="handlePosition", msg=msg)

    @property
    def positions(self):
        return self.getPositions()

    def getPositions(self, account=None):
        if len(self._positions) == 0:
            return {}

        account = self._get_active_account(account)

        if account is None:
            if len(self._positions) > 1:
                raise ValueError("Must specify account number as multiple accounts exists.")
            return self._positions[list(self._positions.keys())[0]]

        if account in self._positions:
            return self._positions[account]

        raise ValueError("Account %s not found in account list" % account)

    # -----------------------------------------
    # Portfolio handling
    # -----------------------------------------
    def handlePortfolio(self, msg):
        """ handle portfolio updates """

        # log handler msg
        self.log_msg("portfolio", msg)

        # contract identifier
        contract_tuple = self.contract_to_tuple(msg.contract)
        contractString = self.contractString(contract_tuple)

        # try creating the contract
        self.registerContract(msg.contract)

        # new account?
        if msg.accountName not in self._portfolios.keys():
            self._portfolios[msg.accountName] = {}

        self._portfolios[msg.accountName][contractString] = {
            "symbol":        contractString,
            "position":      int(msg.position),
            "marketPrice":   float(msg.marketPrice),
            "marketValue":   float(msg.marketValue),
            "averageCost":   float(msg.averageCost),
            "unrealizedPNL": float(msg.unrealizedPNL),
            "realizedPNL":   float(msg.realizedPNL),
            "totalPNL":      float(msg.realizedPNL) + float(msg.unrealizedPNL),
            "account":       msg.accountName
        }

        # fire callback
        self.ibCallback(caller="handlePortfolio", msg=msg)

    @property
    def portfolios(self):
        return self._portfolios

    @property
    def portfolio(self):
        return self.getPortfolio()

    def getPortfolio(self, account=None):
        if len(self._portfolios) == 0:
            return {}

        account = self._get_active_account(account)

        if account is None:
            if len(self._portfolios) > 1:
                raise ValueError("Must specify account number as multiple accounts exists.")
            return self._portfolios[list(self._portfolios.keys())[0]]

        if account in self._portfolios:
            return self._portfolios[account]

        raise ValueError("Account %s not found in account list" % account)

    # -----------------------------------------
    # Order handling
    # -----------------------------------------
    def handleOrders(self, msg):
        """ handle order open & status """
        """
        It is possible that orderStatus() may return duplicate messages.
        It is essential that you filter the message accordingly.
        """

        # log handler msg
        self.log_msg("order", msg)

        # get server time
        self.getServerTime()
        time.sleep(0.001)

        # we need to handle mutiple events for the same order status
        duplicateMessage = False

        # open order
        if msg.typeName == dataTypes["MSG_TYPE_OPEN_ORDER"]:
            # contract identifier
            contractString = self.contractString(msg.contract)

            order_account = None
            if msg.orderId in self.orders and self.orders[msg.orderId]["status"] == "SENT":
                order_account = self.orders[msg.orderId]["account"]
                try:
                    del self.orders[msg.orderId]
                except Exception:
                    pass
            order_account = self._get_active_account(order_account)

            if msg.orderId in self.orders:
                duplicateMessage = True
            else:
                self.orders[msg.orderId] = {
                    "id":       msg.orderId,
                    "symbol":   contractString,
                    "contract": msg.contract,
                    "order":    msg.order,
                    "quantity": msg.order.m_totalQuantity,
                    "action":   msg.order.m_action,
                    "status":   "OPENED",
                    "reason":   None,
                    "avgFillPrice": 0.,
                    "parentId": 0,
                    "attached": set(),
                    "time": datetime.fromtimestamp(int(self.time)),
                    "account": order_account
                }
                self._assgin_order_to_account(self.orders[msg.orderId])

        # order status
        elif msg.typeName == dataTypes["MSG_TYPE_ORDER_STATUS"]:
            if msg.orderId in self.orders and self.orders[msg.orderId]['status'] == msg.status.upper():
                duplicateMessage = True
            else:
                # remove cancelled orphan orders
                # if "CANCELLED" in msg.status.upper() and msg.parentId not in self.orders.keys():
                #     try: del self.orders[msg.orderId]
                #     except Exception: pass
                # # otherwise, update order status
                # else:
                self.orders[msg.orderId]['status'] = msg.status.upper()
                self.orders[msg.orderId]['reason'] = msg.whyHeld
                self.orders[msg.orderId]['avgFillPrice'] = float(msg.avgFillPrice)
                self.orders[msg.orderId]['parentId'] = int(msg.parentId)
                self.orders[msg.orderId]['time'] = datetime.fromtimestamp(int(self.time))

            # remove from orders? no! (keep log)
            # if msg.status.upper() == 'CANCELLED':
            #     del self.orders[msg.orderId]

            # attach sub-orders
            # if hasattr(msg, 'parentId'):
            parentId = self.orders[msg.orderId]['parentId']
            if parentId > 0 and parentId in self.orders:
                if 'attached' not in self.orders[parentId]:
                    self.orders[parentId]['attached'] = set()
                self.orders[parentId]['attached'].add(msg.orderId)

            # cancel orphan sub-orders
            if self.orders[msg.orderId]['status'] == "FILLED":
                order = self.orders[msg.orderId]
                positions = self.getPositions(order['account'])
                if (positions[order['symbol']] == 0):
                    for orderId in order['attached']:
                        self.cancelOrder(orderId)

        # fire callback
        if duplicateMessage is False:
            # group orders by symbol
            self.symbol_orders = self.group_orders("symbol")
            # group orders by accounts->symbol
            for accountCode in self.accountCodes:
                self.account_symbols_orders[accountCode] = self.group_orders(
                    "symbol", accountCode)
            self.ibCallback(caller="handleOrders", msg=msg)

    # -----------------------------------------
    def _assgin_order_to_account(self, order):
        # assign order to account_orders dict
        account_key = order["account"]
        if account_key == "":
            return
        # new account?
        if account_key not in self.account_orders.keys():
            self.account_orders[account_key] = {}
        self.account_orders[account_key][order['id']] = order

    # -----------------------------------------
    def getOrders(self, account=None):
        if len(self.account_orders) == 0:
            return {}

        account = self._get_active_account(account)

        if account is None:
            if len(self.account_orders) > 1:
                raise ValueError("Must specify account number as multiple accounts exists.")
            return self.account_orders[list(self.account_orders.keys())[0]]

        if account == "*":
            return self.orders

        if account in self.account_orders:
            return self.account_orders[account]

        raise ValueError("Account %s not found in account list" % account)

    # -----------------------------------------
    def group_orders(self, by="symbol", account=None):
        orders = {}
        collection = self.orders
        if account is not None:
            if account not in self.account_orders:
                self.account_orders[account] = {}
            collection = self.account_orders[account]

        for orderId in collection:
            order = collection[orderId]

            if order[by] not in orders.keys():
                orders[order[by]] = {}

            # try: del order["contract"]
            # except Exception: pass

            orders[order[by]][order['id']] = order

        return orders

    # -----------------------------------------
    # Start price handlers
    # -----------------------------------------
    def handleMarketDepth(self, msg):
        """
        https://www.interactivebrokers.com/en/software/api/apiguide/java/updatemktdepth.htm
        https://www.interactivebrokers.com/en/software/api/apiguide/java/updatemktdepthl2.htm
        """

        # make sure symbol exists
        if msg.tickerId not in self.marketDepthData.keys():
            self.marketDepthData[msg.tickerId] = self.marketDepthData[0].copy()

        # bid
        if msg.side == 1:
            self.marketDepthData[msg.tickerId].loc[msg.position, "bid"] = msg.price
            self.marketDepthData[msg.tickerId].loc[msg.position, "bidsize"] = msg.size

        # ask
        elif msg.side == 0:
            self.marketDepthData[msg.tickerId].loc[msg.position, "ask"] = msg.price
            self.marketDepthData[msg.tickerId].loc[msg.position, "asksize"] = msg.size

        """
        # bid/ask spread / vol diff
        self.marketDepthData[msg.tickerId].loc[msg.position, "spread"] = \
            self.marketDepthData[msg.tickerId].loc[msg.position, "ask"]-\
            self.marketDepthData[msg.tickerId].loc[msg.position, "bid"]

        self.marketDepthData[msg.tickerId].loc[msg.position, "spreadsize"] = \
            self.marketDepthData[msg.tickerId].loc[msg.position, "asksize"]-\
            self.marketDepthData[msg.tickerId].loc[msg.position, "bidsize"]
        """

        self.ibCallback(caller="handleMarketDepth", msg=msg)

    # -----------------------------------------
    def handleHistoricalData(self, msg):
        # self.log.debug("[HISTORY]: %s", msg)
        print('.', end="", flush=True)

        if msg.date[:8].lower() == 'finished':
            # print(self.historicalData)

            if self.utc_history:
                for sym in self.historicalData:
                    contractString = str(sym)
                    self.historicalData[contractString] = local_to_utc(self.historicalData[contractString])

            if self.csv_path is not None:
                for sym in self.historicalData:
                    contractString = str(sym)
                    self.log.info("[HISTORICAL DATA FOR %s DOWNLOADED]" % contractString)
                    self.historicalData[contractString].to_csv(
                        self.csv_path + contractString + '.csv'
                    )

            print('.')
            # fire callback
            self.ibCallback(caller="handleHistoricalData", msg=msg, completed=True)

        else:
            # create tick holder for ticker
            if len(msg.date) <= 8:  # daily
                ts = datetime.strptime(msg.date, dataTypes["DATE_FORMAT"])
                ts = ts.strftime(dataTypes["DATE_FORMAT_HISTORY"])
            else:
                ts = datetime.fromtimestamp(int(msg.date))
                ts = ts.strftime(dataTypes["DATE_TIME_FORMAT_LONG"])

            hist_row = DataFrame(index=['datetime'], data={
                "datetime": ts, "O": msg.open, "H": msg.high,
                "L": msg.low, "C": msg.close, "V": msg.volume,
                "OI": msg.count, "WAP": msg.WAP})
            hist_row.set_index('datetime', inplace=True)

            symbol = self.tickerSymbol(msg.reqId)
            if symbol not in self.historicalData.keys():
                self.historicalData[symbol] = hist_row
            else:
                self.historicalData[symbol] = self.historicalData[symbol].append(hist_row)

            # fire callback
            self.ibCallback(caller="handleHistoricalData", msg=msg, completed=False)

    # -----------------------------------------
    def handleTickGeneric(self, msg):
        """
        holds latest tick bid/ask/last price
        """

        df2use = self.marketData
        if self.contracts[msg.tickerId].m_secType in ("OPT", "FOP"):
            df2use = self.optionsData

        # create tick holder for ticker
        if msg.tickerId not in df2use.keys():
            df2use[msg.tickerId] = df2use[0].copy()

        if msg.tickType == dataTypes["FIELD_OPTION_IMPLIED_VOL"]:
            df2use[msg.tickerId]['iv'] = round(float(msg.value), 2)

        # elif msg.tickType == dataTypes["FIELD_OPTION_HISTORICAL_VOL"]:
        #     df2use[msg.tickerId]['historical_iv'] = round(float(msg.value), 2)

        # fire callback
        self.ibCallback(caller="handleTickGeneric", msg=msg)

    # -----------------------------------------
    def handleTickPrice(self, msg):
        """
        holds latest tick bid/ask/last price
        """
        # self.log.debug("[TICK PRICE]: %s - %s", dataTypes["PRICE_TICKS"][msg.field], msg)
        # return

        if msg.price < 0:
            return

        df2use = self.marketData
        canAutoExecute = msg.canAutoExecute == 1
        if self.contracts[msg.tickerId].m_secType in ("OPT", "FOP"):
            df2use = self.optionsData
            canAutoExecute = True

        # create tick holder for ticker
        if msg.tickerId not in df2use.keys():
            df2use[msg.tickerId] = df2use[0].copy()

        # bid price
        if canAutoExecute and msg.field == dataTypes["FIELD_BID_PRICE"]:
            df2use[msg.tickerId]['bid'] = float(msg.price)
        # ask price
        elif canAutoExecute and msg.field == dataTypes["FIELD_ASK_PRICE"]:
            df2use[msg.tickerId]['ask'] = float(msg.price)
        # last price
        elif msg.field == dataTypes["FIELD_LAST_PRICE"]:
            df2use[msg.tickerId]['last'] = float(msg.price)

        # fire callback
        self.ibCallback(caller="handleTickPrice", msg=msg)

    # -----------------------------------------
    def handleTickSize(self, msg):
        """
        holds latest tick bid/ask/last size
        """

        if msg.size < 0:
            return

        df2use = self.marketData
        if self.contracts[msg.tickerId].m_secType in ("OPT", "FOP"):
            df2use = self.optionsData

        # create tick holder for ticker
        if msg.tickerId not in df2use.keys():
            df2use[msg.tickerId] = df2use[0].copy()

        # ---------------------
        # market data
        # ---------------------
        # bid size
        if msg.field == dataTypes["FIELD_BID_SIZE"]:
            df2use[msg.tickerId]['bidsize'] = int(msg.size)
        # ask size
        elif msg.field == dataTypes["FIELD_ASK_SIZE"]:
            df2use[msg.tickerId]['asksize'] = int(msg.size)
        # last size
        elif msg.field == dataTypes["FIELD_LAST_SIZE"]:
            df2use[msg.tickerId]['lastsize'] = int(msg.size)

        # ---------------------
        # options data
        # ---------------------
        # open interest
        elif msg.field == dataTypes["FIELD_OPEN_INTEREST"]:
            df2use[msg.tickerId]['oi'] = int(msg.size)

        elif msg.field == dataTypes["FIELD_OPTION_CALL_OPEN_INTEREST"] and \
                self.contracts[msg.tickerId].m_right == "CALL":
            df2use[msg.tickerId]['oi'] = int(msg.size)

        elif msg.field == dataTypes["FIELD_OPTION_PUT_OPEN_INTEREST"] and \
                self.contracts[msg.tickerId].m_right == "PUT":
            df2use[msg.tickerId]['oi'] = int(msg.size)

        # volume
        elif msg.field == dataTypes["FIELD_VOLUME"]:
            df2use[msg.tickerId]['volume'] = int(msg.size)

        elif msg.field == dataTypes["FIELD_OPTION_CALL_VOLUME"] and \
                self.contracts[msg.tickerId].m_right == "CALL":
            df2use[msg.tickerId]['volume'] = int(msg.size)

        elif msg.field == dataTypes["FIELD_OPTION_PUT_VOLUME"] and \
                self.contracts[msg.tickerId].m_right == "PUT":
            df2use[msg.tickerId]['volume'] = int(msg.size)

        # fire callback
        self.ibCallback(caller="handleTickSize", msg=msg)

    # -----------------------------------------
    def handleTickString(self, msg):
        """
        holds latest tick bid/ask/last timestamp
        """

        df2use = self.marketData
        if self.contracts[msg.tickerId].m_secType in ("OPT", "FOP"):
            df2use = self.optionsData

        # create tick holder for ticker
        if msg.tickerId not in df2use.keys():
            df2use[msg.tickerId] = df2use[0].copy()

        # update timestamp
        if msg.tickType == dataTypes["FIELD_LAST_TIMESTAMP"]:
            ts = datetime.fromtimestamp(int(msg.value)) \
                .strftime(dataTypes["DATE_TIME_FORMAT_LONG_MILLISECS"])
            df2use[msg.tickerId].index = [ts]
            # self.log.debug("[TICK TS]: %s", ts)

            # handle trailing stop orders
            if self.contracts[msg.tickerId].m_secType not in ("OPT", "FOP"):
                self.triggerTrailingStops(msg.tickerId)
                self.handleTrailingStops(msg.tickerId)

            # fire callback
            self.ibCallback(caller="handleTickString", msg=msg)

        elif (msg.tickType == dataTypes["FIELD_RTVOLUME"]):

            # log handler msg
            # self.log_msg("rtvol", msg)

            tick = dict(dataTypes["RTVOL_TICKS"])
            (tick['price'], tick['size'], tick['time'], tick['volume'],
                tick['wap'], tick['single']) = msg.value.split(';')

            try:
                tick['last']       = float(tick['price'])
                tick['lastsize']   = float(tick['size'])
                tick['volume']     = float(tick['volume'])
                tick['wap']        = float(tick['wap'])
                tick['single']     = tick['single'] == 'true'
                tick['instrument'] = self.tickerSymbol(msg.tickerId)

                # parse time
                s, ms = divmod(int(tick['time']), 1000)
                tick['time'] = '{}.{:03d}'.format(
                    time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(s)), ms)

                # add most recent bid/ask to "tick"
                tick['bid']     = df2use[msg.tickerId]['bid'][0]
                tick['bidsize'] = int(df2use[msg.tickerId]['bidsize'][0])
                tick['ask']     = df2use[msg.tickerId]['ask'][0]
                tick['asksize'] = int(df2use[msg.tickerId]['asksize'][0])

                # self.log.debug("%s: %s\n%s", tick['time'], self.tickerSymbol(msg.tickerId), tick)

                # fire callback
                self.ibCallback(caller="handleTickString", msg=msg, tick=tick)

            except Exception:
                pass

        else:
            # self.log.info("tickString-%s", msg)
            # fire callback
            self.ibCallback(caller="handleTickString", msg=msg)

        # print(msg)

    # -----------------------------------------
    def handleTickOptionComputation(self, msg):
        """
        holds latest option data timestamp
        only option price is kept at the moment
        https://www.interactivebrokers.com/en/software/api/apiguide/java/tickoptioncomputation.htm
        """
        def calc_generic_val(data, field):
            last_val = data['last_' + field].values[-1]
            bid_val  = data['bid_' + field].values[-1]
            ask_val  = data['ask_' + field].values[-1]
            bid_ask_val = last_val
            if bid_val != 0 and ask_val != 0:
                bid_ask_val = (bid_val + ask_val) / 2
            return max([last_val, bid_ask_val])

        def valid_val(val):
            return float(val) if val < 1000000000 else None

        # create tick holder for ticker
        if msg.tickerId not in self.optionsData.keys():
            self.optionsData[msg.tickerId] = self.optionsData[0].copy()

        col_prepend = ""
        if msg.field == "FIELD_BID_OPTION_COMPUTATION":
            col_prepend = "bid_"
        elif msg.field == "FIELD_ASK_OPTION_COMPUTATION":
            col_prepend = "ask_"
        elif msg.field == "FIELD_LAST_OPTION_COMPUTATION":
            col_prepend = "last_"

        # save side
        self.optionsData[msg.tickerId][col_prepend + 'imp_vol']  = valid_val(msg.impliedVol)
        self.optionsData[msg.tickerId][col_prepend + 'dividend'] = valid_val(msg.pvDividend)
        self.optionsData[msg.tickerId][col_prepend + 'delta'] = valid_val(msg.delta)
        self.optionsData[msg.tickerId][col_prepend + 'gamma'] = valid_val(msg.gamma)
        self.optionsData[msg.tickerId][col_prepend + 'vega'] = valid_val(msg.vega)
        self.optionsData[msg.tickerId][col_prepend + 'theta'] = valid_val(msg.theta)
        self.optionsData[msg.tickerId][col_prepend + 'price'] = valid_val(msg.optPrice)

        # save generic/mid
        data = self.optionsData[msg.tickerId]
        self.optionsData[msg.tickerId]['imp_vol'] = calc_generic_val(data, 'imp_vol')
        self.optionsData[msg.tickerId]['dividend'] = calc_generic_val(data, 'dividend')
        self.optionsData[msg.tickerId]['delta'] = calc_generic_val(data, 'delta')
        self.optionsData[msg.tickerId]['gamma'] = calc_generic_val(data, 'gamma')
        self.optionsData[msg.tickerId]['vega'] = calc_generic_val(data, 'vega')
        self.optionsData[msg.tickerId]['theta'] = calc_generic_val(data, 'theta')
        self.optionsData[msg.tickerId]['price'] = calc_generic_val(data, 'price')
        self.optionsData[msg.tickerId]['underlying'] = valid_val(msg.undPrice)

        # fire callback
        self.ibCallback(caller="handleTickOptionComputation", msg=msg)

    # -----------------------------------------
    # trailing stops
    # -----------------------------------------
    def createTriggerableTrailingStop(self, symbol, quantity=1,
            triggerPrice=0, trailPercent=100., trailAmount=0.,
            parentId=0, stopOrderId=None, targetOrderId=None,
            account=None, **kwargs):
        """
        adds order to triggerable list

        IMPORTANT! For trailing stop to work you'll need
            1. real time market data subscription for the tracked ticker
            2. the python/algo script to be kept alive
        """

        ticksize = self.contractDetails(symbol)["m_minTick"]

        self.triggerableTrailingStops[symbol] = {
            "parentId": parentId,
            "stopOrderId": stopOrderId,
            "targetOrderId": targetOrderId,
            "triggerPrice": triggerPrice,
            "trailAmount": abs(trailAmount),
            "trailPercent": abs(trailPercent),
            "quantity": quantity,
            "ticksize": ticksize,
            "account": self._get_active_account(account)
        }

        return self.triggerableTrailingStops[symbol]

    # -----------------------------------------
    def cancelTriggerableTrailingStop(self, symbol):
        """ cancel **pending** triggerable trailing stop """
        del self.triggerableTrailingStops[symbol]

    # -----------------------------------------
    def modifyTriggerableTrailingStop(self, symbol, quantity=1,
            triggerPrice=0, trailPercent=100., trailAmount=0.,
            parentId=0, stopOrderId=None, targetOrderId=None, **kwargs):

        params = {
            "symbol": symbol,
            "quantity": quantity,
            "triggerPrice": triggerPrice,
            "trailPercent": abs(trailPercent),
            "trailAmount": abs(trailAmount),
            "parentId": parentId,
            "stopOrderId": stopOrderId,
            "targetOrderId": targetOrderId,
        }

        if symbol in self.triggerableTrailingStops:
            original = self.triggerableTrailingStops[symbol]
            self.cancelTriggerableTrailingStop(symbol)
            params = {**original, **kwargs}

        return self.createTriggerableTrailingStop(**params)

    # -----------------------------------------
    def registerTrailingStop(self, tickerId, orderId=0, quantity=1,
            lastPrice=0, trailPercent=100., trailAmount=0., parentId=0, **kwargs):
        """ adds trailing stop to monitor list """

        ticksize = self.contractDetails(tickerId)["m_minTick"]

        trailingStop = self.trailingStops[tickerId] = {
            "orderId": orderId,
            "parentId": parentId,
            "lastPrice": lastPrice,
            "trailAmount": trailAmount,
            "trailPercent": trailPercent,
            "quantity": quantity,
            "ticksize": ticksize
        }

        return trailingStop

    # -----------------------------------------
    def modifyStopOrder(self, orderId, parentId, newStop, quantity,
                        transmit=True, stop_limit=False, account=None):
        """ modify stop order """
        if orderId in self.orders.keys():
            order = self.createStopOrder(
                quantity = quantity,
                parentId = parentId,
                stop     = newStop,
                stop_limit = stop_limit,
                trail    = False,
                transmit = transmit,
                account  = self._get_active_account(account)
            )
            return self.placeOrder(self.orders[orderId]['contract'], order, orderId)

        return None

    # -----------------------------------------
    def handleTrailingStops(self, tickerId):
        """ software-based trailing stop """

        # existing?
        if tickerId not in self.trailingStops.keys():
            return None

        # continue
        trailingStop   = self.trailingStops[tickerId]
        price          = self.marketData[tickerId]['last'][0]
        symbol         = self.tickerSymbol(tickerId)
        # contract       = self.contracts[tickerId]
        # contractString = self.contractString(contract)

        if self.default_account is None:
            self.default_account = list(self._positions.keys())[0]

        # filled / no positions?
        if (self._positions[self.default_account][symbol] == 0) | \
                (self.orders[trailingStop['orderId']]['status'] == "FILLED"):
            del self.trailingStops[tickerId]
            return None

        # continue...
        newStop  = trailingStop['lastPrice']
        ticksize = trailingStop['ticksize']

        # long
        if (trailingStop['quantity'] < 0) & (trailingStop['lastPrice'] < price):
            if abs(trailingStop['trailAmount']) >= 0:
                newStop = price - abs(trailingStop['trailAmount'])
            elif trailingStop['trailPercent'] >= 0:
                newStop = price - (price * (abs(trailingStop['trailPercent']) / 100))
        # short
        elif (trailingStop['quantity'] > 0) & (trailingStop['lastPrice'] > price):
            if abs(trailingStop['trailAmount']) >= 0:
                newStop = price + abs(trailingStop['trailAmount'])
            elif trailingStop['trailPercent'] >= 0:
                newStop = price + (price * (abs(trailingStop['trailPercent']) / 100))

        # valid newStop
        newStop = self.roundClosestValid(newStop, ticksize)

        # print("\n\n", trailingStop['lastPrice'], newStop, price, "\n\n")

        # no change?
        if newStop == trailingStop['lastPrice']:
            return None

        # submit order
        trailingStopOrderId = self.modifyStopOrder(
            orderId  = trailingStop['orderId'],
            parentId = trailingStop['parentId'],
            newStop  = newStop,
            quantity = trailingStop['quantity']
        )

        if trailingStopOrderId:
            self.trailingStops[tickerId]['lastPrice'] = price

        return trailingStopOrderId

    # -----------------------------------------
    def triggerTrailingStops(self, tickerId, **kwargs):
        """ trigger waiting trailing stops """
        # print('.')

        # get pricing data
        price  = self.marketData[tickerId]['last'][0]
        contract = self.contracts[tickerId]
        symbol = self.tickerSymbol(tickerId)

        # abort?
        if symbol not in self.triggerableTrailingStops.keys():
            return

        # # trigger the order (used for debugging)
        # if not self.trailch:
        #     self.triggerableTrailingStops[symbol]['triggerPrice'] = price
        #     self.trailch = True
        #     return

        # extract order data
        pendingOrder  = self.triggerableTrailingStops[symbol]
        parentId      = pendingOrder["parentId"]
        stopOrderId   = pendingOrder["stopOrderId"]
        targetOrderId = pendingOrder["targetOrderId"]
        triggerPrice  = pendingOrder["triggerPrice"]
        trailAmount   = pendingOrder["trailAmount"]
        trailPercent  = pendingOrder["trailPercent"]
        quantity      = pendingOrder["quantity"]
        ticksize      = pendingOrder["ticksize"]
        account       = pendingOrder["account"]

        # abort?
        if parentId not in self.orders.keys():
            del self.triggerableTrailingStops[symbol]
            return
        elif self.orders[parentId]["status"] != "FILLED":
            return

        # print(">>>>>>>", pendingOrder)
        # print(">>>>>>>", parentId)
        # print(">>>>>>>", self.orders)

        print("[TRAIL]", quantity, triggerPrice, price)

        if ((quantity > 0) & (triggerPrice >= price)) | (
            (quantity < 0) & (triggerPrice <= price)):
            # print('TRIGGER ***********')

            newStop = price
            if trailAmount > 0:
                if quantity > 0:
                    newStop += trailAmount
                else:
                    newStop -= trailAmount
            elif trailPercent > 0:
                if quantity > 0:
                    newStop += price * (trailPercent / 100)
                else:
                    newStop -= price * (trailPercent / 100)
            else:
                del self.triggerableTrailingStops[symbol]
                return 0

            # print("------", stopOrderId , parentId, newStop , quantity, "------")

            # use valid newStop
            trailingStopOrderId = self.modifyStopOrder(
                orderId  = stopOrderId,
                parentId = parentId,
                newStop  = self.roundClosestValid(newStop, ticksize),
                quantity = quantity,
                account  = account
            )

            """
            @TODO : convert hard stop to trailing
            if trailAmount > 0:
                trailValue = self.roundClosestValid(abs(trailAmount), ticksize)
                trailType = 'amount'
            elif trailPercent > 0:
                trailValue = abs(trailPercent)
                trailType = 'percent'
            else:
                del self.triggerableTrailingStops[symbol]
                return

            trailingStopOrderId = self.createTrailingStopOrder(
                contract=contract,
                quantity=quantity,
                parentId=stopOrderId,
                trailType=trailType,
                trailValue=trailValue,
                stopTrigger=triggerPrice,
                account=account)
            """

            if trailingStopOrderId:
                # print(">>> TRAILING STOP TRIGGERED")
                del self.triggerableTrailingStops[symbol]

                # "delete" target and keep traling only
                if targetOrderId and targetOrderId in self.orders.keys():
                    # self.cancelOrder(targetOrderId)
                    targetOrder = self.orders[targetOrderId]['order']
                    targetOrder.m_auxPrice = 0 if quantity < 0 else 1000000
                    self.placeOrder(contract, order, targetOrderId,
                                    targetOrder.m_account)

                # register trailing stop
                tickerId = self.tickerId(symbol)
                self.registerTrailingStop(
                    tickerId = tickerId,
                    parentId = parentId,
                    orderId = stopOrderId,
                    lastPrice = price,
                    trailAmount = trailAmount,
                    trailPercent = trailPercent,
                    quantity = quantity,
                    ticksize = ticksize
                )

                return trailingStopOrderId

        return None

    # -----------------------------------------
    # tickerId/Symbols constructors
    # -----------------------------------------
    def tickerId(self, contract_identifier):
        """
        returns the tickerId for the symbol or
        sets one if it doesn't exits
        """
        # contract passed instead of symbol?
        symbol = contract_identifier
        if isinstance(symbol, Contract):
            symbol = self.contractString(symbol)

        for tickerId in self.tickerIds:
            if symbol == self.tickerIds[tickerId]:
                return tickerId
        else:
            tickerId = len(self.tickerIds)
            self.tickerIds[tickerId] = symbol
            return tickerId

    # -----------------------------------------
    def tickerSymbol(self, tickerId):
        """ returns the symbol of a tickerId """
        try:
            return self.tickerIds[tickerId]
        except Exception:
            return ""

    # -----------------------------------------
    def contractString(self, contract, seperator="_"):
        """ returns string from contract tuple """

        localSymbol = ""
        contractTuple = contract

        if type(contract) != tuple:
            localSymbol = contract.m_localSymbol
            contractTuple = self.contract_to_tuple(contract)

        # build identifier
        try:
            if contractTuple[1] in ("OPT", "FOP"):
                # if contractTuple[5]*100 - int(contractTuple[5]*100):
                #     strike = contractTuple[5]
                # else:
                #     strike = "{0:.2f}".format(contractTuple[5])
                strike = '{:0>5d}'.format(int(contractTuple[5])) + \
                    format(contractTuple[5], '.3f').split('.')[1]

                contractString = (contractTuple[0] + str(contractTuple[4]) +
                                  contractTuple[6][0] + strike, contractTuple[1])
                                  # contractTuple[6], str(strike).replace(".", ""))

            elif contractTuple[1] == "FUT":
                exp = ' ' # default

                # round expiry day to expiry month
                if localSymbol != "":
                    # exp = localSymbol[2:3]+str(contractTuple[4][:4])
                    exp = localSymbol[2:3] + self.localSymbolExpiry[localSymbol][:4]

                if ' ' in exp:
                    exp = str(contractTuple[4])[:6]
                    exp = dataTypes["MONTH_CODES"][int(exp[4:6])] + str(int(exp[:4]))

                contractString = (contractTuple[0] + exp, contractTuple[1])

            elif contractTuple[1] == "CASH":
                contractString = (contractTuple[0] + contractTuple[3], contractTuple[1])

            else:  # STK
                contractString = (contractTuple[0], contractTuple[1])

            # construct string
            contractString = seperator.join(
                str(v) for v in contractString).replace(seperator + "STK", "")

        except Exception:
            contractString = contractTuple[0]

        return contractString.replace(" ", "_").upper()

    # -----------------------------------------
    def contractDetails(self, contract_identifier):
        """ returns string from contract tuple """

        if isinstance(contract_identifier, Contract):
            tickerId = self.tickerId(contract_identifier)
        else:
            if str(contract_identifier).isdigit():
                tickerId = contract_identifier
            else:
                tickerId = self.tickerId(contract_identifier)

        if tickerId in self.contract_details:
            return self.contract_details[tickerId]
        elif tickerId in self._contract_details:
            return self._contract_details[tickerId]

        # default values
        return {
            'm_category': None, 'm_contractMonth': '', 'downloaded': False, 'm_evMultiplier': 0,
            'm_evRule': None, 'm_industry': None, 'm_liquidHours': '', 'm_longName': '',
            'm_marketName': '', 'm_minTick': 0.01, 'm_orderTypes': '', 'm_priceMagnifier': 0,
            'm_subcategory': None, 'm_timeZoneId': '', 'm_tradingHours': '', 'm_underConId': 0,
            'm_validExchanges': 'SMART', 'contracts': [Contract()], 'm_summary': {
                'm_conId': 0, 'm_currency': 'USD', 'm_exchange': 'SMART', 'm_expiry': '',
                'm_includeExpired': False, 'm_localSymbol': '', 'm_multiplier': '',
                'm_primaryExch': None, 'm_right': None, 'm_secType': '',
                'm_strike': 0.0, 'm_symbol': '', 'm_tradingClass': '',
            }
        }

    # -----------------------------------------
    # contract constructors
    # -----------------------------------------
    def isMultiContract(self, contract):
        """ tells if is this contract has sub-contract with expiries/strikes/sides """
        if contract.m_secType == "FUT" and contract.m_expiry == "":
            return True

        if contract.m_secType in ["OPT", "FOP"] and \
                (contract.m_expiry == "" or contract.m_strike == "" or contract.m_right == ""):
            return True

        tickerId = self.tickerId(contract)
        if tickerId in self.contract_details and \
                len(self.contract_details[tickerId]["contracts"]) > 1:
            return True

        return False

    # -----------------------------------------
    def createContract(self, contractTuple, **kwargs):
        # https://www.interactivebrokers.com/en/software/api/apiguide/java/contract.htm

        contractString = self.contractString(contractTuple)
        # print(contractString)

        # get (or set if not set) the tickerId for this symbol
        # tickerId = self.tickerId(contractTuple[0])
        tickerId = self.tickerId(contractString)

        # construct contract
        exchange = contractTuple[2]
        if exchange is not None:
            exchange = exchange.upper().replace("NASDAQ", "ISLAND")
        newContract = Contract()
        newContract.m_symbol   = contractTuple[0]
        newContract.m_secType  = contractTuple[1]
        newContract.m_exchange = exchange
        newContract.m_currency = contractTuple[3]
        newContract.m_expiry   = contractTuple[4]
        newContract.m_strike   = contractTuple[5]
        newContract.m_right    = contractTuple[6]

        if len(contractTuple) == 8:
            newContract.m_multiplier = contractTuple[7]

        # include expired (needed for historical data)
        newContract.m_includeExpired = (newContract.m_secType in ["FUT", "OPT", "FOP"])

        if "comboLegs" in kwargs:
            newContract.m_comboLegs = kwargs["comboLegs"]

        # add contract to pool
        self.contracts[tickerId] = newContract

        # request contract details
        if "comboLegs" not in kwargs:
            try:
                self.requestContractDetails(newContract)
                time.sleep(1.5 if self.isMultiContract(newContract) else 0.5)
            except KeyboardInterrupt:
                sys.exit()

        # print(vars(newContract))
        # print('Contract Values:%s,%s,%s,%s,%s,%s,%s:' % contractTuple)
        return newContract

    # shortcuts
    # -----------------------------------------
    def createStockContract(self, symbol, currency="USD", exchange="SMART"):
        contract_tuple = (symbol, "STK", exchange, currency, "", 0.0, "")
        contract = self.createContract(contract_tuple)
        return contract

    # -----------------------------------------
    def createFuturesContract(self, symbol, currency="USD", expiry=None, exchange="GLOBEX"):
        expiry = [expiry] if not isinstance(expiry, list) else expiry

        contracts = []
        for fut_expiry in expiry:
            contract_tuple = (symbol, "FUT", exchange, currency, fut_expiry, 0.0, "")
            contract = self.createContract(contract_tuple)
            contracts.append(contract)

        return contracts[0] if len(contracts) == 1 else contracts

    # -----------------------------------------
    def createOptionContract(self, symbol, expiry=None, strike=0.0, otype="CALL",
            currency="USD", secType="OPT", exchange="SMART"):

        # secType = OPT (Option) / FOP (Options on Futures)
        expiry = [expiry] if not isinstance(expiry, list) else expiry
        strike = [strike] if not isinstance(strike, list) else strike
        otype  = [otype] if not isinstance(otype, list) else otype

        contracts = []
        for opt_expiry in expiry:
            for opt_strike in strike:
                for opt_otype in otype:
                    contract_tuple = (symbol, secType, exchange, currency,
                                      opt_expiry, opt_strike, opt_otype)
                    contract = self.createContract(contract_tuple)
                    contracts.append(contract)

        return contracts[0] if len(contracts) == 1 else contracts

    # -----------------------------------------
    def createCashContract(self, symbol, currency="USD", exchange="IDEALPRO"):
        """ Used for FX, etc:
        createCashContract("EUR", currency="USD")
        """
        contract_tuple = (symbol, "CASH", exchange, currency, "", 0.0, "")
        contract = self.createContract(contract_tuple)
        return contract

    # -----------------------------------------
    def createIndexContract(self, symbol, currency="USD", exchange="CBOE"):
        """ Used for indexes (SPX, DJX, ...) """
        contract_tuple = (symbol, "IND", exchange, currency, "", 0.0, "")
        contract = self.createContract(contract_tuple)
        return contract

    # -----------------------------------------
    # order constructors
    # -----------------------------------------
    def createOrder(self, quantity, price=0., stop=0., tif="DAY",
            fillorkill=False, iceberg=False, transmit=True, rth=False,
            account=None, **kwargs):

        # https://www.interactivebrokers.com/en/software/api/apiguide/java/order.htm
        order = Order()
        order.m_clientId = self.clientId
        order.m_action = dataTypes["ORDER_ACTION_BUY"] if quantity > 0 else dataTypes["ORDER_ACTION_SELL"]
        order.m_totalQuantity = abs(int(quantity))

        if "orderType" in kwargs:
            order.m_orderType = kwargs["orderType"]
            if kwargs["orderType"] == "MOO":
                order.m_orderType = "MKT"
                tif = "OPG"
            elif kwargs["orderType"] == "LOO":
                order.m_orderType = "LMT"
                tif = "OPG"
        else:
            order.m_orderType = dataTypes["ORDER_TYPE_MARKET"] if price == 0 else dataTypes["ORDER_TYPE_LIMIT"]

        order.m_lmtPrice   = price  # LMT  Price
        order.m_auxPrice   = kwargs["auxPrice"] if "auxPrice" in kwargs else stop
        order.m_tif        = tif.upper()   # DAY, GTC, IOC, GTD, OPG, ...
        order.m_allOrNone  = int(fillorkill)
        order.hidden       = iceberg
        order.m_transmit   = int(transmit)
        order.m_outsideRth = int(rth == False and tif.upper() != "OPG")

        # send to specific account?
        account = self._get_active_account(account)
        if account is not None:
            order.m_account = account

        # The publicly disclosed order size for Iceberg orders
        if iceberg & ("blockOrder" in kwargs):
            order.m_blockOrder = kwargs["m_blockOrder"]

        # The percent offset amount for relative orders.
        if "percentOffset" in kwargs:
            order.m_percentOffset = kwargs["percentOffset"]

        # The order ID of the parent order,
        # used for bracket and auto trailing stop orders.
        if "parentId" in kwargs:
            order.m_parentId = kwargs["parentId"]

        # oca group (Order Cancels All)
        # used for bracket and auto trailing stop orders.
        if "ocaGroup" in kwargs:
            order.m_ocaGroup = kwargs["ocaGroup"]
            if "ocaType" in kwargs:
                order.m_ocaType = kwargs["ocaType"]
            else:
                order.m_ocaType = 2  # proportionately reduced size of remaining orders

        # For TRAIL order
        if "trailingPercent" in kwargs:
            order.m_trailingPercent = kwargs["trailingPercent"]

        # For TRAILLIMIT orders only
        if "trailStopPrice" in kwargs:
            order.m_trailStopPrice = kwargs["trailStopPrice"]

        return order

    # -----------------------------------------
    def createTargetOrder(self, quantity, parentId=0,
            target=0., orderType=None, transmit=True, group=None, tif="DAY",
            rth=False, account=None):
        """ Creates TARGET order """
        params = {
            "quantity": quantity,
            "price": target,
            "transmit": transmit,
            "orderType": orderType,
            "ocaGroup": group,
            "parentId": parentId,
            "rth": rth,
            "tif": tif,
            "account": self._get_active_account(account)
        }
        # default order type is "Market if Touched"
        if orderType is None: # or orderType.upper() == "MKT":
            params['orderType'] = dataTypes["ORDER_TYPE_MIT"]
            params['auxPrice'] = target
            del params['price']

        order = self.createOrder(**params)
        return order

    # -----------------------------------------
    def createStopOrder(self, quantity, parentId=0, stop=0., trail=None,
            transmit=True, trigger=None, group=None, stop_limit=False,
            rth=False, tif="DAY", account=None, **kwargs):

        """ Creates STOP order """
        stop_limit_price = 0
        if stop_limit is not False:
            if stop_limit is True:
                stop_limit_price = stop
            else:
                try:
                    stop_limit_price = float(stop_limit)
                except Exception:
                    stop_limit_price = stop

        trailStopPrice = trigger if trigger else stop_limit_price
        if quantity > 0:
            trailStopPrice -= abs(stop)
        elif quantity < 0:
            trailStopPrice -= abs(stop)

        order_data = {
            "quantity": quantity,
            "trailStopPrice": trailStopPrice,
            "stop": abs(stop),
            "price": stop_limit_price,
            "transmit": transmit,
            "ocaGroup": group,
            "parentId": parentId,
            "rth": rth,
            "tif": tif,
            "account": self._get_active_account(account)
        }

        if trail:
            order_data['orderType'] = dataTypes["ORDER_TYPE_TRAIL_STOP"]
            if "orderType" in kwargs:
                order_data['orderType'] = kwargs["orderType"]
            elif stop_limit:
                # order_data['lmtPriceOffset'] = ??
                order_data['orderType'] = dataTypes["ORDER_TYPE_TRAIL_STOP_LIMIT"]

            if trail == "percent":
                order_data['trailingPercent'] = stop
            else:
                order_data['auxPrice'] = stop
        else:
            order_data['orderType'] = dataTypes["ORDER_TYPE_STOP"]
            if stop_limit:
                order_data['orderType'] = dataTypes["ORDER_TYPE_STOP_LIMIT"]

        order = self.createOrder(**order_data)
        return order

    # -----------------------------------------
    def createTrailingStopOrder(self, contract, quantity,
            parentId=0, trailType='percent', trailValue=100.,
            group=None, stopTrigger=None, account=None, **kwargs):

        """ convert hard stop order to trailing stop order """
        if parentId not in self.orders:
            raise ValueError("Order #" + str(parentId) + " doesn't exist or wasn't submitted")

        order = self.createStopOrder(quantity,
                    stop     = trailValue,
                    trail    = trailType,
                    transmit = True,
                    trigger  = stopTrigger,
                    # ocaGroup = group
                    parentId = parentId,
                    account  = self._get_active_account(account)
                )

        self.requestOrderIds()
        return self.placeOrder(contract, order, self.orderId + 1)

    # -----------------------------------------
    def createBracketOrder(self, contract, quantity,
            entry=0., target=0., stop=0.,
            targetType=None, stopType=None,
            trailingStop=False,  # (pct/amt/False)
            trailingValue=None,  # value to train by (amt/pct)
            trailingTrigger=None,  # (price where hard stop starts trailing)
            group=None, tif="DAY",
            fillorkill=False, iceberg=False, rth=False,
            transmit=True, account=None, **kwargs):

        """
        creates One Cancels All Bracket Order
        """
        if group == None:
            group = "bracket_" + str(int(time.time()))

        account = self._get_active_account(account)

        # main order
        enteyOrder = self.createOrder(quantity, price=entry, transmit=False,
                        tif=tif, fillorkill=fillorkill, iceberg=iceberg,
                        rth=rth, account=account, **kwargs)

        entryOrderId = self.placeOrder(contract, enteyOrder)

        # target
        targetOrderId = 0
        if target > 0 or targetType == "MOC":
            targetOrder = self.createTargetOrder(-quantity,
                            parentId  = entryOrderId,
                            target    = target,
                            transmit  = False if stop > 0 else True,
                            orderType = targetType,
                            group     = group,
                            rth       = rth,
                            tif       = tif,
                            account   = account
                        )

            self.requestOrderIds()
            targetOrderId = self.placeOrder(contract, targetOrder, self.orderId + 1)
            # print(self.orderId, targetOrderId)

        # stop
        stopOrderId = 0
        if stop > 0:
            stop_limit = stopType and stopType.upper() in ["LIMIT", "LMT"]
            # stop_limit = stop_limit or (
            #     trailingStop and trailingTrigger and trailingValue)
            stopOrder = self.createStopOrder(-quantity,
                            parentId   = entryOrderId,
                            stop       = stop,
                            trail      = None,
                            transmit   = transmit,
                            group      = group,
                            rth        = rth,
                            tif        = tif,
                            stop_limit = stop_limit,
                            account    = account
                        )

            self.requestOrderIds()
            stopOrderId = self.placeOrder(contract, stopOrder, self.orderId + 2)
            # print(self.orderId, stopOrderId)

            # triggered trailing stop?
            # print(trailingStop, trailingTrigger, trailingValue)
            if trailingStop and trailingTrigger and trailingValue:
                trailing_params = {
                    "symbol": self.contractString(contract),
                    "quantity": -quantity,
                    "triggerPrice": trailingTrigger,
                    "parentId": entryOrderId,
                    "stopOrderId": stopOrderId,
                    "targetOrderId": targetOrderId if targetOrderId != 0 else None,
                    "account": account
                }
                if trailingStop.lower() in ['amt', 'amount']:
                    trailing_params["trailAmount"] = trailingValue
                elif trailingStop.lower() in ['pct', 'percent']:
                    trailing_params["trailPercent"] = trailingValue

                self.createTriggerableTrailingStop(**trailing_params)

        return {
            "group": group,
            "entryOrderId": entryOrderId,
            "targetOrderId": targetOrderId,
            "stopOrderId": stopOrderId
        }

    # -----------------------------------------
    def placeOrder(self, contract, order, orderId=None, account=None):
        """ Place order on IB TWS """

        # get latest order id before submitting an order
        self.requestOrderIds()
        # time.sleep(0.01)

        # make sure the price confirms to th contract
        ticksize = self.contractDetails(contract)["m_minTick"]
        order.m_lmtPrice = self.roundClosestValid(order.m_lmtPrice, ticksize)
        order.m_auxPrice = self.roundClosestValid(order.m_auxPrice, ticksize)

        # continue...
        useOrderId = self.orderId if orderId == None else orderId

        account = self._get_active_account(account)
        if account is not None:
            order.m_account = account
        self.ibConn.placeOrder(useOrderId, contract, order)

        account_key = order.m_account
        self.orders[useOrderId] = {
            "id":       useOrderId,
            "symbol":   self.contractString(contract),
            "contract": contract,
            "status":   "SENT",
            "reason":   None,
            "avgFillPrice": 0.,
            "parentId": 0,
            "time": datetime.fromtimestamp(int(self.time)),
            "account": None
        }
        if hasattr(order, "m_account"):
            self.orders[useOrderId]["account"] = order.m_account

        # return order id
        return useOrderId

    # -----------------------------------------
    def cancelOrder(self, orderId):
        """ cancel order on IB TWS """
        self.ibConn.cancelOrder(orderId)

        # update order id for next time
        self.requestOrderIds()
        return orderId

    # -----------------------------------------
    # data requesters
    # -----------------------------------------
    # https://github.com/blampe/IbPy/blob/master/demo/reference_python
    def requestOpenOrders(self, all_clients=False):
        """
        Request open orders - loads up orders that wasn't created using this session
        """
        if all_clients:
            self.ibConn.reqAllOpenOrders()
        self.ibConn.reqOpenOrders()

    # -----------------------------------------
    def requestOrderIds(self, numIds=1):
        """
        Request the next valid ID that can be used when placing an order.
        Triggers the nextValidId() event, and the id returned is that next valid ID.
        # https://www.interactivebrokers.com/en/software/api/apiguide/java/reqids.htm
        """
        self.orderId += 1
        self.ibConn.reqIds(numIds)
        time.sleep(0.01)

    # -----------------------------------------
    def requestMarketDepth(self, contracts=None, num_rows=10):
        """
        Register to streaming market data updates
        https://www.interactivebrokers.com/en/software/api/apiguide/java/reqmktdepth.htm
        """

        if num_rows > 10:
            num_rows = 10

        if contracts == None:
            contracts = list(self.contracts.values())
        elif not isinstance(contracts, list):
            contracts = [contracts]

        for contract in contracts:
            tickerId = self.tickerId(self.contractString(contract))
            self.ibConn.reqMktDepth(
                tickerId, contract, num_rows)

    # -----------------------------------------
    def cancelMarketDepth(self, contracts=None):
        """
        Cancel streaming market data for contract
        https://www.interactivebrokers.com/en/software/api/apiguide/java/cancelmktdepth.htm
        """
        if contracts == None:
            contracts = list(self.contracts.values())
        elif not isinstance(contracts, list):
            contracts = [contracts]

        for contract in contracts:
            tickerId = self.tickerId(self.contractString(contract))
            self.ibConn.cancelMktDepth(tickerId=tickerId)

    # -----------------------------------------
    def requestMarketData(self, contracts=None, snapshot=False):
        """
        Register to streaming market data updates
        https://www.interactivebrokers.com/en/software/api/apiguide/java/reqmktdata.htm
        """
        if contracts == None:
            contracts = list(self.contracts.values())
        elif not isinstance(contracts, list):
            contracts = [contracts]

        for contract in contracts:
            if snapshot:
                reqType = ""
            else:
                reqType = dataTypes["GENERIC_TICKS_RTVOLUME"]
                if contract.m_secType in ("OPT", "FOP"):
                    reqType = dataTypes["GENERIC_TICKS_NONE"]

            # get market data for single contract
            # limit is 250 requests/second
            if not self.isMultiContract(contract):
                try:
                    tickerId = self.tickerId(self.contractString(contract))
                    self.ibConn.reqMktData(tickerId, contract, reqType, snapshot)
                    time.sleep(0.0042)  # 250 = 1.05s
                except KeyboardInterrupt:
                    sys.exit()

    # -----------------------------------------
    def cancelMarketData(self, contracts=None):
        """
        Cancel streaming market data for contract
        https://www.interactivebrokers.com/en/software/api/apiguide/java/cancelmktdata.htm
        """
        if contracts == None:
            contracts = list(self.contracts.values())
        elif not isinstance(contracts, list):
            contracts = [contracts]

        for contract in contracts:
            # tickerId = self.tickerId(contract.m_symbol)
            tickerId = self.tickerId(self.contractString(contract))
            self.ibConn.cancelMktData(tickerId=tickerId)

    # -----------------------------------------
    def requestHistoricalData(self, contracts=None, resolution="1 min",
            lookback="1 D", data="TRADES", end_datetime=None, rth=False,
            csv_path=None, format_date=2, utc=False):

        """
        Download to historical data
        https://www.interactivebrokers.com/en/software/api/apiguide/java/reqhistoricaldata.htm
        """

        self.csv_path = csv_path
        self.utc_history = utc

        if end_datetime == None:
            end_datetime = time.strftime(dataTypes["DATE_TIME_FORMAT_HISTORY"])

        if contracts == None:
            contracts = list(self.contracts.values())

        if not isinstance(contracts, list):
            contracts = [contracts]

        for contract in contracts:
            show = str(data).upper()
            if contract.m_secType in ['CASH', 'CFD'] and data == 'TRADES':
                show = 'MIDPOINT'

            # tickerId = self.tickerId(contract.m_symbol)
            tickerId = self.tickerId(self.contractString(contract))
            self.ibConn.reqHistoricalData(
                tickerId       = tickerId,
                contract       = contract,
                endDateTime    = end_datetime,
                durationStr    = lookback,
                barSizeSetting = resolution,
                whatToShow     = show,
                useRTH         = int(rth),
                formatDate     = int(format_date)
            )

    def cancelHistoricalData(self, contracts=None):
        """ cancel historical data stream """
        if contracts == None:
            contracts = list(self.contracts.values())
        elif not isinstance(contracts, list):
            contracts = [contracts]

        for contract in contracts:
            # tickerId = self.tickerId(contract.m_symbol)
            tickerId = self.tickerId(self.contractString(contract))
            self.ibConn.cancelHistoricalData(tickerId=tickerId)

    # -----------------------------------------
    def requestPositionUpdates(self, subscribe=True):
        """ Request/cancel request real-time position data for all accounts. """
        if self.subscribePositions != subscribe:
            self.subscribePositions = subscribe
            if subscribe == True:
                self.ibConn.reqPositions()
            else:
                self.ibConn.cancelPositions()

    # -----------------------------------------
    def requestAccountUpdates(self, subscribe=True):
        """
        Register to account updates
        https://www.interactivebrokers.com/en/software/api/apiguide/java/reqaccountupdates.htm
        """
        if self.subscribeAccount != subscribe:
            self.subscribeAccount = subscribe
            self.ibConn.reqAccountUpdates(subscribe, 0)
            # for accountCode in self.accountCodes:
            #     self.ibConn.reqAccountUpdates(subscribe, accountCode)

    # -----------------------------------------
    def requestContractDetails(self, contract):
        """
        Register to contract details
        https://www.interactivebrokers.com/en/software/api/apiguide/java/reqcontractdetails.htm
        """
        self.ibConn.reqContractDetails(self.tickerId(contract), contract)

    # -----------------------------------------
    def getConId(self, contract_identifier):
        """ Get contracts conId """
        details = self.contractDetails(contract_identifier)
        if len(details["contracts"]) > 1:
            return details["m_underConId"]
        return details["m_summary"]["m_conId"]

    # -----------------------------------------
    # combo orders
    # -----------------------------------------
    def createComboLeg(self, contract, action, ratio=1, exchange=None):
        """ create combo leg
        https://www.interactivebrokers.com/en/software/api/apiguide/java/comboleg.htm
        """
        leg = ComboLeg()

        loops = 0
        conId = 0
        while conId == 0 and loops < 100:
            conId = self.getConId(contract)
            loops += 1
            time.sleep(0.05)

        leg.m_conId = conId
        leg.m_ratio = abs(ratio)
        leg.m_action = action
        leg.m_exchange = contract.m_exchange if exchange is None else exchange
        leg.m_openClose = 0
        leg.m_shortSaleSlot = 0
        leg.m_designatedLocation = ""

        return leg

    # -----------------------------------------
    def createComboContract(self, symbol, legs, currency="USD", exchange=None):
        """ Used for ComboLegs. Expecting list of legs """
        exchange = legs[0].m_exchange if exchange is None else exchange
        contract_tuple = (symbol, "BAG", exchange, currency, "", 0.0, "")
        contract = self.createContract(contract_tuple, comboLegs=legs)
        return contract

    # -----------------------------------------
    def getStrikes(self, contract_identifier, smin=None, smax=None):
        """ return strikes of contract / "multi" contract's contracts """
        strikes = []
        contracts = self.contractDetails(contract_identifier)["contracts"]

        if contracts[0].m_secType not in ("FOP", "OPT"):
            return []

        # collect expirations
        for contract in contracts:
            strikes.append(contract.m_strike)

        # convert to floats
        strikes = list(map(float, strikes))
        # strikes = list(set(strikes))

        # get min/max
        if smin is not None or smax is not None:
            smin = smin if smin is not None else 0
            smax = smax if smax is not None else 1000000000
            srange = list(set(range(smin, smax, 1)))
            strikes = [n for n in strikes if n in srange]

        strikes.sort()
        return tuple(strikes)

    # -----------------------------------------
    def getExpirations(self, contract_identifier, expired=0):
        """ return expiration of contract / "multi" contract's contracts """
        expirations = []
        contracts = self.contractDetails(contract_identifier)["contracts"]

        if contracts[0].m_secType not in ("FUT", "FOP", "OPT"):
            return []

        # collect expirations
        for contract in contracts:
            expirations.append(contract.m_expiry)

        # convert to ints
        expirations = list(map(int, expirations))
        # expirations = list(set(expirations))

        # remove expired contracts
        today = int(datetime.now().strftime("%Y%m%d"))
        closest = min(expirations, key=lambda x: abs(x - today))
        expirations = expirations[expirations.index(closest) - expired:]

        return tuple(expirations)
