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

import atexit
import os
import tempfile
import time
import logging
import sys

from datetime import datetime
from pandas import DataFrame, read_pickle
from stat import S_IWRITE

from ib.opt import Connection
from ib.ext.Contract import Contract
from ib.ext.Order import Order
from ib.ext.ComboLeg import ComboLeg

from .utils import (
    dataTypes, createLogger
)

# -------------------------------------------------------------
createLogger('ezibpy')
# -------------------------------------------------------------


class ezIBpy():

    # ---------------------------------------------------------
    @staticmethod
    def roundClosestValid(val, res, decimals=2):
        """ round to closest resolution """
        return round(round(val / res)*res, decimals)

    # ---------------------------------------------------------
    # https://www.interactivebrokers.com/en/software/api/apiguide/java/java_eclientsocket_methods.htm
    def __init__(self):

        """Initialize a new ezIBpy object."""
        self.clientId         = 1
        self.port             = 4001 # 7496/7497 = TWS, 4001 = IBGateway
        self.host             = "localhost"
        self.ibConn           = None

        self.time             = 0
        self.commission       = 0

        self.connected        = False

        self.accountCode      = 0
        self.orderId          = 1

        # auto-construct for every contract/order
        self.tickerIds        = { 0: "SYMBOL" }
        self.contracts        = {}
        self.orders           = {}
        self.symbol_orders    = {}
        self.account          = {}
        self.positions        = {}
        self.portfolio        = {}

        self._contract_details = {} # multiple expiry/strike/side contracts
        self.contract_details  = {}
        self.localSymbolExpiry = {}

        # -----------------------------------------------------
        self.log = logging.getLogger('ezibpy') # get logger
        # -----------------------------------------------------

        # holds market data
        tickDF = DataFrame({
            "datetime":[0], "bid":[0], "bidsize":[0],
            "ask":[0], "asksize":[0], "last":[0], "lastsize":[0]
            })
        tickDF.set_index('datetime', inplace=True)
        self.marketData  = { 0: tickDF } # idx = tickerId

        # holds orderbook data
        l2DF = DataFrame(index=range(5), data={
            "bid":0, "bidsize":0,
            "ask":0, "asksize":0
        })
        self.marketDepthData = { 0: l2DF } # idx = tickerId

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
            "datetime":[0], "oi": [0], "volume": [0], "underlying": [0], "iv": [0],
            "bid":[0], "bidsize":[0],"ask":[0], "asksize":[0], "last":[0], "lastsize":[0],
            # opt field
            "price": [0], "dividend": [0], "imp_vol": [0], "delta": [0], "gamma": [0], "vega": [0], "theta": [0],
            "last_price": [0], "last_dividend": [0], "last_imp_vol": [0], "last_delta": [0], "last_gamma": [0], "last_vega": [0], "last_theta": [0],
            "bid_price": [0], "bid_dividend": [0], "bid_imp_vol": [0], "bid_delta": [0], "bid_gamma": [0], "bid_vega": [0], "bid_theta": [0],
            "ask_price": [0], "ask_dividend": [0], "ask_imp_vol": [0], "ask_delta": [0], "ask_gamma": [0], "ask_vega": [0], "ask_theta": [0],
        })
        optionsDF.set_index('datetime', inplace=True)
        self.optionsData  = { 0: optionsDF } # idx = tickerId

        # historical data contrainer
        self.historicalData = { }  # idx = symbol

        # register exit
        atexit.register(self.disconnect)

        # fire connected/disconnected callbacks/errors once per event
        self.connection_tracking = {
            "connected": False,
            "disconnected": False,
            "errors": []
        }

    # ---------------------------------------------------------
    def connect(self, clientId=0, host="localhost", port=4001):
        """ Establish connection to TWS/IBGW """
        self.clientId = clientId
        self.host     = host
        self.port     = port
        self.ibConn   = Connection.create(
                            host = self.host,
                            port = self.port,
                            clientId = self.clientId
                            )

        # Assign server messages handling function.
        self.ibConn.registerAll(self.handleServerEvents)

        # connect
        self.log.info("[CONNECTING TO IB]")
        self.ibConn.connect()

        # get server time
        self.getServerTime()

        # subscribe to position and account changes
        self.subscribePositions = False
        self.requestPositionUpdates(subscribe=True)

        self.subscribeAccount = False
        self.requestAccountUpdates(subscribe=True)

        # force refresh of orderId upon connect
        self.handleNextValidId(self.orderId)

    # ---------------------------------------------------------
    def disconnect(self):
        """ Disconnect from TWS/IBGW """
        if self.ibConn is not None:
            self.log.info("[DISCONNECT FROM IB]")
            self.ibConn.disconnect()

    # ---------------------------------------------------------
    def reconnect(self):
        while not self.connected:
            self.connect(self.clientId, self.host, self.port)
            time.sleep(1)

    # ---------------------------------------------------------
    def getServerTime(self):
        """ get the current time on IB """
        self.ibConn.reqCurrentTime()

    # ---------------------------------------------------------
    @staticmethod
    def contract_to_tuple(contract):
        return (contract.m_symbol, contract.m_secType,
            contract.m_exchange, contract.m_currency, contract.m_expiry,
            contract.m_strike, contract.m_right)

    # ---------------------------------------------------------
    # Start event handlers
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
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

        elif msg.typeName == dataTypes["MSG_TYPE_MANAGED_ACCOUNTS"]:
            self.accountCode = msg.accountsList

        elif msg.typeName == dataTypes["MSG_COMMISSION_REPORT"]:
            self.commission = msg.commissionReport.m_commission

        elif msg.typeName == dataTypes["MSG_CONTRACT_DETAILS"]:
            self.handleContractDetails(msg, end=False)

        elif msg.typeName == dataTypes["MSG_CONTRACT_DETAILS_END"]:
            self.handleContractDetails(msg, end=True)

        elif msg.typeName == dataTypes["MSG_TICK_SNAPSHOT_END"]:
            self.ibCallback(caller="handleTickSnapshotEnd", msg=msg)

        else:
            self.log.info("[SERVER]: %s", msg)
            pass

    # ---------------------------------------------------------
    # generic callback function - can be used externally
    # ---------------------------------------------------------
    def ibCallback(self, caller, msg, **kwargs):
        pass


    # ---------------------------------------------------------
    # Start admin handlers
    # ---------------------------------------------------------
    def handleConnectionState(self, msg):
        """:Return: True if IBPy message `msg` indicates the connection is unavailable for any reason, else False."""
        self.connected = not ( msg.typeName == "error" and
            msg.errorCode in dataTypes["DISCONNECT_ERROR_CODES"] )

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

    # ---------------------------------------------------------
    def handleConnectionClosed(self, msg):
        self.connected = False
        self.ibCallback(caller="handleConnectionClosed", msg=msg)

        # retry to connect
        self.reconnect()

    # ---------------------------------------------------------
    def handleNextValidId(self, orderId):
        """
        handle nextValidId event
        https://www.interactivebrokers.com/en/software/api/apiguide/java/nextvalidid.htm
        """
        self.orderId = orderId

        # cash last orderId
        try:
            # db file
            dbfile = tempfile.gettempdir()+"/ezibpy.pkl"

            lastOrderId = 1 # default
            if os.path.exists(dbfile):
                df = read_pickle(dbfile).groupby("clientId").last()
                filtered = df[df['clientId']==self.clientId]
                if len(filtered) > 0:
                    lastOrderId = filtered['orderId'].values[0]

            # override with db if needed
            if self.orderId <= 1 or self.orderId < lastOrderId+1:
                self.orderId = lastOrderId+1

            # save in db
            orderDB = DataFrame(index=[0], data={'clientId':self.clientId, 'orderId':self.orderId})
            if os.path.exists(dbfile):
                orderDB = df[df['clientId']!=self.clientId].append(orderDB[['clientId', 'orderId']])
            orderDB.groupby("clientId").last().to_pickle(dbfile)

            # make writeable by all users
            try: os.chmod(dbfile, S_IWRITE) # windows (cover all)
            except: pass
            try: os.chmod(dbfile, 0o777) # *nix
            except: pass

            time.sleep(.001)

        except:
            pass

    # ---------------------------------------------------------
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
                        if oldString in self.portfolio:
                            self.portfolio[newString] = self.portfolio[oldString]
                        if oldString in self.positions:
                            self.positions[newString] = self.positions[oldString]

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

        # continue if this is a "multi" contract
        if tickerId == msg.reqId:
            self._contract_details[msg.reqId]["m_summary"] = vars(contract)
        else:
            # print("+++", tickerId, contractString)
            self.contracts[tickerId] = contract
            self.contract_details[tickerId] = details.copy()
            self.contract_details[tickerId]["m_summary"] = vars(contract)
            self.contract_details[tickerId]["contracts"] = [contract]

        # fire callback
        self.ibCallback(caller="handleContractDetails", msg=msg)


    # ---------------------------------------------------------
    def handleAccount(self, msg):
        """
        handle account info update
        https://www.interactivebrokers.com/en/software/api/apiguide/java/updateaccountvalue.htm
        """
        track = ["BuyingPower", "CashBalance", "DayTradesRemaining",
                 "NetLiquidation", "InitMarginReq", "MaintMarginReq",
                 "AvailableFunds", "AvailableFunds-C", "AvailableFunds-S"]

        if msg.key in track:
            # self.log.info("[ACCOUNT]: %s", msg)
            self.account[msg.key] = float(msg.value)

            # fire callback
            self.ibCallback(caller="handleAccount", msg=msg)

    # ---------------------------------------------------------
    def handlePosition(self, msg):
        """ handle positions changes """
        self.log.info("[POSITION]: %s", msg)

        # contract identifier
        contract_tuple = self.contract_to_tuple(msg.contract)
        contractString = self.contractString(contract_tuple)

        # try creating the contract
        if msg.contract not in self.contracts.values() and msg.contract.m_exchange:
            self.createContract(contract_tuple)

        # if msg.pos != 0 or contractString in self.contracts.keys():
        self.positions[contractString] = {
            "symbol":        contractString,
            "position":      int(msg.pos),
            "avgCost":       float(msg.avgCost),
            "account":       msg.account
        }

        # fire callback
        self.ibCallback(caller="handlePosition", msg=msg)

    # ---------------------------------------------------------
    def handlePortfolio(self, msg):
        """ handle portfolio updates """
        self.log.info("[PORTFOLIO]: %s", msg)

        # contract identifier
        contract_tuple = self.contract_to_tuple(msg.contract)
        contractString = self.contractString(contract_tuple)

        # try creating the contract
        if msg.contract not in self.contracts.values() and msg.contract.m_exchange:
            self.createContract(contract_tuple)

        self.portfolio[contractString] = {
            "symbol":        contractString,
            "position":      int(msg.position),
            "marketPrice":   float(msg.marketPrice),
            "marketValue":   float(msg.marketValue),
            "averageCost":   float(msg.averageCost),
            "unrealizedPNL": float(msg.unrealizedPNL),
            "realizedPNL":   float(msg.realizedPNL),
            "account":       msg.accountName
        }

        # fire callback
        self.ibCallback(caller="handlePortfolio", msg=msg)

    # ---------------------------------------------------------
    def handleOrders(self, msg):
        """ handle order open & status """
        """
        It is possible that orderStatus() may return duplicate messages.
        It is essential that you filter the message accordingly.
        """
        self.log.info("[ORDER]: %s", msg)

        # get server time
        self.getServerTime()
        time.sleep(0.001)

        # we need to handle mutiple events for the same order status
        duplicateMessage = False

        # open order
        if msg.typeName == dataTypes["MSG_TYPE_OPEN_ORDER"]:
            # contract identifier
            contractString = self.contractString(msg.contract)

            if msg.orderId in self.orders and self.orders[msg.orderId]["status"] == "SENT":
                try: del self.orders[msg.orderId]
                except: pass

            if msg.orderId in self.orders:
                duplicateMessage = True
            else:
                self.orders[msg.orderId] = {
                    "id":       msg.orderId,
                    "symbol":   contractString,
                    "contract": msg.contract,
                    "order":    msg.order,
                    "status":   "OPENED",
                    "reason":   None,
                    "avgFillPrice": 0.,
                    "parentId": 0,
                    "time": datetime.fromtimestamp(int(self.time))
                }

        # order status
        elif msg.typeName == dataTypes["MSG_TYPE_ORDER_STATUS"]:
            if msg.orderId in self.orders and self.orders[msg.orderId]['status'] == msg.status.upper():
                duplicateMessage = True
            else:
                if "CANCELLED" in msg.status.upper():
                    try: del self.orders[msg.orderId]
                    except: pass
                else:
                    self.orders[msg.orderId]['status']       = msg.status.upper()
                    self.orders[msg.orderId]['reason']       = msg.whyHeld
                    self.orders[msg.orderId]['avgFillPrice'] = float(msg.avgFillPrice)
                    self.orders[msg.orderId]['parentId']     = int(msg.parentId)
                    self.orders[msg.orderId]['time']         = datetime.fromtimestamp(int(self.time))

            # remove from orders?
            # if msg.status.upper() == 'CANCELLED':
            #     del self.orders[msg.orderId]

        # fire callback
        if duplicateMessage == False:
            # group orders by symbol
            self.symbol_orders = self.group_orders("symbol")

            self.ibCallback(caller="handleOrders", msg=msg)

    # ---------------------------------------------------------
    def group_orders(self, by="symbol"):
        orders = {}
        for orderId in self.orders:
            order = self.orders[orderId]
            if order[by] not in orders.keys():
                orders[order[by]] = {}

            try: del order["contract"]
            except: pass
            orders[order[by]][order['id']] = order

        return orders

    # ---------------------------------------------------------
    # Start price handlers
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    def handleHistoricalData(self, msg):
        # self.log.debug("[HISTORY]: %s", msg)
        print('.', end="",flush=True)

        if msg.date[:8].lower() == 'finished':
            # print(self.historicalData)
            if self.csv_path != None:
                for sym in self.historicalData:
                    contractString = str(sym)
                    self.log.info("[HISTORICAL DATA FOR %s DOWNLOADED]" % contractString)
                    self.historicalData[contractString].to_csv(
                        self.csv_path + contractString +'.csv'
                        )

            print('.')
            # fire callback
            self.ibCallback(caller="handleHistoricalData", msg=msg, completed=True)

        else:
            # create tick holder for ticker
            if len(msg.date) <= 8: # daily
                ts = datetime.strptime(msg.date, dataTypes["DATE_FORMAT"])
                ts = ts.strftime(dataTypes["DATE_FORMAT_HISTORY"])
            else:
                ts = datetime.fromtimestamp(int(msg.date))
                ts = ts.strftime(dataTypes["DATE_TIME_FORMAT_LONG"])

            hist_row = DataFrame(index=['datetime'], data={
                "datetime":ts, "O":msg.open, "H":msg.high,
                "L":msg.low, "C":msg.close, "V":msg.volume,
                "OI":msg.count, "WAP": msg.WAP })
            hist_row.set_index('datetime', inplace=True)

            symbol = self.tickerSymbol(msg.reqId)
            if symbol not in self.historicalData.keys():
                self.historicalData[symbol] = hist_row
            else:
                self.historicalData[symbol] = self.historicalData[symbol].append(hist_row)

            # fire callback
            self.ibCallback(caller="handleHistoricalData", msg=msg, completed=False)

    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
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
            # self.log.info("[RTVOL]: %s", msg)

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

            except:
                pass

        else:
            # self.log.info("tickString-%s", msg)
            # fire callback
            self.ibCallback(caller="handleTickString", msg=msg)

        # print(msg)

    # ---------------------------------------------------------
    def handleTickOptionComputation(self, msg):
        """
        holds latest option data timestamp
        only option price is kept at the moment
        https://www.interactivebrokers.com/en/software/api/apiguide/java/tickoptioncomputation.htm
        """
        def calc_generic_val(data, field):
            last_val = data['last_'+field].values[-1]
            bid_val  = data['bid_'+field].values[-1]
            ask_val  = data['ask_'+field].values[-1]
            bid_ask_val = last_val
            if bid_val != 0 and ask_val != 0:
                bid_ask_val = (bid_val+ask_val)/2
            return max([ last_val, bid_ask_val ])

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
        self.optionsData[msg.tickerId][col_prepend+'imp_vol']  = valid_val(msg.impliedVol)
        self.optionsData[msg.tickerId][col_prepend+'dividend'] = valid_val(msg.pvDividend)
        self.optionsData[msg.tickerId][col_prepend+'delta']    = valid_val(msg.delta)
        self.optionsData[msg.tickerId][col_prepend+'gamma']    = valid_val(msg.gamma)
        self.optionsData[msg.tickerId][col_prepend+'vega']     = valid_val(msg.vega)
        self.optionsData[msg.tickerId][col_prepend+'theta']    = valid_val(msg.theta)
        self.optionsData[msg.tickerId][col_prepend+'price']    = valid_val(msg.optPrice)

        # save generic/mid
        data = self.optionsData[msg.tickerId]
        self.optionsData[msg.tickerId]['imp_vol']    = calc_generic_val(data, 'imp_vol')
        self.optionsData[msg.tickerId]['dividend']   = calc_generic_val(data, 'dividend')
        self.optionsData[msg.tickerId]['delta']      = calc_generic_val(data, 'delta')
        self.optionsData[msg.tickerId]['gamma']      = calc_generic_val(data, 'gamma')
        self.optionsData[msg.tickerId]['vega']       = calc_generic_val(data, 'vega')
        self.optionsData[msg.tickerId]['theta']      = calc_generic_val(data, 'theta')
        self.optionsData[msg.tickerId]['price']      = calc_generic_val(data, 'price')
        self.optionsData[msg.tickerId]['underlying'] = valid_val(msg.undPrice)


        # fire callback
        self.ibCallback(caller="handleTickOptionComputation", msg=msg)


    # ---------------------------------------------------------
    # trailing stops
    # ---------------------------------------------------------
    def createTriggerableTrailingStop(self, symbol, quantity=1,
        triggerPrice=0, trailPercent=100., trailAmount=0.,
        parentId=0, stopOrderId=None, ticksize=None):
        """ adds order to triggerable list """

        ticksize = self.contractDetails(symbol)["m_minTick"]

        self.triggerableTrailingStops[symbol] = {
            "parentId": parentId,
            "stopOrderId": stopOrderId,
            "triggerPrice": triggerPrice,
            "trailAmount": abs(trailAmount),
            "trailPercent": abs(trailPercent),
            "quantity": quantity,
            "ticksize": ticksize
        }

        return self.triggerableTrailingStops[symbol]

    # ---------------------------------------------------------
    def registerTrailingStop(self, tickerId, orderId=0, quantity=1,
        lastPrice=0, trailPercent=100., trailAmount=0., parentId=0, ticksize=None):
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

    # ---------------------------------------------------------
    def modifyStopOrder(self, orderId, parentId, newStop, quantity):
        """ modify stop order """
        if orderId in self.orders.keys():
            order = self.createStopOrder(
                quantity = quantity,
                parentId = parentId,
                stop     = newStop,
                trail    = False,
                transmit = True
            )
            return self.placeOrder(self.orders[orderId]['contract'], order, orderId)

        return None

    # ---------------------------------------------------------
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

        # filled / no positions?
        if (self.positions[symbol] == 0) | \
            (self.orders[trailingStop['orderId']]['status'] == "FILLED"):
            del self.trailingStops[tickerId]
            return None

        # continue...
        newStop  = trailingStop['lastPrice']
        ticksize = trailingStop['ticksize']

        # long
        if (trailingStop['quantity'] < 0) & (trailingStop['lastPrice'] < price):
            if abs(trailingStop['trailAmount']) > 0:
                newStop = price - abs(trailingStop['trailAmount'])
            elif trailingStop['trailPercent'] > 0:
                newStop = price - (price*(abs(trailingStop['trailPercent'])/100))
        # short
        elif (trailingStop['quantity'] > 0) & (trailingStop['lastPrice'] > price):
            if abs(trailingStop['trailAmount']) > 0:
                newStop = price + abs(trailingStop['trailAmount'])
            elif trailingStop['trailPercent'] > 0:
                newStop = price + (price*(abs(trailingStop['trailPercent'])/100))

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

    # ---------------------------------------------------------
    def triggerTrailingStops(self, tickerId):
        """ trigger waiting trailing stops """
        # print('.')
        # test
        symbol   = self.tickerSymbol(tickerId)
        price    = self.marketData[tickerId]['last'][0]
        # contract = self.contracts[tickerId]

        if symbol in self.triggerableTrailingStops.keys():
            pendingOrder   = self.triggerableTrailingStops[symbol]
            parentId       = pendingOrder["parentId"]
            stopOrderId    = pendingOrder["stopOrderId"]
            triggerPrice   = pendingOrder["triggerPrice"]
            trailAmount    = pendingOrder["trailAmount"]
            trailPercent   = pendingOrder["trailPercent"]
            quantity       = pendingOrder["quantity"]
            ticksize       = pendingOrder["ticksize"]

            # print(">>>>>>>", pendingOrder)
            # print(">>>>>>>", parentId)
            # print(">>>>>>>", self.orders)

            # abort
            if parentId not in self.orders.keys():
                # print("DELETING")
                del self.triggerableTrailingStops[symbol]
                return None
            else:
                if self.orders[parentId]["status"] != "FILLED":
                    return None

            # print("\n\n", quantity, triggerPrice, price, "\n\n")

            # create the order
            if ((quantity > 0) & (triggerPrice >= price)) | ((quantity < 0) & (triggerPrice <= price)) :

                newStop = price
                if trailAmount > 0:
                    if quantity > 0:
                        newStop += trailAmount
                    else:
                        newStop -= trailAmount
                elif trailPercent > 0:
                    if quantity > 0:
                        newStop += price*(trailPercent/100)
                    else:
                        newStop -= price*(trailPercent/100)
                else:
                    del self.triggerableTrailingStops[symbol]
                    return 0

                # print("------", stopOrderId , parentId, newStop , quantity, "------")

                # use valid newStop
                newStop = self.roundClosestValid(newStop, ticksize)

                trailingStopOrderId = self.modifyStopOrder(
                    orderId  = stopOrderId,
                    parentId = parentId,
                    newStop  = newStop,
                    quantity = quantity
                )

                if trailingStopOrderId:
                    # print(">>> TRAILING STOP")
                    del self.triggerableTrailingStops[symbol]

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

    # ---------------------------------------------------------
    # tickerId/Symbols constructors
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    def tickerSymbol(self, tickerId):
        """ returns the symbol of a tickerId """
        try:
            return self.tickerIds[tickerId]
        except:
            return ""


    # ---------------------------------------------------------
    def contractString(self, contract, seperator="_"):
        """ returns string from contract tuple """

        localSymbol   = ""
        contractTuple = contract

        if type(contract) != tuple:
            localSymbol   = contract.m_localSymbol
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

                contractString = (contractTuple[0] + str(contractTuple[4]) + \
                    contractTuple[6][0] + strike, contractTuple[1])
                    # contractTuple[6], str(strike).replace(".", ""))

            elif contractTuple[1] == "FUT":
                # round expiry day to expiry month
                if localSymbol != "":
                    # exp = localSymbol[2:3]+str(contractTuple[4][:4])
                    exp = localSymbol[2:3]+self.localSymbolExpiry[localSymbol][:4]
                else:
                    exp = str(contractTuple[4])[:6]
                    exp = dataTypes["MONTH_CODES"][int(exp[4:6])] + str(int(exp[:4]))

                contractString = (contractTuple[0] + exp, contractTuple[1])

            elif contractTuple[1] == "CASH":
                contractString = (contractTuple[0]+contractTuple[3], contractTuple[1])

            else: # STK
                contractString = (contractTuple[0], contractTuple[1])

            # construct string
            contractString = seperator.join(
                str(v) for v in contractString).replace(seperator+"STK", "")

        except:
            contractString = contractTuple[0]

        return contractString.replace(" ", "_").upper()

    # ---------------------------------------------------------
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
            'm_validExchanges': 'SMART', 'contracts':[Contract()], 'm_summary': {
                'm_conId': 0, 'm_currency': 'USD', 'm_exchange': 'SMART', 'm_expiry': '',
                'm_includeExpired': False, 'm_localSymbol': '', 'm_multiplier': '',
                'm_primaryExch': None, 'm_right': None, 'm_secType': '',
                'm_strike': 0.0, 'm_symbol': '', 'm_tradingClass': '',
            }
        }


    # ---------------------------------------------------------
    # contract constructors
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    def createContract(self, contractTuple, **kwargs):
        # https://www.interactivebrokers.com/en/software/api/apiguide/java/contract.htm

        contractString = self.contractString(contractTuple)
        # print(contractString)

        # get (or set if not set) the tickerId for this symbol
        # tickerId = self.tickerId(contractTuple[0])
        tickerId = self.tickerId(contractString)

        # construct contract
        newContract = Contract()

        newContract.m_symbol   = contractTuple[0]
        newContract.m_secType  = contractTuple[1]
        newContract.m_exchange = contractTuple[2]
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
    # ---------------------------------------------------------
    def createStockContract(self, symbol, currency="USD", exchange="SMART"):
        contract_tuple = (symbol, "STK", exchange, currency, "", 0.0, "")
        contract = self.createContract(contract_tuple)
        return contract

    # ---------------------------------------------------------
    def createFuturesContract(self, symbol, currency="USD", expiry=None, exchange="GLOBEX"):
        if not isinstance(expiry, list): expiry = [expiry]

        contracts = []
        for fut_expiry in expiry:
            contract_tuple = (symbol, "FUT", exchange, currency, fut_expiry, 0.0, "")
            contract = self.createContract(contract_tuple)
            contracts.append(contract)

        return contracts[0] if len(contracts) == 1 else contracts


    def createFutureContract(self, symbol, currency="USD", expiry=None, exchange="GLOBEX"):
        logging.warning("DEPRECATED: This method have been deprecated and will be removed in future versions. \
            Use createFuturesContract() instead.")
        return self.createFuturesContract(symbol=symbol, currency=currency, expiry=expiry, exchange=exchange)

    # ---------------------------------------------------------
    def createOptionContract(self, symbol, expiry=None, strike=0.0, otype="CALL",
        currency="USD", secType="OPT", exchange="SMART"):
        # secType = OPT (Option) / FOP (Options on Futures)
        if not isinstance(expiry, list): expiry = [expiry]
        if not isinstance(strike, list): strike = [strike]
        if not isinstance(otype, list):  otype  = [otype]

        contracts = []
        for opt_expiry in expiry:
            for opt_strike in strike:
                for opt_otype in otype:
                    contract_tuple = (symbol, secType, exchange, currency, opt_expiry, opt_strike, opt_otype)
                    contract = self.createContract(contract_tuple)
                    contracts.append(contract)

        return contracts[0] if len(contracts) == 1 else contracts

    # ---------------------------------------------------------
    def createCashContract(self, symbol, currency="USD", exchange="IDEALPRO"):
        """ Used for FX, etc:
        createCashContract("EUR", currency="USD")
        """
        contract_tuple = (symbol, "CASH", exchange, currency, "", 0.0, "")
        contract = self.createContract(contract_tuple)
        return contract

    # ---------------------------------------------------------
    def createIndexContract(self, symbol, currency="USD", exchange="CBOE"):
        """ Used for indexes (SPX, DJX, ...) """
        contract_tuple = (symbol, "IND", exchange, currency, "", 0.0, "")
        contract = self.createContract(contract_tuple)
        return contract

    # ---------------------------------------------------------
    # order constructors
    # ---------------------------------------------------------
    def createOrder(self, quantity, price=0., stop=0., tif="DAY",
        fillorkill=False, iceberg=False, transmit=True, rth=False, **kwargs):
        # https://www.interactivebrokers.com/en/software/api/apiguide/java/order.htm
        order = Order()
        order.m_clientId      = self.clientId
        order.m_action        = dataTypes["ORDER_ACTION_BUY"] if quantity>0 else dataTypes["ORDER_ACTION_SELL"]
        order.m_totalQuantity = abs(quantity)

        if "orderType" in kwargs:
            order.m_orderType = kwargs["orderType"]
        else:
            order.m_orderType = dataTypes["ORDER_TYPE_MARKET"] if price==0 else dataTypes["ORDER_TYPE_LIMIT"]

        order.m_lmtPrice      = price # LMT  Price
        order.m_auxPrice      = stop  # STOP Price
        order.m_tif           = tif   # DAY, GTC, IOC, GTD
        order.m_allOrNone     = int(fillorkill)
        order.hidden          = iceberg
        order.m_transmit      = int(transmit)
        order.m_outsideRth    = int(rth==False)

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
                order.m_ocaType = 2 # proportionately reduced size of remaining orders

        # For TRAIL order
        if "trailingPercent" in kwargs:
            order.m_trailingPercent = kwargs["trailingPercent"]

        # For TRAILLIMIT orders only
        if "trailStopPrice" in kwargs:
            order.m_trailStopPrice = kwargs["trailStopPrice"]


        return order


    # ---------------------------------------------------------
    def createTargetOrder(self, quantity, parentId=0,
        target=0., orderType=None, transmit=True, group=None, tif="DAY", rth=False):
        """ Creates TARGET order """
        order = self.createOrder(quantity,
            price     = target,
            transmit  = transmit,
            orderType = dataTypes["ORDER_TYPE_LIMIT"] if orderType == None else orderType,
            ocaGroup  = group,
            parentId  = parentId,
            rth       = rth,
            tif       = tif
        )
        return order

    # ---------------------------------------------------------
    def createStopOrder(self, quantity, parentId=0,
        stop=0., trail=None, transmit=True, group=None, stop_limit=False,
        rth=False, tif="DAY"):

        """ Creates STOP order """
        if trail is not None:
            if trail == "percent":
                order = self.createOrder(quantity,
                    trailingPercent = stop,
                    transmit  = transmit,
                    orderType = dataTypes["ORDER_TYPE_TRAIL_STOP"],
                    ocaGroup  = group,
                    parentId  = parentId,
                    rth       = rth,
                    tif       = tif
                )
            else:
                order = self.createOrder(quantity,
                    trailStopPrice = stop,
                    stop      = stop,
                    transmit  = transmit,
                    orderType = dataTypes["ORDER_TYPE_TRAIL_STOP"],
                    ocaGroup  = group,
                    parentId  = parentId,
                    rth       = rth,
                    tif       = tif
                )

        else:
            order = self.createOrder(quantity,
                stop      = stop,
                price     = stop if stop_limit else 0.,
                transmit  = transmit,
                orderType = dataTypes["ORDER_TYPE_STOP_LIMIT"] if stop_limit else dataTypes["ORDER_TYPE_STOP"],
                ocaGroup  = group,
                parentId  = parentId,
                rth       = rth,
                tif       = tif
            )
        return order

    # ---------------------------------------------------------
    def createTrailingStopOrder(self, contract, quantity,
        parentId=0, trailPercent=100., group=None, triggerPrice=None):
        """ convert hard stop order to trailing stop order """
        if parentId not in self.orders:
            raise ValueError("Order #"+ str(parentId) +" doesn't exist or wasn't submitted")

        order = self.createStopOrder(quantity,
            stop       = trailPercent,
            transmit   = True,
            trail      = True,
            # ocaGroup = group
            parentId   = parentId
        )

        self.requestOrderIds()
        return self.placeOrder(contract, order, self.orderId+1)

    # ---------------------------------------------------------
    def createBracketOrder(self,
        contract, quantity, entry=0., target=0., stop=0.,
        targetType=None, trailingStop=None, group=None,
        tif="DAY", fillorkill=False, iceberg=False, rth=False,
        stop_limit=False, **kwargs):
        """
        creates One Cancels All Bracket Order
        trailingStop = None (regular stop) / percent / amount
        """
        if group == None:
            group = "bracket_"+str(int(time.time()))

        # main order
        enteyOrder = self.createOrder(quantity, price=entry, transmit=False,
            tif=tif, fillorkill=fillorkill, iceberg=iceberg, rth=rth)
        entryOrderId = self.placeOrder(contract, enteyOrder)

        # target
        targetOrderId = 0
        if target > 0:
            targetOrder = self.createTargetOrder(-quantity,
                parentId  = entryOrderId,
                target    = target,
                transmit  = False if stop > 0 else True,
                orderType = targetType,
                group     = group,
                rth       = rth,
                tif       = tif
            )

            self.requestOrderIds()
            targetOrderId = self.placeOrder(contract, targetOrder, self.orderId+1)

        # stop
        stopOrderId = 0
        if stop > 0:
            stopOrder = self.createStopOrder(-quantity,
                parentId   = entryOrderId,
                stop       = stop,
                trail      = trailingStop,
                transmit   = True,
                group      = group,
                rth        = rth,
                tif        = tif,
                stop_limit = stop_limit
            )

            self.requestOrderIds()
            stopOrderId = self.placeOrder(contract, stopOrder, self.orderId+2)

        # triggered trailing stop?
        # if ("triggerPrice" in kwargs) & ("trailPercent" in kwargs):
            # self.pendingTriggeredTrailingStopOrders.append()
            # self.signal_ttl    = kwargs["signal_ttl"] if "signal_ttl" in kwargs else 0

        return {
            "group": group,
            "entryOrderId": entryOrderId,
            "targetOrderId": targetOrderId,
            "stopOrderId": stopOrderId
            }

    # ---------------------------------------------------------
    def placeOrder(self, contract, order, orderId=None):
        """ Place order on IB TWS """

        # get latest order id before submitting an order
        self.requestOrderIds()

        # continue...
        useOrderId = self.orderId if orderId == None else orderId
        self.ibConn.placeOrder(useOrderId, contract, order)

        self.orders[useOrderId] = {
            "id":       useOrderId,
            "symbol":   self.contractString(contract),
            "contract": contract,
            "status":   "SENT",
            "reason":   None,
            "avgFillPrice": 0.,
            "parentId": 0,
            "time": datetime.fromtimestamp(int(self.time))
        }


        # update order id for next time
        self.requestOrderIds()
        return useOrderId


    # ---------------------------------------------------------
    def cancelOrder(self, orderId):
        """ cancel order on IB TWS """
        self.ibConn.cancelOrder(orderId)

        # update order id for next time
        self.requestOrderIds()
        return orderId

    # ---------------------------------------------------------
    # data requesters
    # ---------------------------------------------------------
    # https://github.com/blampe/IbPy/blob/master/demo/reference_python

    # ---------------------------------------------------------
    def requestOrderIds(self, numIds=1):
        """
        Request the next valid ID that can be used when placing an order.
        Triggers the nextValidId() event, and the id returned is that next valid ID.
        # https://www.interactivebrokers.com/en/software/api/apiguide/java/reqids.htm
        """
        self.ibConn.reqIds(numIds)

    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
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


    # ---------------------------------------------------------
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
                    time.sleep(0.0042) # 250 = 1.05s
                except KeyboardInterrupt:
                    sys.exit()


    # ---------------------------------------------------------
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


    # ---------------------------------------------------------
    def requestHistoricalData(self, contracts=None, resolution="1 min",
        lookback="1 D", data="TRADES", end_datetime=None, rth=False,
        csv_path=None, format_date=2):
        """
        Download to historical data
        https://www.interactivebrokers.com/en/software/api/apiguide/java/reqhistoricaldata.htm
        """

        self.csv_path = csv_path

        if end_datetime == None:
            end_datetime = time.strftime(dataTypes["DATE_TIME_FORMAT_HISTORY"])

        if contracts == None:
            contracts = list(self.contracts.values())

        if not isinstance(contracts, list):
            contracts = [contracts]

        for contract in contracts:
            # tickerId = self.tickerId(contract.m_symbol)
            tickerId = self.tickerId(self.contractString(contract))
            self.ibConn.reqHistoricalData(
                tickerId       = tickerId,
                contract       = contract,
                endDateTime    = end_datetime,
                durationStr    = lookback,
                barSizeSetting = resolution,
                whatToShow     = data,
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

    # ---------------------------------------------------------
    def requestPositionUpdates(self, subscribe=True):
        """ Request/cancel request real-time position data for all accounts. """
        if self.subscribePositions != subscribe:
            self.subscribePositions = subscribe
            if subscribe == True:
                self.ibConn.reqPositions()
            else:
                self.ibConn.cancelPositions()


    # ---------------------------------------------------------
    def requestAccountUpdates(self, subscribe=True):
        """
        Register to account updates
        https://www.interactivebrokers.com/en/software/api/apiguide/java/reqaccountupdates.htm
        """
        if self.subscribeAccount != subscribe:
            self.subscribeAccount = subscribe
            self.ibConn.reqAccountUpdates(subscribe, self.accountCode)

    # ---------------------------------------------------------
    def requestContractDetails(self, contract):
        """
        Register to contract details
        https://www.interactivebrokers.com/en/software/api/apiguide/java/reqcontractdetails.htm
        """
        self.ibConn.reqContractDetails(self.tickerId(contract), contract)


    # ---------------------------------------------------------
    def getConId(self, contract_identifier):
        """ Get contracts conId """
        details = self.contractDetails(contract_identifier)
        if len(details["contracts"]) > 1:
            return details["m_underConId"]
        return details["m_summary"]["m_conId"]

    # ---------------------------------------------------------
    # combo orders
    # ---------------------------------------------------------
    def createComboLeg(self, contract, action, ratio=1, exchange=None):
        """ create combo leg
        https://www.interactivebrokers.com/en/software/api/apiguide/java/comboleg.htm
        """
        leg =  ComboLeg()

        leg.m_conId     = self.getConId(contract)
        leg.m_ratio     = abs(ratio)
        leg.m_action    = action
        leg.m_exchange  = contract.m_exchange if exchange is None else exchange
        leg.m_openClose = 0

        leg.m_shortSaleSlot      = 0
        leg.m_designatedLocation = ""

        return leg


    # ---------------------------------------------------------
    def createComboContract(self, symbol, legs, currency="USD"):
        """ Used for ComboLegs. Expecting list of legs """
        contract_tuple = (symbol, "BAG", legs[0].m_exchange, currency, "", 0.0, "")
        contract = self.createContract(contract_tuple, comboLegs=legs)
        return contract

    # ---------------------------------------------------------
    def getStrikes(self, contract_identifier, smin=None, smax=None):
        """ return strikes of contract / "multi" contract's contracts """
        strikes = []
        contracts = self.contractDetails(contract_identifier)["contracts"]

        if contracts[0].m_secType not in ("FOP", "OPT"):
            return []

        # collect expirations
        for contract in contracts:
            strikes.append( contract.m_strike )

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

    # ---------------------------------------------------------
    def getExpirations(self, contract_identifier, expired=0):
        """ return expiration of contract / "multi" contract's contracts """
        expirations = []
        contracts = self.contractDetails(contract_identifier)["contracts"]

        if contracts[0].m_secType not in ("FUT", "FOP", "OPT"):
            return []

        # collect expirations
        for contract in contracts:
            expirations.append( contract.m_expiry )

        # convert to ints
        expirations = list(map(int, expirations))
        # expirations = list(set(expirations))

        # remove expired contracts
        today   = int(datetime.now().strftime("%Y%m%d"))
        closest = min(expirations, key=lambda x:abs(x-today))
        expirations = expirations[expirations.index(closest)-expired:]

        return tuple(expirations)
