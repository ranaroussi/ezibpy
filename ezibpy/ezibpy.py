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

import time
from datetime import datetime
from pandas import DataFrame, read_pickle

from ib.opt import Connection
from ib.ext.Contract import Contract
from ib.ext.Order import Order

from ezibpy.utils import dataTypes

import atexit
import tempfile
import os
from stat import S_IWRITE

# =============================================================
# set debugging mode
# levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
# filename=LOG_FILENAME
# =============================================================
import logging
# import sys
# logging.basicConfig(stream=sys.stdout, level=self.log(mode="debug", msg=
    # format='%(asctime)s [%(levelname)s]: %(message)s')


class ezIBpy():

    def log(self, mode, msg):
        if self.logging:
            if mode == "debug":
                logging.debug(msg)
            elif mode == "info":
                logging.info(msg)
            elif mode == "warning":
                logging.warning(msg)
            elif mode == "error":
                logging.error(msg)
            elif mode == "critical":
                logging.critical(msg)



    def roundClosestValid(self, val, res, decimals=2):
        """ round to closest resolution """
        return round(round(val / res)*res, decimals)


    """
    https://www.interactivebrokers.com/en/software/api/apiguide/java/java_eclientsocket_methods.htm
    """
    # ---------------------------------------------------------
    def __init__(self):

        self.__version__   = 0.09

        self.logging       = False

        self.clientId      = 1
        self.port          = 4001 # 7496/7497 = TWS, 4001 = IBGateway
        self.host          = "localhost"
        self.ibConn        = None

        self.time          = 0
        self.commission    = 0

        self.connected     = False

        self.accountCode   = 0
        self.orderId       = 1

        # auto-construct for every contract/order
        self.tickerIds     = { 0: "SYMBOL" }
        self.contracts     = {}
        self.orders        = {}
        self.symbol_orders = {}
        self.account       = {}
        self.positions     = {}
        self.portfolio     = {}

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
            "datetime":[0], "oi": [0], "volume": [0],
            "bid":[0], "bidsize":[0],"ask":[0], "asksize":[0], "last":[0], "lastsize":[0],
            "historical_iv": [0], "iv": [0], "dividend": [0], "underlying": [0],
            "delta": [0], "gamma": [0], "vega": [0], "theta": [0],
        })
        optionsDF.set_index('datetime', inplace=True)
        self.optionsData  = { 0: optionsDF } # idx = tickerId

        # historical data contrainer
        self.historicalData = { }  # idx = symbol

        # register exit
        atexit.register(self.disconnect)


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

        # Assign error handling function.
        self.ibConn.register(self.handleErrorEvents, 'Error')

        # Assign server messages handling function.
        self.ibConn.registerAll(self.handleServerEvents)

        # connect
        self.log(mode="info", msg="[CONNECTING TO IB]")
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
            self.log(mode="info", msg="[DISCONNECT TO IB]")
            self.ibConn.disconnect()


    # ---------------------------------------------------------
    def getServerTime(self):
        """ get the current time on IB """
        self.ibConn.reqCurrentTime()

    # ---------------------------------------------------------
    # Start event handlers
    # ---------------------------------------------------------
    def handleErrorEvents(self, msg):
        """ logs error messages """
        # https://www.interactivebrokers.com/en/software/api/apiguide/tables/api_message_codes.htm
        if msg.errorCode != -1: # and msg.errorCode != 2104 and msg.errorCode != 2106:
            self.log(mode="error", msg=msg)
            self.ibCallback(caller="handleError", msg=msg.errorCode)

    # ---------------------------------------------------------
    def handleServerEvents(self, msg):
        """ dispatch msg to the right handler """

        if msg.typeName == "error":
            self.log(mode="error", msg="[IB ERROR] "+str(msg))

        elif msg.typeName == dataTypes["MSG_CURRENT_TIME"]:
            if self.time < msg.time:
                self.time = msg.time
                self.connected = True

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

        else:
            self.log(mode="info", msg="[SERVER]: "+ str(msg))
            pass

    # ---------------------------------------------------------
    # generic callback function - can be used externally
    # ---------------------------------------------------------
    def ibCallback(self, caller, msg, **kwargs):
        pass


    # ---------------------------------------------------------
    # Start admin handlers
    # ---------------------------------------------------------
    def handleConnectionClosed(self, msg):
        self.connected = False
        self.ibCallback(caller="handleConnectionClosed", msg=msg)


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
    def handleAccount(self, msg):
        """
        handle account info update
        https://www.interactivebrokers.com/en/software/api/apiguide/java/updateaccountvalue.htm
        """
        track = ["BuyingPower", "CashBalance", "DayTradesRemaining",
                 "NetLiquidation", "InitMarginReq", "MaintMarginReq",
                 "AvailableFunds", "AvailableFunds-C", "AvailableFunds-S"]

        if msg.key in track:
            # self.log(mode="info", msg="[ACCOUNT]: " + str(msg))
            self.account[msg.key] = float(msg.value)

            # fire callback
            self.ibCallback(caller="handleAccount", msg=msg)

    # ---------------------------------------------------------
    def handlePosition(self, msg):
        """ handle positions changes """

        # contract identifier
        contractString = self.contractString(msg.contract)

        # if msg.pos != 0 or contractString in self.contracts.keys():
        self.log(mode="info", msg="[POSITION]: " + str(msg))
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
        self.log(mode="info", msg="[PORTFOLIO]: " + str(msg))

        # contract identifier
        contractString = self.contractString(msg.contract)

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
        self.log(mode="info", msg="[ORDER]: " + str(msg))

        # get server time
        self.getServerTime()
        time.sleep(0.001)

        # we need to handle mutiple events for the same order status
        duplicateMessage = False;

        # open order
        if msg.typeName == dataTypes["MSG_TYPE_OPEN_ORDER"]:
            # contract identifier
            contractString = self.contractString(msg.contract)

            if msg.orderId in self.orders:
                duplicateMessage = True
            else:
                self.orders[msg.orderId] = {
                    "id":       msg.orderId,
                    "symbol":   contractString,
                    "contract": msg.contract,
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
        # self.log(mode="debug", msg="[HISTORY]: " + str(msg))
        print('.', end="",flush=True)

        if msg.date[:8].lower() == 'finished':
            # print(self.historicalData)
            if self.csv_path != None:
                for sym in self.historicalData:
                    # print("[HISTORY FINISHED]: " + str(sym.upper()))
                    # contractString = self.contractString(str(sym))
                    contractString = str(sym)
                    print("[HISTORY FINISHED]: " + contractString)
                    self.historicalData[sym].to_csv(
                        self.csv_path + contractString +'.csv'
                        );

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

        elif msg.tickType == dataTypes["FIELD_OPTION_HISTORICAL_VOL"]:
            df2use[msg.tickerId]['historical_iv'] = round(float(msg.value), 2)

        # fire callback
        self.ibCallback(caller="handleTickGeneric", msg=msg)

    # ---------------------------------------------------------
    def handleTickPrice(self, msg):
        """
        holds latest tick bid/ask/last price
        """
        # self.log(mode="debug", msg="[TICK PRICE]: " + dataTypes["PRICE_TICKS"][msg.field] + " - " + str(msg))
        # return

        df2use = self.marketData
        if self.contracts[msg.tickerId].m_secType in ("OPT", "FOP"):
            df2use = self.optionsData

        # create tick holder for ticker
        if msg.tickerId not in df2use.keys():
            df2use[msg.tickerId] = df2use[0].copy()

        # bid price
        if msg.canAutoExecute == 1 and msg.field == dataTypes["FIELD_BID_PRICE"]:
            df2use[msg.tickerId]['bid'] = float(msg.price)
        # ask price
        elif msg.canAutoExecute == 1 and msg.field == dataTypes["FIELD_ASK_PRICE"]:
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
            # self.log(mode="debug", msg="[TICK TS]: " + ts)

            # handle trailing stop orders
            if self.contracts[msg.tickerId].m_secType not in ("OPT", "FOP"):
                self.triggerTrailingStops(msg.tickerId)
                self.handleTrailingStops(msg.tickerId)

            # fire callback
            self.ibCallback(caller="handleTickString", msg=msg)


        elif (msg.tickType == dataTypes["FIELD_RTVOLUME"]):
            # self.log(mode="info", msg="[RTVOL]: " + str(msg))

            tick = dataTypes["RTVOL_TICKS"]
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

                # self.log(mode="debug", msg=tick['time'] + ':' + self.tickerSymbol(msg.tickerId) + "-" + str(tick))

                # fire callback
                self.ibCallback(caller="handleTickString", msg=msg, tick=tick)

            except:
                pass

        else:
            # self.log(mode="info", msg="tickString" + "-" + msg)
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

        # create tick holder for ticker
        if msg.tickerId not in self.optionsData.keys():
            self.optionsData[msg.tickerId] = self.optionsData[0].copy()

        self.optionsData[msg.tickerId]['iv']         = round(float(msg.impliedVol), 2)
        self.optionsData[msg.tickerId]['dividend']   = round(float(msg.pvDividend), 2)
        self.optionsData[msg.tickerId]['delta']      = round(float(msg.delta), 2)
        self.optionsData[msg.tickerId]['gamma']      = round(float(msg.gamma), 2)
        self.optionsData[msg.tickerId]['vega']       = round(float(msg.vega), 2)
        self.optionsData[msg.tickerId]['theta']      = round(float(msg.theta), 2)
        self.optionsData[msg.tickerId]['underlying'] = float(msg.undPrice)
        # print(msg)

        # fire callback
        self.ibCallback(caller="handleTickOptionComputation", msg=msg)


    # ---------------------------------------------------------
    # trailing stops
    # ---------------------------------------------------------
    def createTriggerableTrailingStop(self, symbol, quantity=1, \
        triggerPrice=0, trailPercent=100., trailAmount=0., \
        parentId=0, stopOrderId=None, ticksize=0.01):
        """ adds order to triggerable list """

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
    def registerTrailingStop(self, tickerId, orderId=0, quantity=1, \
        lastPrice=0, trailPercent=100., trailAmount=0., parentId=0, ticksize=0.01):
        """ adds trailing stop to monitor list """

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
        newStop = trailingStop['lastPrice']
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

        print("\n\n", trailingStop['lastPrice'], newStop, price, "\n\n")

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
    def tickerId(self, symbol):
        """
        returns the tickerId for the symbol or
        sets one if it doesn't exits
        """
        for tickerId in self.tickerIds:
            if symbol == self.tickerIds[tickerId]:
                return tickerId
                break
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
            contractTuple = (contract.m_symbol, contract.m_secType,
                contract.m_exchange, contract.m_currency, contract.m_expiry,
                contract.m_strike, contract.m_right)

        # build identifier
        try:
            if contractTuple[1] in ("OPT", "FOP"):
                # contractString = (contractTuple[0], contractTuple[1], contractTuple[6], contractTuple[4], contractTuple[5])
                if contractTuple[5]*100 - int(contractTuple[5]*100):
                    strike = contractTuple[5]
                else:
                    strike = "{0:.2f}".format(contractTuple[5])

                contractString = (contractTuple[0] + str(contractTuple[4]) + \
                    contractTuple[6], str(strike).replace(".", ""))

            elif contractTuple[1] == "FUT":
                # round expiry day to expiry month
                if localSymbol != "":
                    exp = localSymbol[2:-1]+str(contractTuple[4][:4])
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

        return contractString

    # ---------------------------------------------------------
    # contract constructors
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

        # include expired (needed for historical data)
        newContract.m_includeExpired = (newContract.m_secType == "FUT")

        # add contract to pull
        # self.contracts[contractTuple[0]] = newContract
        self.contracts[tickerId] = newContract

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
        contract_tuple = (symbol, "FUT", exchange, currency, expiry, 0.0, "")
        contract = self.createContract(contract_tuple)
        return contract

    def createFutureContract(self, symbol, currency="USD", expiry=None, exchange="GLOBEX"):
        return self.createFuturesContract(symbol=symbol, currency=currency, expiry=expiry, exchange=exchange)

    # ---------------------------------------------------------
    def createOptionContract(self, symbol, secType="OPT", \
        currency="USD", expiry=None, strike=0.0, otype="CALL", exchange="SMART"):
        # secType = OPT (Option) / FOP (Options on Futures)
        contract_tuple = (symbol, secType, exchange, currency, expiry, float(strike), otype)
        contract = self.createContract(contract_tuple)
        return contract

    # ---------------------------------------------------------
    def createCashContract(self, symbol, currency="USD", exchange="IDEALPRO"):
        """ Used for FX, etc:
        createCashContract("EUR", currency="USD")
        """
        contract_tuple = (symbol, "CASH", exchange, currency, "", 0.0, "")
        contract = self.createContract(contract_tuple)
        return contract

    # ---------------------------------------------------------
    # order constructors
    # ---------------------------------------------------------
    def createOrder(self, quantity, price=0., stop=0., tif="DAY", \
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
    def createTargetOrder(self, quantity, parentId=0, \
        target=0., orderType=None, transmit=True, group=None, rth=False):
        """ Creates TARGET order """
        order = self.createOrder(quantity,
            price     = target,
            transmit  = transmit,
            orderType = dataTypes["ORDER_TYPE_LIMIT"] if orderType == None else orderType,
            ocaGroup  = group,
            parentId  = parentId,
            rth       = rth
        )
        return order

    # ---------------------------------------------------------
    def createStopOrder(self, quantity, parentId=0, \
        stop=0., trail=None, transmit=True,
        group=None, rth=False, stop_limit=False):

        """ Creates STOP order """
        if trail is not None:
            if trail == "percent":
                order = self.createOrder(quantity,
                    trailingPercent = stop,
                    transmit  = transmit,
                    orderType = dataTypes["ORDER_TYPE_TRAIL_STOP"],
                    ocaGroup  = group,
                    parentId  = parentId,
                    rth       = rth
                )
            else:
                order = self.createOrder(quantity,
                    trailStopPrice = stop,
                    stop      = stop,
                    transmit  = transmit,
                    orderType = dataTypes["ORDER_TYPE_TRAIL_STOP"],
                    ocaGroup  = group,
                    parentId  = parentId,
                    rth       = rth
                )

        else:
            order = self.createOrder(quantity,
                stop      = stop,
                price     = stop if stop_limit else 0.,
                transmit  = transmit,
                orderType = dataTypes["ORDER_TYPE_STOP_LIMIT"] if stop_limit else dataTypes["ORDER_TYPE_STOP"],
                ocaGroup  = group,
                parentId  = parentId,
                rth       = rth
            )
        return order

    # ---------------------------------------------------------
    def createTrailingStopOrder(self, contract, quantity, \
        parentId=0, trailPercent=100., group=None, triggerPrice=None):
        """ convert hard stop order to trailing stop order """
        if parentId not in self.orders:
            raise ValueError("Order #"+ str(parentId) +" doesn't exist or wasn't submitted")
            return

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
    def createBracketOrder(self, \
        contract, quantity, entry=0., target=0., stop=0., \
        targetType=None, trailingStop=None, group=None, \
        tif="DAY", fillorkill=False, iceberg=False, rth=False, \
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
                rth       = rth
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
    def requestMarketData(self, contracts=None):
        """
        Register to streaming market data updates
        https://www.interactivebrokers.com/en/software/api/apiguide/java/reqmktdata.htm
        """
        if contracts == None:
            contracts = list(self.contracts.values())
        elif not isinstance(contracts, list):
            contracts = [contracts]

        for contract in contracts:
            reqType = dataTypes["GENERIC_TICKS_RTVOLUME"]
            if contract.m_secType in ("OPT", "FOP"):
                reqType = dataTypes["GENERIC_TICKS_NONE"]

            # tickerId = self.tickerId(contract.m_symbol)
            tickerId = self.tickerId(self.contractString(contract))
            self.ibConn.reqMktData(tickerId, contract, reqType, False)

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
        lookback="1 D", data="TRADES", end_datetime=None, rth=False, csv_path=None):
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
                formatDate     = 2
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

