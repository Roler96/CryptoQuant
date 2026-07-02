"""Live data feed for real-time trading."""

import time as _time

import pandas as pd
from loguru import logger

from cryptoquant.data.fetcher import OHLCVFetcher, validate_ohlcv
from cryptoquant.data.quality import DataQualityChecker, QualityReport
from cryptoquant.data.store import OHLCVStore
from cryptoquant.exceptions import DataValidationError


def _timeframe_to_seconds(tf: str) -> int:
    """Convert timeframe string like '5m' to seconds."""
    tf = tf.lower().strip()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    elif tf.endswith("h"):
        return int(tf[:-1]) * 3600
    elif tf.endswith("d"):
        return int(tf[:-1]) * 86400
    elif tf.endswith("w"):
        return int(tf[:-1]) * 604800
    return 3600  # default 1h


class LiveDataFeed:
    """Fetches and stores live OHLCV data for a single symbol."""

    def __init__(
        self,
        fetcher: OHLCVFetcher,
        store: OHLCVStore,
        exchange: str,
        symbol: str,
        timeframe: str,
        strict_validation: bool = True,
        quality_check: bool = True,
        fail_on_quality: bool = False,
    ):
        self.fetcher = fetcher
        self.store = store
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.strict_validation = strict_validation
        self.quality_check = quality_check
        self.fail_on_quality = fail_on_quality
        self._last_fetch_ts: int = 0
        self._last_quality_report: QualityReport | None = None
        self._df_cache: pd.DataFrame | None = None  # accumulate bars across calls

    def fetch(self, lookback: int) -> pd.DataFrame:
        """Fetch recent OHLCV data, validate it, and persist to store.

        Merges freshly fetched bars with in-memory cache so the engine
        always gets ``lookback`` bars (or as many as exist).
        """
        import time

        now_ms = int(time.time() * 1000)
        tf_seconds = _timeframe_to_seconds(self.timeframe)
        needed_ms = lookback * tf_seconds * 1000
        since_ms = now_ms - needed_ms

        # 1. Fetch new bars from exchange (paginate if lookback exceeds single-call limit)
        max_per_call = min(self.fetcher.max_candles, 300)  # exchange hard limit
        try:
            if lookback <= max_per_call:
                df_new = self.fetcher.fetch(
                    self.symbol, self.timeframe, limit=lookback
                )
            else:
                df_new = self.fetcher.fetch_range(
                    self.symbol, self.timeframe, start=since_ms, end=now_ms
                )
        except Exception:
            df_new = pd.DataFrame(columns=pd.Index(["open", "high", "low", "close", "volume"]))

        # If no new data but cache exists, return cached tail
        if df_new.empty and self._df_cache is not None and not self._df_cache.empty:
            return self._df_cache.iloc[-lookback:]

        if df_new.empty:
            self._last_quality_report = None
            return df_new

        validate_ohlcv(df_new, strict=self.strict_validation)

        # 2. Merge with in-memory cache
        if self._df_cache is not None and not self._df_cache.empty:
            df_merged = pd.concat([self._df_cache, df_new])
            df_merged = df_merged[~df_merged.index.duplicated(keep="last")]
            df_merged.sort_index(inplace=True)
            if len(df_merged) > lookback * 3:
                df_merged = df_merged.iloc[-(lookback * 2):]
            self._df_cache = pd.DataFrame(df_merged)
        else:
            self._df_cache = df_new.copy()

        # Defensive: both branches above set _df_cache, but pyright can't narrow through if/else
        if self._df_cache is None:
            return df_new

        # 3. Quality check
        if self.quality_check:
            self._last_quality_report = DataQualityChecker(self._df_cache).check()
            if not self._last_quality_report.is_healthy:
                logger.warning(
                    f"Live data quality issue for {self.symbol} {self.timeframe}: "
                    f"{self._last_quality_report}"
                )
                if self.fail_on_quality:
                    raise DataValidationError(
                        "Live data quality check failed: "
                        f"{self._last_quality_report}"
                    )

        # 4. Persist to store
        self.store.save(df_new, self.exchange, self.symbol, self.timeframe)
        self._last_fetch_ts = int(_time.time() * 1000)

        # 5. Return last `lookback` bars
        result = self._df_cache.iloc[-lookback:]
        return result

    @property
    def last_fetch_ts(self) -> int:
        """Unix ms of last successful fetch, or 0 if never fetched."""
        return self._last_fetch_ts

    @property
    def last_quality_report(self) -> QualityReport | None:
        """Most recent data quality report, if quality checks are enabled."""
        return self._last_quality_report

    def stats(self) -> dict:
        """Return feed statistics."""
        return {
            "last_fetch_ts": self.last_fetch_ts,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "quality_healthy": (
                self._last_quality_report.is_healthy
                if self._last_quality_report is not None
                else None
            ),
        }
