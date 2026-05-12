"""Data models for CryptoQuant platform.

Core OHLCV candle model aligned with the SQLite schema:
    candles (pair, timeframe, timestamp, iso_time, open, high, low, close, volume)

Field names match DB column names exactly -- no mapping layer needed.
All prices/volumes use Decimal for exact precision.
Timestamps are milliseconds (Unix epoch). iso_time is UTC ISO 8601.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass(frozen=True)
class OHLCVCandle:
    """OHLCV candlestick data.

    Fields match the SQLite `candles` table 1:1.

    Attributes:
        pair: Trading pair symbol (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "1h", "1d")
        timestamp: Unix timestamp in milliseconds
        open: Opening price
        high: Highest price during the period
        low: Lowest price during the period
        close: Closing price
        volume: Trading volume
    """
    pair: str
    timeframe: str
    timestamp: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @property
    def iso_time(self) -> str:
        """ISO 8601 UTC string (e.g., '2024-05-12T14:00:00+00:00').

        Derived from timestamp, always UTC. Stored as iso_time column in DB.
        """
        dt = datetime.fromtimestamp(self.timestamp / 1000, tz=timezone.utc)
        return dt.isoformat()
