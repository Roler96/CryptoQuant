# cryptoquant/data/ — Data Layer

## OVERVIEW

Three-level data cache (L1 memory → L2 SQLite → L3 exchange) with OHLCV validation. Upper layers (engine, strategy) only call `DataCache.get_ohlcv()`.

## STRUCTURE

```
data/
├── cache.py     # DataCache — 3-level cascade (235 lines)
├── store.py     # OHLCVStore — SQLite WAL persistence (218 lines)
├── fetcher.py   # OHLCVFetcher — ccxt wrapper + validation (255 lines)
└── __init__.py
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Change cache behavior | `cache.py` | `DataCache.get_ohlcv()` — L1/L2/L3 lookup |
| Modify SQLite schema | `store.py` | `_ensure_table()`, `_table_name()` |
| Change fetch logic | `fetcher.py` | `OHLCVFetcher.fetch()` / `fetch_range()` |
| Modify validation | `fetcher.py` | `validate_ohlcv()` — checks high≥low, no NaN, etc. |
| Tune L1 cache | `cache.py` | `_set_l1()`, `_get_l1()` — TTL + FIFO eviction |

## CONVENTIONS

- **Cache key**: `(exchange, symbol, timeframe)` tuple. Symbol uses `/` separator (e.g., `BTC/USDT`).
- **Table naming**: `ohlcv_{exchange}_{symbol}_{timeframe}`. Slashes replaced with underscores.
- **Timestamps**: Unix milliseconds in SQLite. `DatetimeIndex` in DataFrames.
- **Validation**: All fetched data passes `validate_ohlcv()` before returning. Checks: high≥low, open/close in [low,high], volume≥0, no NaN.
- **Proxy**: Set manually on `exchange.session.proxies` — ccxt disables `trust_env`.

## ANTI-PATTERNS

- **DO NOT** bypass `DataCache` and call `OHLCVFetcher` directly from engine/strategy — breaks caching.
- **DO NOT** store timezone-aware timestamps — strip tz at fetch boundary (`df.index.tz_localize(None)`).
- **DO NOT** use `OHLCVStore` without WAL mode — concurrent reads will fail.
- **DO NOT** skip `validate_ohlcv()` — corrupt data causes silent strategy errors.
- **DO NOT** assume contiguous timestamps — exchanges have gaps. Validation warns but does not reject.
