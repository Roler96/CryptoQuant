"""Data loader for multi-asset backtesting.

Loads OHLCV data for multiple trading pairs from SQLite repository,
aligns timestamps, and prepares data for vectorized backtesting.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import structlog

from data.repository import get_repository

logger = structlog.get_logger(__name__)


class MultiAssetDataLoader:
    """Loads and aligns OHLCV data for multiple assets.

    Features:
    - Loads data for multiple pairs from SQLite
    - Aligns timestamps across all assets
    - Filters by date range
    - Handles missing data gracefully
    """

    def __init__(self):
        """Initialize data loader."""
        self.repo = get_repository()
        self.logger = structlog.get_logger(__name__)

    def load_data(
        self,
        pairs: List[str],
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Load OHLCV data for multiple pairs and align by timestamp.

        Args:
            pairs: List of trading pairs (e.g., ["BTC/USDT", "ETH/USDT"])
            timeframe: Candle timeframe (e.g., "1h", "4h")
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            Multi-index DataFrame with (timestamp, pair) index and
            columns: open, high, low, close, volume
        """
        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

        all_data: List[pd.DataFrame] = []
        valid_pairs: List[str] = []

        for pair in pairs:
            df = self.repo.load_as_dataframe(pair, timeframe, since=start_ts, until=end_ts)

            if df.empty:
                self.logger.warning("no_data_for_pair", pair=pair)
                continue

            df["pair"] = pair
            valid_pairs.append(pair)
            all_data.append(df)

        if not all_data:
            raise ValueError(f"No data found for any of the requested pairs: {pairs}")

        # Concatenate all dataframes
        combined = pd.concat(all_data, ignore_index=True)

        # Create multi-index (timestamp, pair)
        combined = combined.set_index(["timestamp", "pair"]).sort_index()

        self.logger.info(
            "data_loaded",
            pairs=len(valid_pairs),
            timeframe=timeframe,
            rows=len(combined),
            start_date=start_date,
            end_date=end_date,
        )

        return combined

    def get_close_prices(
        self,
        pairs: List[str],
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Load close prices as a timestamp-by-pair matrix.

        Args:
            pairs: List of trading pairs
            timeframe: Candle timeframe
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with timestamp index and pair columns, values are close prices
        """
        df = self.load_data(pairs, timeframe, start_date, end_date)

        # Pivot to get close prices
        close_prices = df["close"].unstack("pair")

        # Forward fill missing values (handle gaps)
        close_prices = close_prices.ffill()

        return close_prices

    def get_returns(
        self,
        pairs: List[str],
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Load percentage returns for all pairs.

        Args:
            pairs: List of trading pairs
            timeframe: Candle timeframe
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with timestamp index and pair columns, values are percentage returns
        """
        close_prices = self.get_close_prices(pairs, timeframe, start_date, end_date)

        # Calculate percentage returns
        returns = close_prices.pct_change()

        return returns

    def get_available_pairs(self) -> List[str]:
        """Get list of all pairs with data in repository."""
        pairs_timeframes = self.repo.list_pairs_timeframes()
        pairs = [p for p, tf in pairs_timeframes]
        return list(set(pairs))


def download_missing_pairs(
    pairs: List[str],
    timeframe: str,
    start_date: str,
    end_date: str,
    sandbox: bool = True,
) -> None:
    """Download data for pairs not yet in repository.

    Args:
        pairs: List of pairs to download
        timeframe: Candle timeframe
        start_date: Start date
        end_date: End date
        sandbox: Use sandbox mode (default True)
    """
    from data.manager import OKXClient
    import time

    repo = get_repository()
    logger = structlog.get_logger(__name__)

    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

    try:
        client = OKXClient(sandbox=sandbox)
    except Exception as e:
        logger.error("failed_to_init_client", error=str(e))
        return

    for pair in pairs:
        if repo.exists(pair, timeframe):
            logger.info("data_exists", pair=pair, timeframe=timeframe)
            continue

        logger.info("downloading_pair", pair=pair, timeframe=timeframe)

        try:
            candles = client.fetch_ohlcv_history(
                symbol=pair,
                timeframe=timeframe,
                since=start_ts,
                until=end_ts,
            )

            if candles:
                repo.save_candles(candles, pair, timeframe)
                logger.info("downloaded", pair=pair, count=len(candles))
            else:
                logger.warning("no_data_returned", pair=pair)

        except Exception as e:
            logger.error("download_failed", pair=pair, error=str(e))

        time.sleep(0.5)  # Rate limiting

    client.close()