# cryptoquant/data/ — Data Layer

## OVERVIEW

Data pipeline for backtests and live trading: SQLite persistence, ccxt fetching, OHLCV validation, and out-of-sample helpers. Backtest and live engines use `BacktestDataFeed` and `LiveDataFeed` respectively.

## STRUCTURE

```
data/
├── backtest_feed.py  # BacktestDataFeed — historical OHLCV feed
├── live_feed.py      # LiveDataFeed — real-time OHLCV feed
├── store.py          # OHLCVStore — SQLite WAL persistence (218 lines)
├── fetcher.py        # OHLCVFetcher — ccxt wrapper + validation (255 lines)
├── oos.py            # Out-of-sample / walk-forward split helpers
├── quality.py        # Gap detection, outlier filtering
└── __init__.py
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Backtest data feed | `backtest_feed.py` | `BacktestDataFeed.get_ohlcv()` — SQLite + fetcher cascade |
| Live data feed | `live_feed.py` | `LiveDataFeed.get_ohlcv()` — real-time with polling |
| Modify SQLite schema | `store.py` | `_ensure_table()`, `_table_name()` |
| Change fetch logic | `fetcher.py` | `OHLCVFetcher.fetch()` / `fetch_range()` |
| Modify validation | `fetcher.py` | `validate_ohlcv()` — checks high≥low, no NaN, etc. |
| OOS splitting | `oos.py` | `temporal_split()`, `walk_forward_split()` |
| Data quality | `quality.py` | Gap detection, outlier filtering |

## CONVENTIONS

- **Cache key**: `(exchange, symbol, timeframe)` tuple. Symbol uses `/` separator (e.g., `BTC/USDT`).
- **Table naming**: `ohlcv_{exchange}_{symbol}_{timeframe}`. Slashes replaced with underscores.
- **Timestamps**: Unix milliseconds in SQLite. `DatetimeIndex` in DataFrames.
- **Validation**: All fetched data passes `validate_ohlcv()` before returning. Checks: high≥low, open/close in [low,high], volume≥0, no NaN.
- **Proxy**: Set manually on `exchange.session.proxies` — ccxt disables `trust_env`.

## ANTI-PATTERNS

- **DO NOT** bypass `BacktestDataFeed`/`LiveDataFeed` and call `OHLCVFetcher` directly from engine/strategy — breaks caching and feed logic.
- **DO NOT** store timezone-aware timestamps — strip tz at fetch boundary (`df.index.tz_localize(None)`).
- **DO NOT** use `OHLCVStore` without WAL mode — concurrent reads will fail.
- **DO NOT** skip `validate_ohlcv()` — corrupt data causes silent strategy errors.
- **DO NOT** assume contiguous timestamps — exchanges have gaps. Validation warns but does not reject.
