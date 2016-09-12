## Change Log

#### 1.12.10

- Caching last ``orderId`` to keep a persistent ``orderId`` between TWS sessions (may require a one-time resetting of API Order ID Sequence, see
[https://www.interactivebrokers.com/en/software/csharp/topics/orders.htm](https://www.interactivebrokers.com/en/software/csharp/topics/orders.htm) for more information).


#### 1.12.9

- Calls ``requestPositionUpdates(...)`` and ``requestAccountUpdates(...)`` upon connecting by default
- Calls ``requestOrderIds()`` before every order submission to prevent conflicts with other programs submitting orders (other instances of ezIBpy included)

#### 1.12.8

- Renamed ``createFutureContract(...)`` to ``createFuturesContract(...)`` (old name still works for backward compatibility)

#### 1.12.7

- Changed default exhange to IDEALPRO in ``createCashContract(...)``
