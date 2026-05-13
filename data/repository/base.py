"""Abstract data repository interface for CryptoQuant platform.

Defines the contract for OHLCV data storage backends. The repository pattern
decouples business logic from storage implementation details.

Implementations must support:
- Batch upsert (insert or replace) to avoid duplicates
- Time-range queries for backtesting
- DataFrame output for Backtrader integration
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import pandas as pd
import structlog

from data.models import OHLCVCandle

logger = structlog.get_logger(__name__)


class DataRepository(ABC):
    """Abstract data repository for OHLCV candle storage.

    All implementations must support:
    - Batch upsert (insert or replace) to avoid duplicates
    - Time-range queries for backtesting
    - DataFrame output for Backtrader integration
    """

    # ---- Core CRUD (abstract) ----

    @abstractmethod
    def save_candles(
        self,
        candles: List[OHLCVCandle],
        pair: str,
        timeframe: str,
    ) -> int:
        """Save candles with upsert semantics (duplicate timestamps replaced).

        Args:
            candles: List of OHLCV candle objects to save
            pair: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (e.g., "1h", "4h")

        Returns:
            Number of candles saved/updated
        """

    @abstractmethod
    def load_candles(
        self,
        pair: str,
        timeframe: str,
        since: Optional[int] = None,
        until: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[OHLCVCandle]:
        """Load candles as OHLCVCandle objects.

        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            since: Start timestamp in ms (inclusive)
            until: End timestamp in ms (inclusive)
            limit: Maximum number of candles to return

        Returns:
            List of OHLCVCandle sorted by timestamp ascending
        """

    @abstractmethod
    def load_as_dataframe(
        self,
        pair: str,
        timeframe: str,
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> pd.DataFrame:
        """Load candles as pandas DataFrame for backtest engine.

        DataFrame columns: timestamp, open, high, low, close, volume

        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            since: Start timestamp in ms (inclusive)
            until: End timestamp in ms (inclusive)

        Returns:
            DataFrame sorted by timestamp ascending
        """

    @abstractmethod
    def get_latest_timestamp(self, pair: str, timeframe: str) -> Optional[int]:
        """Get the most recent timestamp for a pair/timeframe.

        Used for incremental data fetching.

        Args:
            pair: Trading pair
            timeframe: Candle timeframe

        Returns:
            Latest timestamp in ms, or None if no data exists
        """

    @abstractmethod
    def get_earliest_timestamp(self, pair: str, timeframe: str) -> Optional[int]:
        """Get the oldest timestamp for a pair/timeframe.

        Args:
            pair: Trading pair
            timeframe: Candle timeframe

        Returns:
            Earliest timestamp in ms, or None if no data exists
        """

    @abstractmethod
    def count(self, pair: str, timeframe: str) -> int:
        """Count candles for a pair/timeframe.

        Args:
            pair: Trading pair
            timeframe: Candle timeframe

        Returns:
            Number of stored candles
        """

    @abstractmethod
    def exists(self, pair: str, timeframe: str) -> bool:
        """Check if any data exists for a pair/timeframe.

        Args:
            pair: Trading pair
            timeframe: Candle timeframe

        Returns:
            True if data exists
        """

    @abstractmethod
    def delete(
        self,
        pair: str,
        timeframe: str,
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> int:
        """Delete candles for a pair/timeframe.

        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            since: Start timestamp to delete from (inclusive)
            until: End timestamp to delete to (inclusive)

        Returns:
            Number of deleted rows
        """

    @abstractmethod
    def list_pairs_timeframes(self) -> List[tuple]:
        """Return list of (pair, timeframe) tuples that have stored data.

        Used by list_all() to enumerate all stored datasets.

        Returns:
            List of (pair, timeframe) tuples
        """

    # ---- Convenience methods built on the abstract interface ----

    def get_stats(self, pair: str, timeframe: str) -> Dict[str, Any]:
        """Get summary statistics for a pair/timeframe.

        Args:
            pair: Trading pair
            timeframe: Candle timeframe

        Returns:
            Dict with count, min_timestamp, max_timestamp, pair, timeframe
        """
        return {
            "pair": pair,
            "timeframe": timeframe,
            "count": self.count(pair, timeframe),
            "min_timestamp": self.get_earliest_timestamp(pair, timeframe),
            "max_timestamp": self.get_latest_timestamp(pair, timeframe),
        }

    def list_all(self) -> List[Dict[str, Any]]:
        """List all available pair/timeframe combinations with stats.

        Returns:
            List of stat dictionaries for each stored pair/timeframe
        """
        pairs_tfs = self.list_pairs_timeframes()
        return [self.get_stats(pair, tf) for pair, tf in pairs_tfs]

    def close(self) -> None:
        """Release resources held by this repository. Override if needed."""
        pass
