"""Live data feed for real-time trading."""

import time as _time

import pandas as pd
from loguru import logger

from cryptoquant.data.fetcher import OHLCVFetcher, validate_ohlcv
from cryptoquant.data.quality import DataQualityChecker, QualityReport
from cryptoquant.data.store import OHLCVStore
from cryptoquant.exceptions import DataValidationError


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

    def fetch(self, lookback: int) -> pd.DataFrame:
        """Fetch recent OHLCV data, validate it, and persist to store."""
        df = self.fetcher.fetch(
            self.symbol, self.timeframe, limit=min(lookback, 300)
        )
        if df.empty:
            self._last_quality_report = None
            return df

        validate_ohlcv(df, strict=self.strict_validation)
        if self.quality_check:
            self._last_quality_report = DataQualityChecker(df).check()
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
        self.store.save(df, self.exchange, self.symbol, self.timeframe)
        self._last_fetch_ts = int(_time.time() * 1000)
        return df

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
