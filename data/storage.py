"""Historical data storage module for CryptoQuant platform.

Provides Parquet-based storage for OHLCV data with:
- Incremental updates (append new data without duplicates)
- Metadata tracking (last_update, data_source, pair, timeframe)
- Snappy compression for efficient storage
- DataFrame loading for analysis and backtesting
"""

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from data.models import OHLCVCandle

logger = structlog.get_logger(__name__)

# Default paths
DEFAULT_DATA_DIR = Path("data/historical")
METADATA_FILE = "metadata.json"


def _normalize_pair(pair: str) -> str:
    """Normalize pair string for filename.

    Args:
        pair: Trading pair (e.g., "BTC/USDT")

    Returns:
        Lowercase pair with / replaced by _ (e.g., "btc_usdt")
    """
    return pair.lower().replace("/", "_")


def _get_parquet_path(pair: str, timeframe: str, data_dir: Optional[Path] = None) -> Path:
    """Get the Parquet file path for a given pair and timeframe.

    Args:
        pair: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "1h", "1d")
        data_dir: Optional custom data directory

    Returns:
        Path to the Parquet file
    """
    directory = data_dir or DEFAULT_DATA_DIR
    normalized_pair = _normalize_pair(pair)
    filename = f"{normalized_pair}_{timeframe}.parquet"
    return directory / filename


def _get_metadata_path(data_dir: Optional[Path] = None) -> Path:
    """Get the metadata file path.

    Args:
        data_dir: Optional custom data directory

    Returns:
        Path to the metadata JSON file
    """
    directory = data_dir or DEFAULT_DATA_DIR
    return directory / METADATA_FILE


def _candles_to_dataframe(candles: List[OHLCVCandle]) -> pd.DataFrame:
    """Convert list of OHLCVCandle to pandas DataFrame.

    Args:
        candles: List of OHLCVCandle objects

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    if not candles:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    data = {
        "timestamp": [c.timestamp for c in candles],
        "open": [float(c.open_price) for c in candles],
        "high": [float(c.high_price) for c in candles],
        "low": [float(c.low_price) for c in candles],
        "close": [float(c.close_price) for c in candles],
        "volume": [float(c.volume) for c in candles],
    }

    return pd.DataFrame(data)


def _dataframe_to_candles(df: pd.DataFrame, pair: str, timeframe: str) -> List[OHLCVCandle]:
    """Convert DataFrame back to list of OHLCVCandle objects.

    Args:
        df: DataFrame with OHLCV columns
        pair: Trading pair symbol
        timeframe: Candle timeframe

    Returns:
        List of OHLCVCandle objects
    """
    candles = []
    for _, row in df.iterrows():
        candles.append(
            OHLCVCandle(
                timestamp=int(row["timestamp"]),
                open_price=Decimal(str(row["open"])),
                high_price=Decimal(str(row["high"])),
                low_price=Decimal(str(row["low"])),
                close_price=Decimal(str(row["close"])),
                volume=Decimal(str(row["volume"])),
                pair=pair,
                timeframe=timeframe,
            )
        )
    return candles


def _ensure_data_directory(data_dir: Optional[Path] = None) -> Path:
    """Ensure the data directory exists.

    Args:
        data_dir: Optional custom data directory

    Returns:
        Path to the data directory
    """
    directory = data_dir or DEFAULT_DATA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _load_metadata(data_dir: Optional[Path] = None) -> Dict:
    """Load metadata from JSON file.

    Args:
        data_dir: Optional custom data directory

    Returns:
        Metadata dictionary
    """
    metadata_path = _get_metadata_path(data_dir)

    if metadata_path.exists():
        try:
            with open(metadata_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("failed_to_load_metadata", error=str(e))
            return {"files": {}}

    return {"files": {}}


def _save_metadata(metadata: Dict, data_dir: Optional[Path] = None) -> None:
    """Save metadata to JSON file.

    Args:
        metadata: Metadata dictionary
        data_dir: Optional custom data directory
    """
    metadata_path = _get_metadata_path(data_dir)
    _ensure_data_directory(data_dir)

    try:
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
    except IOError as e:
        logger.error("failed_to_save_metadata", error=str(e))
        raise


def _update_metadata_entry(
    pair: str,
    timeframe: str,
    row_count: int,
    data_source: str = "okx",
    data_dir: Optional[Path] = None,
) -> None:
    """Update metadata entry for a specific pair/timeframe.

    Args:
        pair: Trading pair
        timeframe: Candle timeframe
        row_count: Number of rows in the data
        data_source: Data source identifier
        data_dir: Optional custom data directory
    """
    metadata = _load_metadata(data_dir)

    key = f"{_normalize_pair(pair)}_{timeframe}"
    parquet_path = _get_parquet_path(pair, timeframe, data_dir)

    metadata["files"][key] = {
        "pair": pair,
        "timeframe": timeframe,
        "last_update_timestamp": datetime.utcnow().isoformat(),
        "data_source": data_source,
        "rows_count": row_count,
        "file_path": str(parquet_path.relative_to(Path.cwd())),
    }

    _save_metadata(metadata, data_dir)
    logger.debug("metadata_updated", pair=pair, timeframe=timeframe, rows=row_count)


def save_historical_data(
    candles: List[OHLCVCandle],
    pair: str,
    timeframe: str,
    data_source: str = "okx",
    data_dir: Optional[Path] = None,
) -> Path:
    """Save OHLCV candles to Parquet file with incremental update support.

    This function:
    1. Reads existing data if the file exists
    2. Combines old and new data
    3. Removes duplicate timestamps (keeps newest)
    4. Sorts by timestamp ascending
    5. Writes back with snappy compression
    6. Updates metadata

    Args:
        candles: List of OHLCVCandle objects to save
        pair: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "1h", "1d")
        data_source: Data source identifier (default: "okx")
        data_dir: Optional custom data directory

    Returns:
        Path to the saved Parquet file

    Raises:
        ValueError: If candles is empty and no existing file
        IOError: If file operations fail
    """
    if not candles:
        logger.warning("empty_candles_list", pair=pair, timeframe=timeframe)
        raise ValueError(f"Cannot save empty candles list for {pair} {timeframe}")

    # Ensure directory exists
    _ensure_data_directory(data_dir)

    parquet_path = _get_parquet_path(pair, timeframe, data_dir)

    # Convert new candles to DataFrame
    new_df = _candles_to_dataframe(candles)

    if new_df.empty:
        logger.warning("empty_dataframe_after_conversion", pair=pair, timeframe=timeframe)
        raise ValueError(f"Failed to convert candles to DataFrame for {pair} {timeframe}")

    # Check for existing data
    if parquet_path.exists():
        logger.debug("existing_file_found", path=str(parquet_path))
        try:
            existing_df = pd.read_parquet(parquet_path)

            # Combine old and new data
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)

            # Remove duplicates based on timestamp (keep last = newest)
            combined_df = combined_df.drop_duplicates(subset=["timestamp"], keep="last")

            # Sort by timestamp ascending
            combined_df = combined_df.sort_values(by="timestamp", ascending=True).reset_index(drop=True)

            final_df = combined_df
            logger.info(
                "incremental_update",
                pair=pair,
                timeframe=timeframe,
                existing_rows=len(existing_df),
                new_rows=len(new_df),
                final_rows=len(final_df),
            )
        except Exception as e:
            logger.error("failed_to_read_existing_data", error=str(e))
            # If we can't read existing data, just use new data
            final_df = new_df.sort_values(by="timestamp", ascending=True).reset_index(drop=True)
    else:
        # No existing file, just sort new data
        final_df = new_df.sort_values(by="timestamp", ascending=True).reset_index(drop=True)
        logger.info(
            "new_file_created",
            pair=pair,
            timeframe=timeframe,
            rows=len(final_df),
        )

    # Write to Parquet with snappy compression
    try:
        table = pa.Table.from_pandas(final_df)
        pq.write_table(table, parquet_path, compression="snappy")
        logger.info(
            "parquet_file_saved",
            path=str(parquet_path),
            rows=len(final_df),
            size_bytes=parquet_path.stat().st_size,
        )
    except Exception as e:
        logger.error("failed_to_write_parquet", error=str(e))
        raise IOError(f"Failed to write Parquet file: {e}")

    # Update metadata
    _update_metadata_entry(pair, timeframe, len(final_df), data_source, data_dir)

    return parquet_path


def load_historical_data(
    pair: str,
    timeframe: str,
    data_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Load historical OHLCV data from Parquet file.

    Args:
        pair: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "1h", "1d")
        data_dir: Optional custom data directory

    Returns:
        pandas DataFrame with columns: timestamp, open, high, low, close, volume
        Sorted by timestamp ascending. Returns empty DataFrame if file doesn't exist.

    Raises:
        FileNotFoundError: If the Parquet file doesn't exist
    """
    parquet_path = _get_parquet_path(pair, timeframe, data_dir)

    if not parquet_path.exists():
        logger.warning("parquet_file_not_found", path=str(parquet_path))
        raise FileNotFoundError(f"No historical data file found for {pair} {timeframe}: {parquet_path}")

    try:
        df = pd.read_parquet(parquet_path)

        # Ensure expected columns exist
        expected_columns = ["timestamp", "open", "high", "low", "close", "volume"]
        missing_columns = [col for col in expected_columns if col not in df.columns]

        if missing_columns:
            logger.error("missing_columns_in_parquet", columns=missing_columns)
            raise ValueError(f"Parquet file missing required columns: {missing_columns}")

        # Ensure sorted by timestamp
        df = df.sort_values(by="timestamp", ascending=True).reset_index(drop=True)

        logger.debug(
            "historical_data_loaded",
            pair=pair,
            timeframe=timeframe,
            rows=len(df),
            columns=list(df.columns),
        )

        return df

    except Exception as e:
        logger.error("failed_to_load_historical_data", error=str(e))
        raise


def load_historical_candles(
    pair: str,
    timeframe: str,
    data_dir: Optional[Path] = None,
) -> List[OHLCVCandle]:
    """Load historical OHLCV data as list of OHLCVCandle objects.

    Args:
        pair: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "1h", "1d")
        data_dir: Optional custom data directory

    Returns:
        List of OHLCVCandle objects sorted by timestamp ascending

    Raises:
        FileNotFoundError: If the Parquet file doesn't exist
    """
    df = load_historical_data(pair, timeframe, data_dir)
    return _dataframe_to_candles(df, pair, timeframe)


def get_metadata(data_dir: Optional[Path] = None) -> Dict:
    """Get metadata for all stored historical data files.

    Args:
        data_dir: Optional custom data directory

    Returns:
        Metadata dictionary with file information
    """
    return _load_metadata(data_dir)


def get_data_info(
    pair: str,
    timeframe: str,
    data_dir: Optional[Path] = None,
) -> Optional[Dict]:
    """Get metadata information for a specific pair/timeframe.

    Args:
        pair: Trading pair
        timeframe: Candle timeframe
        data_dir: Optional custom data directory

    Returns:
        Metadata dict for the specific file, or None if not found
    """
    metadata = _load_metadata(data_dir)
    key = f"{_normalize_pair(pair)}_{timeframe}"
    return metadata.get("files", {}).get(key)


def delete_historical_data(
    pair: str,
    timeframe: str,
    data_dir: Optional[Path] = None,
) -> bool:
    """Delete historical data file and update metadata.

    Args:
        pair: Trading pair
        timeframe: Candle timeframe
        data_dir: Optional custom data directory

    Returns:
        True if file was deleted, False if file didn't exist
    """
    parquet_path = _get_parquet_path(pair, timeframe, data_dir)

    deleted = False
    if parquet_path.exists():
        try:
            parquet_path.unlink()
            deleted = True
            logger.info("historical_data_deleted", pair=pair, timeframe=timeframe)
        except OSError as e:
            logger.error("failed_to_delete_file", error=str(e))
            raise

    # Update metadata
    metadata = _load_metadata(data_dir)
    key = f"{_normalize_pair(pair)}_{timeframe}"
    if key in metadata.get("files", {}):
        del metadata["files"][key]
        _save_metadata(metadata, data_dir)

    return deleted


def list_available_data(data_dir: Optional[Path] = None) -> List[Dict]:
    """List all available historical data files.

    Args:
        data_dir: Optional custom data directory

    Returns:
        List of metadata dictionaries for all stored files
    """
    metadata = _load_metadata(data_dir)
    return list(metadata.get("files", {}).values())


def get_last_timestamp(
    pair: str,
    timeframe: str,
    data_dir: Optional[Path] = None,
) -> Optional[int]:
    """Get the last (most recent) timestamp in stored data.

    Args:
        pair: Trading pair
        timeframe: Candle timeframe
        data_dir: Optional custom data directory

    Returns:
        Last timestamp in milliseconds, or None if no data exists
    """
    try:
        df = load_historical_data(pair, timeframe, data_dir)
        if df.empty:
            return None
        return int(df["timestamp"].max())
    except FileNotFoundError:
        return None


def check_data_exists(
    pair: str,
    timeframe: str,
    data_dir: Optional[Path] = None,
) -> bool:
    """Check if historical data exists for a given pair/timeframe.

    Args:
        pair: Trading pair
        timeframe: Candle timeframe
        data_dir: Optional custom data directory

    Returns:
        True if data file exists, False otherwise
    """
    parquet_path = _get_parquet_path(pair, timeframe, data_dir)
    return parquet_path.exists()
