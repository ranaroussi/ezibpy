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

# IB Referrence:
# --------------
# https://www.interactivebrokers.com/en/software/api/apiguide/java/reqhistoricaldata.htm
# https://www.interactivebrokers.com/en/software/api/apiguide/tables/tick_types.htm

dataTypes = {
    "MONTH_CODES" : ['','F','G','H','J','K','M','N','Q','U','V','X','Z'],

    "PRICE_TICKS" : { 1:"bid", 2:"ask", 4:"last", 6:"high", 7:"low", 9:"close", 14:"open"},
    "SIZE_TICKS"  : { 0:"bid", 3:"ask", 5:"last", 8:"volume"},
    "RTVOL_TICKS" : { "instrument":"", "ticketId":0, "price":0, "size":0, "time":0, "volume":0, "vwap":0, "single":0 },

    "FIELD_BID_SIZE"                  : 0,
    "FIELD_BID_PRICE"                 : 1,
    "FIELD_ASK_PRICE"                 : 2,
    "FIELD_ASK_SIZE"                  : 3,
    "FIELD_LAST_PRICE"                : 4,
    "FIELD_LAST_SIZE"                 : 5,
    "FIELD_HIGH"                      : 6,
    "FIELD_LOW"                       : 7,
    "FIELD_VOLUME"                    : 8,
    "FIELD_CLOSE_PRICE"               : 9,

    "FIELD_BID_OPTION_COMPUTATION"    : 10,
    "FIELD_ASK_OPTION_COMPUTATION"    : 11,
    "FIELD_LAST_OPTION_COMPUTATION"   : 12,
    "FIELD_MODEL_OPTION_COMPUTATION"  : 13,

    "FIELD_OPEN_INTEREST"             : 22, #  tickSize()
    "FIELD_OPTION_HISTORICAL_VOL"     : 23, #  tickGeneric()
    "FIELD_OPTION_IMPLIED_VOL"        : 24, #  tickGeneric()
    "FIELD_OPTION_CALL_OPEN_INTEREST" : 27, #  tickSize()
    "FIELD_OPTION_PUT_OPEN_INTEREST"  : 28, #  tickSize()
    "FIELD_OPTION_CALL_VOLUME"        : 29, #  tickSize()
    "FIELD_OPTION_PUT_VOLUME"         : 30, #  tickSize()

    "FIELD_AVG_VOLUME"                : 21,
    "FIELD_BID_EXCH"                  : 32,
    "FIELD_ASK_EXCH"                  : 33,
    "FIELD_AUCTION_VOLUME"            : 34,
    "FIELD_AUCTION_PRICE"             : 35,
    "FIELD_LAST_TIMESTAMP"            : 45,
    "FIELD_RTVOLUME"                  : 48,
    "FIELD_HALTED"                    : 49,
    "FIELD_TRADE_COUNT"               : 54,
    "FIELD_TRADE_RATE"                : 55,
    "FIELD_VOLUME_RATE"               : 56,

    "FIELD_HALTED_NOT_HALTED"         : 0,
    "FIELD_HALTED_IS_HALTED"          : 1,
    "FIELD_HALTED_BY_VOLATILITY"      : 2,

    "DURATION_1_HR"                   : "3600 S",
    "DURATION_1_MIN"                  : "60 S",
    "DURATION_1_DAY"                  : "1 D",

    "BAR_SIZE_1_SEC"                  : "1 secs",
    "BAR_SIZE_1_MIN"                  : "1 min",

    "RTH_ALL"                         : 0,
    "RTH_ONLY_TRADING_HRS"            : 1,

    "WHAT_TO_SHOW_TRADES"             : "TRADES",
    "WHAT_TO_SHOW_MID_PT"             : "MIDPOINT",
    "WHAT_TO_SHOW_BID"                : "BID",
    "WHAT_TO_SHOW_ASK"                : "ASK",
    "WHAT_TO_SHOW_BID_ASK"            : "BID_ASK",
    "WHAT_TO_SHOW_HVOL"               : "HISTORICAL_VOLATILITY",
    "WHAT_TO_SHOW_OPT_IMPV"           : "OPTION_IMPLIED_VOLATILITY",

    "DATEFORMAT_STRING"               : 1,
    "DATEFORMAT_UNIX_TS"              : 2,

    "MSG_CURRENT_TIME"                : "currentTime",
    "MSG_COMMISSION_REPORT"           : "commissionReport",
    "MSG_CONNECTION_CLOSED"           : "connectionClosed",

    "MSG_TYPE_HISTORICAL_DATA"        : "historicalData",
    "MSG_TYPE_ACCOUNT_UPDATES"        : "updateAccountValue",
    "MSG_TYPE_ACCOUNT_TIME_UPDATES"   : "updateAccountTime",
    "MSG_TYPE_PORTFOLIO_UPDATES"      : "updatePortfolio",
    "MSG_TYPE_POSITION"               : "position",
    "MSG_TYPE_MANAGED_ACCOUNTS"       : "managedAccounts",

    "MSG_TYPE_NEXT_ORDER_ID"          : "nextValidId",
    "MSG_TYPE_OPEN_ORDER"             : "openOrder",
    "MSG_TYPE_ORDER_STATUS"           : "orderStatus",

    "MSG_TYPE_MKT_DEPTH"              : "updateMktDepth",
    "MSG_TYPE_MKT_DEPTH_L2"           : "updateMktDepthL2",

    "MSG_TYPE_TICK_PRICE"             : "tickPrice",
    "MSG_TYPE_TICK_STRING"            : "tickString",
    "MSG_TYPE_TICK_GENERIC"           : "tickGeneric",
    "MSG_TYPE_TICK_SIZE"              : "tickSize",
    "MSG_TYPE_TICK_OPTION"            : "tickOptionComputation",

    "DATE_FORMAT"                     : "%Y%m%d",
    "DATE_TIME_FORMAT"                : "%Y%m%d %H:%M:%S",
    "DATE_TIME_FORMAT_LONG"           : "%Y-%m-%d %H:%M:%S",
    "DATE_TIME_FORMAT_LONG_MILLISECS" : "%Y-%m-%d %H:%M:%S.%f",
    "DATE_TIME_FORMAT_HISTORY"        : "%Y%m%d %H:%M:%S",
    "DATE_FORMAT_HISTORY"             : "%Y-%m-%d",

    "GENERIC_TICKS_NONE"              : "",
    "GENERIC_TICKS_RTVOLUME"          : "233",

    "SNAPSHOT_NONE"                   : False,
    "SNAPSHOT_TRUE"                   : True,

    # MARKET ORDERS
    "ORDER_TYPE_MARKET"               : "MKT",
    "ORDER_TYPE_MOC"                  : "MOC", # MARKET ON CLOSE
    "ORDER_TYPE_MOO"                  : "MOO", # MARKET ON OPEN
    "ORDER_TYPE_MIT"                  : "MIT", # MARKET IF TOUCHED

    # LIMIT ORDERS
    "ORDER_TYPE_LIMIT"                : "LMT",
    "ORDER_TYPE_LOC"                  : "LOC", # LIMIT ON CLOSE
    "ORDER_TYPE_LOO"                  : "LOO", # LIMIT ON OPEN
    "ORDER_TYPE_LIT"                  : "LIT", # LIMIT IF TOUCHED

    # STOP ORDERS
    "ORDER_TYPE_STOP"                 : "STP",
    "ORDER_TYPE_STOP_LIMIT"           : "STP LMT",
    "ORDER_TYPE_TRAIL_STOP"           : "TRAIL",
    "ORDER_TYPE_TRAIL_STOP_LIMIT"     : "TRAIL LIMIT",
    "ORDER_TYPE_TRAIL_STOP_LIT"       : "TRAIL LIT", # LIMIT IF TOUCHED
    "ORDER_TYPE_TRAIL_STOP_MIT"       : "TRAIL MIT", # MARKET IF TOUCHED

    # MINC ORDERS
    "ORDER_TYPE_ONE_CANCELS_ALL"      : "OCA",
    "ORDER_TYPE_RELATIVE"             : "REL",
    "ORDER_TYPE_PEGGED_TO_MIDPOINT"   : "PEG MID",

    # ORDER ACTIONS
    "ORDER_ACTION_SELL"               : "SELL",
    "ORDER_ACTION_BUY"                : "BUY",
    "ORDER_ACTION_SHORT"              : "SSHORT"

}
