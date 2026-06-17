# tests/ — Test Suite

## OVERVIEW

pytest suite mirroring `cryptoquant/` structure. One test file per module. Integration tests hit real exchange APIs.

## STRUCTURE

```
tests/
├── conftest.py           # Fixtures (mock_broker) + custom markers
├── common_test.py        # Smoke script — NOT a pytest test (anomaly)
├── test_backtest.py      # BacktestEngine tests
├── test_live.py          # LiveEngine tests
├── test_broker.py        # Broker / MockBroker tests
├── test_fetcher.py       # OHLCVFetcher tests
├── test_store.py         # OHLCVStore tests
├── test_signals.py       # Technical indicator tests
├── test_manager.py       # RiskManager tests
├── test_sizer.py         # PositionSizer tests
├── test_latency.py       # Latency model tests
├── test_slippage.py      # Slippage model tests
├── test_commission.py    # Commission model tests
├── test_state.py         # StateManager tests
├── test_config.py        # Config loading tests
├── test_journal.py       # TradeJournal tests
├── test_health.py        # Health check tests
├── test_alerts.py        # Alert dispatch tests
├── test_reporter.py      # Reporter tests
├── test_sanitizer.py     # Log sanitizer tests
├── test_analysis.py      # TradeAnalyzer tests
├── test_correlation.py   # Correlation check tests
├── test_cvar.py          # CVaR sizing tests
├── test_ensemble.py      # Strategy ensemble tests
├── test_regime_switch.py # Regime switch tests
├── test_exit_logic.py    # Exit logic tests
├── test_types.py         # Dataclass tests
├── test_exceptions.py    # Exception hierarchy tests
├── test_paper_broker.py  # PaperBroker tests
├── test_mock_broker.py   # MockBroker tests
├── test_orders.py        # Order dataclass tests
├── test_oos.py           # OOS split tests
├── test_quality.py       # Data quality tests
└── test_strategy_*.py    # Concrete strategy tests
```

## CONVENTIONS

- **Test naming**: `test_<module>.py` for module tests, `test_strategy_<name>.py` for strategy tests.
- **Integration marker**: `@pytest.mark.integration` for tests hitting real APIs.
- **Fixtures**: `mock_broker()` in `conftest.py` returns a `MockBroker()` instance.
- **Smoke script**: `common_test.py` has `def main()` and fetches live BTC/USDT data — not a pytest test.

## ANTI-PATTERNS

- **DO NOT** add smoke scripts to `tests/` — use `research/` or `demo_*.py` instead.
- **DO NOT** run integration tests in CI without `@pytest.mark.integration` marker.
- **DO NOT** instantiate `Broker` or `OHLCVFetcher` directly in tests — use `mock_broker` fixture.
