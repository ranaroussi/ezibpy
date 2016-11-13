Change Log
===========

1.12.32
-------

- Brought back (accidently) deleted ``tif`` functionality (closing issue #5)

1.12.31
-------

- Added ``requestContractDetails()`` method for calling IB's ``reqContractDetails()``.
- Added container dict for contract details is stored in ``contract_details[tickerId]``
- Auto calls ``requestContractDetails()`` for every created contract
- Contract details is availeble via ``contract_details[tickerId]`` or ``contractDetails(contract_or_symbol_or_tickerId)``
- No need to pass ticksize to ``createTriggerableTrailingStop()`` or ``registerTriggerableTrailingStop()`` (auto-uses data from contract details)


1.12.30
-------

- ``createBracketOrder`` now passes ``tif`` to parent, target and stop child orders (closing issue #5)


1.12.29
-------
- Switch to standard python logging and log errors to ``stderr`` by default.
- removed ``self.ibConn.register(self.handleErrorEvents, 'Error')`` so the code now calls this method from within ``handleServerEvents``
- disabled error callback for benign error codes (``2104`` and ``2106`` are not actually problems)


1.12.28
-------

- Fixed bug that casued error when no ``logger`` specified

1.12.27
-------

- Added two optional parameters to ``__init__()`` for auto-logging: ``logger`` as the log type (either "stream" for stdout or "file") and ``logger_file`` as log file path (if logger == "file")
- Pass entire message to ``handleError`` Callback


1.12.26
-------

- Using ``IbPy2`` installer from `PyPI <https://pypi.python.org/pypi/IbPy2>`_ (no need to install ``IbPy`` seperately anymore)

1.12.25
-------

- Added ``snapshot`` parameter to ``requestMarketData()`` to allow request of single snapshot of market data and have the market data subscription cancel (defaults to ``False``)


1.12.24
-------

- Fixed bug that casued malformed ``contractString`` for Asian Futures


1.12.23
-------

- Uniformed options symbol construction (eg ``AAPL20161028P00115000``, ``SPX20161024P02150000``)
- Misc code improvements and minor bug fixes


1.12.22
-------

- Misc code improvements and minor bug fixes


1.12.21
-------

- Complete Options and Futures Options market data available via ``optionsData``


1.12.20
-------

- Setting correct ``m_includeExpired`` for each asset class (solved a problem with historical data request not being acknowledged by TWS)


1.12.19
-------

- Fixed some issues with stop limit and trailing stop orders


1.12.18
-------

- Fixed some issues with stop limit and trailing stop orders


1.12.17
-------

- Added flag for stop limit orders
- Misc code improvements and minor bug fixes


1.12.16
-------

- Misc code improvements and minor bug fixes


1.12.15
-------

- Misc code improvements and minor bug fixes


1.12.14
-------

- Callback now fires on TWS errors and and passes one of IB's `error codes <https://www.interactivebrokers.com/en/software/api/apiguide/tables/api_message_codes.htm>`_.
- Callback fires upon lost connection to IB TWS/GW with the ``handleConnectionClosed`` event
- ``self.connected`` holds latest connection status (``True``/``False``)


1.12.13
-------

- Fixed bug that caused multiple ``clientId``s to be saved in the orderIds cache file. Now forcing saving of unique orderId in cache file.


1.12.12
-------

- ``cancelOrder()`` not requires ``orderId``
- Better hadling of canceled orders


1.12.11
-------

- Removed debugging code


1.12.10
-------

- Caching last ``orderId`` to keep a persistent ``orderId`` between TWS sessions (may require a one-time resetting of API Order ID Sequence, see `Interactive Brokers's API <https://www.interactivebrokers.com/en/software/java/topics/orders.htm>`_ for more information).


1.12.9
-------

- Calls ``requestPositionUpdates(...)`` and ``requestAccountUpdates(...)`` upon connecting by default
- Calls ``requestOrderIds()`` before every order submission to prevent conflicts with other programs submitting orders (other instances of ezIBpy included)


1.12.8
-------

- Renamed ``createFutureContract(...)`` to ``createFuturesContract(...)`` (old name still works for backward compatibility)


1.12.7
-------

- Changed default exhange to IDEALPRO in ``createCashContract(...)``
