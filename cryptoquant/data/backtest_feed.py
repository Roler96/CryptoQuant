"""Backtest data feed for historical data loading."""

import pandas as pd

from cryptoquant.data.fetcher import OHLCVFetcher
from cryptoquant.data.store import OHLCVStore


class BacktestDataFeed:
    """Loads and fetches historical OHLCV data for backtesting."""

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

    def load(
        self, start: int | None = None, end: int | None = None
    ) -> pd.DataFrame:
        """Load OHLCV data from store for a time range."""
        return self.store.load(
            self.exchange, self.symbol, self.timeframe, start=start, end=end
        )

    def fetch_range(self, start: int, end: int) -> pd.DataFrame:
        """Fetch OHLCV data for a time range and persist to store."""
        df = self.fetcher.fetch_range(
            self.symbol, self.timeframe, start, end
        )
        if not df.empty:
            self.store.save(df, self.exchange, self.symbol, self.timeframe)
        return df
