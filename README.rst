ezIBpy: Pythonic Wrapper for IbPy
=================================================

.. image:: https://img.shields.io/badge/python-3.5+-blue.svg?style=flat
    :target: https://pypi.python.org/pypi/ezibpy
    :alt: Python version

.. image:: https://img.shields.io/pypi/v/ezibpy.svg?maxAge=60
    :target: https://pypi.python.org/pypi/ezibpy
    :alt: PyPi version

.. image:: https://img.shields.io/pypi/status/ezibpy.svg?maxAge=60
    :target: https://pypi.python.org/pypi/ezibpy
    :alt: PyPi status

.. image:: https://img.shields.io/travis/ranaroussi/ezibpy/master.svg?maxAge=1
    :target: https://travis-ci.org/ranaroussi/ezibpy
    :alt: Travis-CI build status

.. image:: https://img.shields.io/github/stars/ranaroussi/ezibpy.svg?style=social&label=Star&maxAge=60
    :target: https://github.com/ranaroussi/ezibpy
    :alt: Star this repo

.. image:: https://img.shields.io/twitter/follow/aroussi.svg?style=social&label=Follow&maxAge=60
    :target: https://twitter.com/aroussi
    :alt: Follow me on twitter

\

ezIBpy is a Pythonic wrapper for the `IbPy <https://github.com/blampe/IbPy>`_
library by `@blampe <https://github.com/blampe/IbPy>`_,
that was developed to speed up the development of
trading software that relies on
`Interactive Brokers <https://www.interactivebrokers.com>`_
for market data and order execution.

`Changelog » <./CHANGELOG.rst>`__

-----

**Version 1.12.67 now supports multiple/FA accounts!**

- Option to specify IB account upon connect. Alternatively, you can...
- Get info using ``getAccount('DUXXXXXX')``, ``getPositions('DUXXXXXX')``, ``getPortfolio('DUXXXXXX')``, or ``getOrders('DUXXXXXX')``
- Submit order to a specific account by specifing ``account=DUXXXXXX`` in ``createOrder()``, ``placeOrder()``, ``createBracketOrder()``, ``createTrailingStopOrder()``, ``createStopOrder()``, and ``createTargetOrder()`` methods

-----

NOTE
=====

Starting with release 9.73, Interactive Brokers is officially supporting a new `Python 3 API client <https://interactivebrokers.github.io/tws-api/#gsc.tab=0>`_.
Although this is great news, I don't see ezIBpy becoming obsolete anytime soon since IB's API isn't Pythonic or or abstracted enough IMO.
**I do have plans to drop IbPy in favor of IB's official Python API**, although I don't have a timetable for this transision.

If you're a developer and interested in helping converting ezIBpy to work with IB's Python API - please let me know :)

-----

Code Examples
=============

\* Make sure you have the latest version of
Interactive Brokers’ `TWS <https://www.interactivebrokers.com/en/index.php?f=15875>`_ or
`IB Gateway <https://www.interactivebrokers.com/en/index.php?f=16457>`_ installed and running on the machine.

**Market Data**

**\*\*\* YOU MUST HAVE ACTIVE MARKET DATA SUBSCRIPTION TO USE THESE METHODS \*\*\***

- `Request Market Data <#request-market-data>`_
- `Request Market Depth <#request-market-depth>`_
- `Request Historical Data <#request-historical-data>`_

**Order Execution**

- `Submit an Order <#submit-an-order>`_
- `Submit a Bracket Order <#submit-a-bracket-order>`_
- `Moving Stop Manually <#submit-a-bracket-order-&-move-stop-manually>`_
- `Bracket Order with Trailing Stop <#submit-a-bracket-order-with-a-trailing-stop>`_
- `Combo Orders <#submit-a-combo-orders>`_

**Other Stuff**

- `Using Custom Callbacks <#custom-callback>`_
- `Account Information <#account-information>`_
- `Logging <#logging>`_


Request Market Data:
--------------------
.. code:: python

    import ezibpy
    import time

    # initialize ezIBpy
    ibConn = ezibpy.ezIBpy()

    # connect to IB (7496/7497 = TWS, 4001 = IBGateway)
    ibConn.connect(clientId=100, host="localhost", port=4001)

    # create some contracts using dedicated methods
    stk_contract = ibConn.createStockContract("AAPL")
    fut_contract = ibConn.createFuturesContract("ES", expiry="201606")
    csh_contract = ibConn.createCashContract("EUR", currency="USD")
    opt_contract = ibConn.createOptionContract("AAPL", expiry="20160425", strike=105.0, otype="PUT")

    # ...or using a contract tuple
    oil_contract = ibConn.createContract(("CL", "FUT", "NYMEX", "USD", "201606", 0.0, ""))

    # request market data for all created contracts
    ibConn.requestMarketData()

    # wait 30 seconds
    time.sleep(30)

    # cancel market data request & disconnect
    ibConn.cancelMarketData()
    ibConn.disconnect()

Request Market Depth:
---------------------
.. code:: python

    import ezibpy
    import time

    # initialize ezIBpy
    ibConn = ezibpy.ezIBpy()
    ibConn.connect(clientId=100, host="localhost", port=4001)

    # create a contract & request market depth
    contract = ibConn.createCashContract("EUR", currency="USD")
    ibConn.requestMarketDepth()

    # wait 30 seconds
    time.sleep(30)

    # cancel market data request & disconnect
    ibConn.cancelMarketData()
    ibConn.disconnect()



Request Historical Data:
------------------------
.. code:: python

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


Submit an Order:
----------------
.. code:: python

    import ezibpy
    import time

    # initialize ezIBpy
    ibConn = ezibpy.ezIBpy()
    ibConn.connect(clientId=100, host="localhost", port=4001)

    # create a contract
    contract = ibConn.createFuturesContract("ES", exchange="GLOBEX", expiry="201609")

    # create an order
    order = ibConn.createOrder(quantity=1) # use price=X for LMT orders

    # submit an order (returns order id)
    orderId = ibConn.placeOrder(contract, order)

    # to submit an order to a specific account (ie DUXXXXXX), use:
    # orderId = ibConn.placeOrder(contract, order, account="DUXXXXXX")

    # let order fill
    time.sleep(1)

    # see the positions
    print("Positions")
    print(ibConn.positions)

    # disconnect
    ibConn.disconnect()


Submit a Bracket Order:
-----------------------
.. code:: python

    import ezibpy
    import time

    # initialize ezIBpy
    ibConn = ezibpy.ezIBpy()
    ibConn.connect(clientId=100, host="localhost", port=4001)

    # create a contract
    contract = ibConn.createFuturesContract("ES", exchange="GLOBEX", expiry="201609")

    # submit a bracket order (entry=0 = MKT order)
    order = ibConn.createBracketOrder(contract, quantity=1, entry=0, target=2200., stop=1900.)

    # to submit bracket order to a specific account (ie DUXXXXXX), use:
    # order = ibConn.createBracketOrder(contract, quantity=1, entry=0, target=2200., stop=1900., account="DUXXXXXX")

    # let order fill
    time.sleep(1)

    # see the positions
    print("Positions")
    print(ibConn.positions)

    # disconnect
    ibConn.disconnect()


Submit a Bracket Order & Move Stop Manually:
--------------------------------------------
.. code:: python

    import ezibpy
    import time

    # initialize ezIBpy
    ibConn = ezibpy.ezIBpy()
    ibConn.connect(clientId=100, host="localhost", port=4001)

    # create a contract
    contract = ibConn.createFuturesContract("ES", exchange="GLOBEX", expiry="201609")

    # submit a bracket order (entry=0 = MKT order)
    order = ibConn.createBracketOrder(contract, quantity=1, entry=0, target=2200., stop=1900.)

    # let order fill
    time.sleep(1)

    # see the positions
    print("Positions")
    print(ibConn.positions)

    # move the stop
    order['stopOrderId'] = ibConn.modifyStopOrder(orderId=order['stopOrderId'],
                parentId=order['entryOrderId'], newStop=2000, quantity=-1)


    # disconnect
    ibConn.disconnect()


Submit a Bracket Order with a Trailing Stop:
--------------------------------------------
.. code:: python

    import ezibpy
    import time

    # initialize ezIBpy
    ibConn = ezibpy.ezIBpy()
    ibConn.connect(clientId=100, host="localhost", port=4001)

    # create a contract
    contract = ibConn.createFuturesContract("ES", exchange="GLOBEX", expiry="201609")

    # submit a bracket order (entry=0 = MKT order)
    order = ibConn.createBracketOrder(contract, quantity=1, entry=0, target=2200., stop=1900.)

    # let order fill
    time.sleep(1)

    # see the positions
    print("Positions")
    print(ibConn.positions)

    # create a trailing stop that's triggered at 2190
    symbol = ibConn.contractString(contract)

    ibConn.createTriggerableTrailingStop(symbol, -1,
                triggerPrice  = 2190,
                trailAmount   = 10, # for trail using fixed amount
                # trailPercent  = 10, # for trail using percentage
                parentId      = order['entryOrderId'],
                stopOrderId   = order["stopOrderId"],
                ticksize      = 0.25 # see note
            )

    # ticksize is needed to rounds the stop price to nearest allowed tick size,
    # so you won't try to buy ES at 2200.128230 :)

    # NOTE: the stop trigger/trailing is done by the software,
    # so your script needs to keep running for this functionality to work

    # disconnect
    # ibConn.disconnect()


Submit a Combo Orders:
----------------------
.. code:: python

    import ezibpy
    import time

    # initialize ezIBpy
    ibConn = ezibpy.ezIBpy()
    ibConn.connect(clientId=100, host="localhost", port=4001)

    # create contracts for an bear call spread
    contract_to_sell = ibConn.createOptionContract("AAPL", expiry=20161118, strike=105., otype="CALL")
    contract_to_buy  = ibConn.createOptionContract("AAPL", expiry=20161118, strike=100., otype="CALL")

    # create combo legs
    leg1 = ibConn.createComboLeg(contract_to_sell, "SELL", ratio=1)
    leg2 = ibConn.createComboLeg(contract_to_buy, "BUY", ratio=1)

    # build a bag contract with these legs
    contract = ibConn.createComboContract("AAPL", [leg1, leg2])

    # create & place order (negative price means this is a credit spread)
    order = ibConn.createOrder(quantity=1, price=-0.25)
    orderId = ibConn.placeOrder(contract, order)

    # let order fill
    time.sleep(1)

    # see the positions
    print("Positions")
    print(ibConn.positions)

    # disconnect
    ibConn.disconnect()


Custom Callback:
----------------
.. code:: python

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
    time.sleep(1)

    # see the positions
    print("Positions")
    print(ibConn.positions)

    # disconnect
    ibConn.disconnect()


\* See `This Gist <https://gist.github.com/ranaroussi/cc2072e5f2cb2b83514fceaeb4b0ca2e>`_ for more examples.


Account Information:
--------------------
.. code:: python

    import ezibpy
    import time

    # initialize ezIBpy
    ibConn = ezibpy.ezIBpy()
    ibConn.connect(clientId=100, host="localhost", port=4001)

    # available variables (auto-updating)
    print("Market Data")
    print(ibConn.marketData)

    print("Market Depth")
    print(ibConn.marketDepthData)

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


Logging:
--------

ezIBpy logs via the standard `Python logging facilities <https://docs.python.org/3/howto/logging.html#logging-basic-tutorial>`__
under the logger name ``ezibpy`` at the level of ``ERROR`` by default.

You can change the log level:

.. code:: python

    import logging
    import ezibpy

    # after ezibpy is imported, we can silence error logging
    logging.getLogger('ezibpy').setLevel(logging.CRITICAL)

    # initialize with new logging configration
    ibConn = ezibpy.ezIBpy()
    ...

Or log to a file:

.. code:: python

    import logging
    import ezibpy

    # after ezibpy is imported, we can change the logging handler to file
    logger = logging.getLogger('ezibpy')
    logger.addHandler(logging.FileHandler('path/to/ezibpy.log'))
    logger.setLevel(logging.INFO)
    logger.propagate = False # do not also log to stderr

    # initialize with new logging configration
    ibConn = ezibpy.ezIBpy()
    ...



Installation
============

Install ezIBpy using ``pip``:

.. code:: bash

    $ pip install ezibpy --upgrade --no-cache-dir

Requirements
------------

* `Python <https://www.python.org>`_ >=3.4
* `Pandas <https://github.com/pydata/pandas>`_ (tested to work with >=0.23.0)
* `dateutil <https://pypi.python.org/pypi/python-dateutil>`_ (tested to with with >=2.5.1)
* `IbPy2 <https://github.com/blampe/IbPy>`_ (tested to work with >=0.8.0)
* Latest Interactive Brokers’ `TWS <https://www.interactivebrokers.com/en/index.php?f=15875>`_ or `IB Gateway <https://www.interactivebrokers.com/en/index.php?f=16457>`_ installed and running on the machine



To-Do:
======

In regards to Options, ezIBpy currently supports market
data retrieval and order execution.

If you want to add more functionality (such as news retreival, etc)
be my guest and please submit a pull request.


Legal Stuff
===========

ezIBpy is licensed under the **Apache License, Version 2.0**. A copy of which is included in LICENSE.txt.
ezIBpy is not a product of Interactive Brokers, nor is it affiliated with Interactive Brokers.


P.S.
====

I'm very interested in your experience with ezIBpy. Please drop me an note with any feedback you have.

**Ran Aroussi**
