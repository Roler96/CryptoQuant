# cryptoquant/ — Core Library

## OVERVIEW

Core trading library with 7 submodules: engine, strategy, execution, data, risk, monitor, analysis. All production code lives here.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Backtest a strategy | `engine/backtest.py` | `BacktestEngine.run(df, strategy, ...)` |
| Run live trading | `engine/live.py` | `LiveEngine.run(interval=60)` |
| Define a strategy | `strategy/base.py` | Subclass `Strategy`, implement `generate_signal()` |
| Technical indicators | `strategy/signals.py` | Pure numpy/pandas: SMA, EMA, RSI, MACD, BB, ATR, ADX, wick_imbalance |
| Fetch market data | `data/fetcher.py` | `OHLCVFetcher.fetch(symbol, timeframe, limit)` |
| Backtest data feed | `data/backtest_feed.py` | `BacktestDataFeed` — historical OHLCV for backtests |
| Live data feed | `data/live_feed.py` | `LiveDataFeed` — real-time OHLCV for live trading |
| Store data | `data/store.py` | `OHLCVStore.save()/load()` — SQLite WAL |
| OOS validation | `data/oos.py` | Walk-forward / temporal split helpers |
| Data quality | `data/quality.py` | Gap detection, outlier filtering |
| Place orders | `execution/broker.py` | `Broker.market_buy/sell()`, retry logic |
| Paper broker | `execution/paper_broker.py` | Simulated broker for paper trading |
| Mock broker | `execution/mock_broker.py` | Test double with call logging |
| Broker ABC | `execution/broker_abc.py` | `BrokerABC` interface + `retry_on_network` |
| Order types | `execution/orders.py` | Order dataclasses and enums |
| Risk checks | `risk/manager.py` | `RiskManager.can_enter()` — daily limits, drawdown |
| Position sizing | `risk/sizer.py` | `FixedSizer`, `KellySizer`, `ATRSizer` |
| Correlation check | `risk/correlation.py` | Cross-position correlation limits (standalone) |
| CVaR sizing | `risk/cvar.py` | Conditional Value-at-Risk position sizing |
| Logging setup | `monitor/logger.py` | `setup_logging(level, log_dir)` |
| Trade journal | `monitor/journal.py` | `TradeJournal.record()` — JSONL, thread-safe |
| Health checks | `monitor/health.py` | Broker connectivity + balance checks |
| Alerts | `monitor/alerts.py` | Webhook/email notification dispatch |
| Reporter | `monitor/reporter.py` | PnL / equity curve report generation |
| Log sanitizer | `monitor/sanitizer.py` | `SanitizingLogger` — redacts secrets |
| Post-trade analysis | `analysis/trade_analyzer.py` | `TradeAnalyzer` — metrics, curves, regimes |
| Config | `config.py` | `load_config()` → `AppConfig` (pydantic-settings) |
| Exceptions | `exceptions.py` | `CryptoQuantError` hierarchy |
| Strategy ensemble | `strategy/ensemble.py` | Compose multiple strategies |
| Regime switch | `strategy/regime_switch.py` | Route signals by market regime |

## CONVENTIONS

- **Submodule imports**: Always absolute from `cryptoquant.*`, never relative.
- **DataFrames**: Columns `[open, high, low, close, volume]`, `DatetimeIndex` (UTC, no tz).
- **Timestamps**: Unix milliseconds in all APIs. Convert at boundaries only.
- **Error handling**: Raise specific subclasses from `exceptions.py`. Never bare `except:`.
- **Logging**: Use `from loguru import logger`. Never `print()` in production code.

## ANTI-PATTERNS

- **DO NOT** add circular imports between submodules — dependency flow: `engine → strategy/execution/data/risk → monitor`.
- **DO NOT** instantiate `Broker` or `OHLCVFetcher` directly in tests — use mocks/fixtures.
- **DO NOT** store API keys in config objects — use environment variables via pydantic-settings.
