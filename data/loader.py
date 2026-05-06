"""Data loader with support for both file and database storage."""

import os
from typing import List, Optional

import structlog
import yaml

from data.database import DatabaseManager, close_database, init_database
from data.models import OHLCVCandle
from data.storage import load_historical_data as load_from_file
from data.storage import save_historical_data as save_to_file

logger = structlog.get_logger(__name__)


def get_storage_config() -> dict:
    """Get storage configuration from config file."""
    config_path = os.getenv("CONFIG_PATH", "config/config.yaml")
    
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = yaml.safe_load(f)
            return config.get("data", {})
    
    return {
        "storage_mode": "file",
        "historical_path": "data/historical",
        "database": {
            "url": "sqlite:///data/cryptoquant.db",
            "pool_size": 5,
        },
    }


def use_database() -> bool:
    """Check if database storage is enabled."""
    config = get_storage_config()
    return config.get("storage_mode", "file") == "database"


def load_candles(
    pair: str,
    timeframe: str,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[OHLCVCandle]:
    """Load candles from storage (file or database).
    
    Args:
        pair: Trading pair
        timeframe: Candle timeframe
        start_time: Start timestamp
        end_time: End timestamp
        limit: Maximum number of candles
        
    Returns:
        List of OHLCVCandle objects
    """
    if use_database():
        db = init_database()
        
        rows = db.get_candles(
            pair=pair,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        
        return [
            OHLCVCandle(
                timestamp=row["timestamp"],
                open_price=row["open"],
                high_price=row["high"],
                low_price=row["low"],
                close_price=row["close"],
                volume=row["volume"],
                pair=pair,
                timeframe=timeframe,
            )
            for row in rows
        ]
    else:
        df = load_from_file(pair, timeframe)
        
        if start_time:
            df = df[df["timestamp"] >= start_time]
        if end_time:
            df = df[df["timestamp"] <= end_time]
        if limit:
            df = df.tail(limit)
        
        return [
            OHLCVCandle(
                timestamp=row["timestamp"],
                open_price=row["open"],
                high_price=row["high"],
                low_price=row["low"],
                close_price=row["close"],
                volume=row["volume"],
                pair=pair,
                timeframe=timeframe,
            )
            for _, row in df.iterrows()
        ]


def save_candles(
    candles: List[OHLCVCandle],
    pair: str,
    timeframe: str,
    data_source: str = "OKX",
) -> int:
    """Save candles to storage (file or database).
    
    Args:
        candles: List of OHLCVCandle objects
        pair: Trading pair
        timeframe: Candle timeframe
        data_source: Data source name
        
    Returns:
        Number of candles saved
    """
    if not candles:
        return 0
    
    if use_database():
        db = init_database()
        
        rows = [
            {
                "timestamp": c.timestamp,
                "open": c.open_price,
                "high": c.high_price,
                "low": c.low_price,
                "close": c.close_price,
                "volume": c.volume,
            }
            for c in candles
        ]
        
        return db.save_candles(rows, pair, timeframe)
    else:
        save_to_file(candles, pair, timeframe, data_source)
        return len(candles)


def get_latest_timestamp(pair: str, timeframe: str) -> Optional[int]:
    """Get the latest timestamp for a pair and timeframe.
    
    Args:
        pair: Trading pair
        timeframe: Candle timeframe
        
    Returns:
        Latest timestamp or None
    """
    if use_database():
        db = init_database()
        candle = db.get_latest_candle(pair, timeframe)
        return candle["timestamp"] if candle else None
    else:
        try:
            df = load_from_file(pair, timeframe)
            return int(df["timestamp"].max()) if not df.empty else None
        except FileNotFoundError:
            return None


def get_data_stats(pair: str, timeframe: str) -> dict:
    """Get data statistics.
    
    Args:
        pair: Trading pair
        timeframe: Candle timeframe
        
    Returns:
        Dictionary with statistics
    """
    if use_database():
        db = init_database()
        count = db.get_candles_count(pair, timeframe)
        min_ts, max_ts = db.get_time_range(pair, timeframe)
        
        return {
            "count": count,
            "min_timestamp": min_ts,
            "max_timestamp": max_ts,
            "storage": "database",
        }
    else:
        try:
            df = load_from_file(pair, timeframe)
            return {
                "count": len(df),
                "min_timestamp": int(df["timestamp"].min()),
                "max_timestamp": int(df["timestamp"].max()),
                "storage": "file",
            }
        except FileNotFoundError:
            return {
                "count": 0,
                "min_timestamp": None,
                "max_timestamp": None,
                "storage": "file",
            }


class IncrementalUpdater:
    """Incremental data updater for efficient downloads."""
    
    def __init__(self):
        self.config = get_storage_config()
    
    def should_update(
        self,
        pair: str,
        timeframe: str,
        max_age_hours: float = 1.0,
    ) -> bool:
        """Check if data should be updated.
        
        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            max_age_hours: Maximum age before update needed
            
        Returns:
            True if update needed
        """
        from datetime import datetime, timedelta, timezone
        
        latest_ts = get_latest_timestamp(pair, timeframe)
        
        if latest_ts is None:
            return True
        
        latest_dt = datetime.fromtimestamp(latest_ts / 1000, tz=timezone.utc)
        age = datetime.now(timezone.utc) - latest_dt
        
        return age > timedelta(hours=max_age_hours)
    
    def get_fetch_range(
        self,
        pair: str,
        timeframe: str,
        days: int = 365,
    ) -> tuple[int, int]:
        """Get the timestamp range to fetch.
        
        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            days: Default number of days to fetch
            
        Returns:
            Tuple of (start_timestamp, end_timestamp)
        """
        from datetime import datetime, timedelta, timezone
        
        latest_ts = get_latest_timestamp(pair, timeframe)
        
        if latest_ts:
            # Fetch from latest to now
            start_ts = latest_ts + 1
        else:
            # Fetch last N days
            start_dt = datetime.now(timezone.utc) - timedelta(days=days)
            start_ts = int(start_dt.timestamp() * 1000)
        
        end_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        
        return start_ts, end_ts
