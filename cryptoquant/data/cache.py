"""Three-level data cache: L1 (memory LRU) -> L2 (SQLite) -> L3 (ccxt fetch)."""

import time
from collections import OrderedDict, namedtuple

import pandas as pd
from loguru import logger

from cryptoquant.data.fetcher import OHLCVFetcher
from cryptoquant.data.store import OHLCVStore

CacheKey = namedtuple("CacheKey", ["exchange", "symbol", "timeframe"])
CacheEntry = namedtuple("CacheEntry", ["df", "cached_at", "latest_ts"])


# Timeframe to milliseconds mapping
_TF_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


def _lookback_to_start(timeframe: str, lookback: int) -> int:
    """Calculate start timestamp (ms) for a lookback count."""
    tf_ms = _TF_MS.get(timeframe, 3_600_000)
    return int(time.time() * 1000) - lookback * tf_ms


class DataCache:
    """Unified data access with 3-level caching.

    L1: In-memory LRU cache (OrderedDict)
    L2: SQLite persistent storage
    L3: ccxt exchange API (via OHLCVFetcher)

    Upper layers (Strategy, Backtest, Live) ONLY use get_ohlcv().
    """

    def __init__(
        self,
        store: OHLCVStore | None = None,
        fetcher: OHLCVFetcher | None = None,
        max_size: int = 128,
        ttl: int = 300,
    ):
        self.store = store or OHLCVStore()
        self.fetcher = fetcher or OHLCVFetcher()
        self._l1: OrderedDict[CacheKey, CacheEntry] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl

    def get_ohlcv(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        lookback: int | None = None,
        start: int | None = None,
        end: int | None = None,
    ) -> pd.DataFrame:
        """Get OHLCV data with cascading cache lookup.

        Priority: L1 -> L2 -> L3

        Args:
            exchange: Exchange name
            symbol: Trading pair
            timeframe: K-line period
            lookback: Number of recent candles
            start: Start timestamp (ms)
            end: End timestamp (ms)

        Returns:
            OHLCV DataFrame
        """
        key = CacheKey(exchange, symbol, timeframe)

        # L1: Memory cache
        l1_result = self._get_l1(key)
        if l1_result is not None:
            return l1_result

        # L2: SQLite
        l2_result = self._get_l2(exchange, symbol, timeframe, lookback, start, end)
        if l2_result is not None:
            self._set_l1(key, l2_result)
            return l2_result

        # L3: Fetch from exchange
        try:
            df = self._fetch_l3(exchange, symbol, timeframe, lookback, start, end)
        except Exception as e:
            logger.error(f"L3 fetch failed for {key}: {e}")
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        if not df.empty:
            self.store.save(df, exchange, symbol, timeframe)
            self._set_l1(key, df)

        return df

    def invalidate(self, exchange: str, symbol: str, timeframe: str) -> None:
        """Invalidate L1 cache for a specific key."""
        key = CacheKey(exchange, symbol, timeframe)
        self._l1.pop(key, None)

    def warm(
        self,
        exchange: str,
        symbols: list[str],
        timeframes: list[str],
        lookback_days: int = 30,
    ) -> dict[str, int]:
        """Pre-warm cache by fetching historical data for multiple symbols/timeframes.

        Returns:
            {symbol_tf: rows_fetched}
        """
        results = {}
        for symbol in symbols:
            for tf in timeframes:
                end = int(time.time() * 1000)
                start = end - lookback_days * 86_400_000
                try:
                    df = self.fetcher.fetch_range(symbol, tf, start, end)
                    if not df.empty:
                        self.store.save(df, exchange, symbol, tf)
                        self._set_l1(CacheKey(exchange, symbol, tf), df)
                    results[f"{symbol}_{tf}"] = len(df)
                except Exception as e:
                    logger.error(f"Warm failed for {symbol}/{tf}: {e}")
                    results[f"{symbol}_{tf}"] = 0
        return results

    def stats(self) -> dict:
        """Cache statistics for monitoring."""
        return {
            "l1_entries": len(self._l1),
            "l1_max_size": self._max_size,
            "l1_keys": [str(k) for k in self._l1.keys()],
            "db_path": str(self.store.db_path),
            "db_tables": self.store.list_tables(),
        }

    # ---- L1 (Memory) ----

    def _set_l1(self, key: CacheKey, df: pd.DataFrame) -> None:
        """Write to L1, evicting oldest if at capacity."""
        if key in self._l1:
            del self._l1[key]
        elif len(self._l1) >= self._max_size:
            self._l1.popitem(last=False)  # FIFO eviction
        self._l1[key] = CacheEntry(
            df=df.copy(deep=True),
            cached_at=time.time(),
            latest_ts=int(df.index[-1].timestamp() * 1000) if len(df) > 0 else None,
        )

    def _get_l1(self, key: CacheKey) -> pd.DataFrame | None:
        """Read from L1 with TTL check."""
        entry = self._l1.get(key)
        if entry is None:
            return None
        if time.time() - entry.cached_at >= self._ttl:
            del self._l1[key]
            return None
        self._l1.move_to_end(key)
        return entry.df.copy(deep=True)

    # ---- L2 (SQLite) ----

    def _get_l2(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        lookback: int | None,
        start: int | None,
        end: int | None,
    ) -> pd.DataFrame | None:
        """Read from L2 if enough data exists."""
        db_range = self.store.get_range(exchange, symbol, timeframe)
        if db_range is None:
            return None

        db_start, db_end = db_range

        # Check if we have enough data
        has_enough = False
        if lookback is not None:
            expected_start = _lookback_to_start(timeframe, lookback)
            has_enough = db_start <= expected_start
        elif start is not None:
            has_enough = db_start <= start and (end is None or db_end >= end)
        else:
            has_enough = True

        if not has_enough:
            return None

        df = self.store.load(exchange, symbol, timeframe, start=start, end=end)

        if lookback is not None and not df.empty:
            df = df.tail(lookback)

        if df.empty:
            return None

        return df

    # ---- L3 (Exchange) ----

    def _fetch_l3(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        lookback: int | None,
        start: int | None,
        end: int | None,
    ) -> pd.DataFrame:
        """Fetch from exchange API."""
        if lookback is not None:
            return self.fetcher.fetch(symbol, timeframe, limit=min(lookback, 300))
        elif start is not None:
            end_ts = end or int(time.time() * 1000)
            return self.fetcher.fetch_range(symbol, timeframe, start, end_ts)
        else:
            return self.fetcher.fetch(symbol, timeframe, limit=300)
