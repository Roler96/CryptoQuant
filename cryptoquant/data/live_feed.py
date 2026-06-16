"""Live data feed for real-time trading."""

import pandas as pd

from cryptoquant.data.fetcher import OHLCVFetcher
from cryptoquant.data.store import OHLCVStore


class LiveDataFeed:
    """Fetches and stores live OHLCV data for a single symbol."""

    def __init__(
        self,
        fetcher: OHLCVFetcher,
        store: OHLCVStore,
        exchange: str,
        symbol: str,
        timeframe: str,
    ):
        self.fetcher = fetcher
        self.store = store
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self._last_fetch_ts: int = 0

    def fetch(self, lookback: int) -> pd.DataFrame:
        """Fetch recent OHLCV data and persist to store."""
        df = self.fetcher.fetch(
            self.symbol, self.timeframe, limit=min(lookback, 300)
        )
        if not df.empty:
            self.store.save(df, self.exchange, self.symbol, self.timeframe)
            self._last_fetch_ts = int(df.index[-1].timestamp() * 1000)
        return df

    @property
    def last_fetch_ts(self) -> int:
        """Unix ms of last successful fetch, or 0 if never fetched."""
        return self._last_fetch_ts

    def stats(self) -> dict:
        """Return feed statistics."""
        return {
            "last_fetch_ts": self.last_fetch_ts,
            "exchange": self.exchange,
            "symbol": self.symbol,
        }
