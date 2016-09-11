## Change Log

#### 1.12.9

- Calls ``requestPositionUpdates(...)`` and ``requestAccountUpdates(...)`` upon connecting by default
- Calls ``requestOrderIds()`` before every order submission to prevent conflicts with other programs submitting orders (other instances of ezIBpy included)

#### 1.12.8

- Renamed ``createFutureContract(...)`` to ``createFuturesContract(...)`` (old name still works for backward compatibility)

#### 1.12.7

- Changed default exhange to IDEALPRO in ``createCashContract(...)``
