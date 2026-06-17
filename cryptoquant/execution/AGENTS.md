# cryptoquant/execution/ — Order Execution

## OVERVIEW

Broker abstraction layer: live ccxt broker, paper-trading simulator, and test mocks. All implement `BrokerABC`.

## STRUCTURE

```
execution/
├── broker.py       # Broker — live ccxt wrapper with retry + proxy (197 lines)
├── broker_abc.py   # BrokerABC interface + retry_on_network decorator
├── paper_broker.py # PaperBroker — simulated fills for paper trading
├── mock_broker.py  # MockBroker — test double with call_log
├── orders.py       # Order dataclasses and enums
└── __init__.py     # Re-exports Broker, Order, etc.
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Change live order logic | `broker.py` | `market_buy/sell()`, retry logic, proxy support |
| Add a new order type | `orders.py` | Extend `Order` dataclass or enums |
| Run paper trading | `paper_broker.py` | Simulated fills with configurable slippage |
| Write broker unit tests | `mock_broker.py` | `MockBroker` records all calls in `call_log` |
| Change retry behavior | `broker_abc.py` | `retry_on_network` decorator parameters |

## CONVENTIONS

- **BrokerABC**: All brokers must implement `get_position()`, `market_buy()`, `market_sell()`, `get_balance()`.
- **Retry**: Network errors are retried with exponential backoff via `@retry_on_network`.
- **Proxy**: ccxt sets `trust_env=False`; set `exchange.session.proxies` manually.
- **Spot vs Swap**: `Broker` handles both; pass `account_type` to differentiate.

## ANTI-PATTERNS

- **DO NOT** instantiate `Broker` directly in tests — use `MockBroker` or fixtures.
- **DO NOT** call `Broker.market_buy()` without checking `RiskManager.can_enter()` first.
- **DO NOT** rely on `trust_env` for proxy configuration — always set explicitly.
