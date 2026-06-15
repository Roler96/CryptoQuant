# cryptoquant/ — Core Library

## OVERVIEW

Core trading library with 6 submodules: engine, strategy, execution, data, risk, monitor. All production code lives here.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Backtest a strategy | `engine/backtest.py` | `BacktestEngine.run(df, strategy, ...)` |
| Run live trading | `engine/live.py` | `LiveEngine.run(interval=60)` |
| Define a strategy | `strategy/base.py` | Subclass `Strategy`, implement `generate_signal()` |
| Technical indicators | `strategy/signals.py` | Pure numpy/pandas: SMA, EMA, RSI, MACD, BB, ATR, ADX, wick_imbalance |
| Fetch market data | `data/fetcher.py` | `OHLCVFetcher.fetch(symbol, timeframe, limit)` |
| Cache data | `data/cache.py` | `DataCache.get_ohlcv()` — L1→L2→L3 cascade |
| Store data | `data/store.py` | `OHLCVStore.save()/load()` — SQLite WAL |
| Place orders | `execution/broker.py` | `Broker.market_buy/sell()`, retry logic |
| Risk checks | `risk/manager.py` | `RiskManager.can_enter()` — daily limits, drawdown |
| Position sizing | `risk/sizer.py` | `FixedSizer`, `KellySizer`, `ATRSizer` |
| Logging setup | `monitor/logger.py` | `setup_logging(level, log_dir)` |
| Trade journal | `monitor/journal.py` | `TradeJournal.record()` — JSONL, thread-safe |
| Config | `config.py` | `load_config()` → `AppConfig` (pydantic-settings) |
| Exceptions | `exceptions.py` | `CryptoQuantError` hierarchy |

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
