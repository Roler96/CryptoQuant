"""OHLCV data fetcher — ccxt wrapper for exchange data."""

import time

import ccxt
import pandas as pd

from cryptoquant.exceptions import DataFetchError, DataValidationError


def validate_ohlcv(df: pd.DataFrame) -> None:
    """Validate OHLCV data integrity.

    Raises:
        DataValidationError: If data fails validation checks.
    """
    if df.empty:
        return

    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataValidationError(f"Missing columns: {missing}")

    # high >= low
    mask = df["high"] < df["low"]
    if mask.any():
        raise DataValidationError(f"high < low at {mask.sum()} bars")

    # open/close within [low, high]
    for col in ("open", "close"):
        mask = (df[col] < df["low"]) | (df[col] > df["high"])
        if mask.any():
            raise DataValidationError(f"{col} outside [low, high] at {mask.sum()} bars")

    # volume >= 0
    if (df["volume"] < 0).any():
        raise DataValidationError("Negative volume detected")

    # no NaN in critical columns
    for col in required:
        if df[col].isna().any():
            raise DataValidationError(f"NaN in column '{col}'")


class OHLCVFetcher:
    """Fetch OHLCV candles from exchange via ccxt.

    Phase 1: Public endpoints only (no API key needed for OHLCV).
    """

    def __init__(
        self,
        exchange: str = "okx",
        testnet: bool = True,
        timeout: int = 30_000,
    ):
        exchange_class = getattr(ccxt, exchange)
        self.exchange: ccxt.Exchange = exchange_class(
            {
                "enableRateLimit": True,
                "timeout": timeout,
                "options": {"defaultType": "spot"},
            }
        )
        self.exchange_name = exchange
        if testnet:
            self.exchange.set_sandbox_mode(True)

    def fetch(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 300,
        since: int | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles and return as DataFrame.

        Args:
            symbol: Trading pair, e.g. 'BTC/USDT'
            timeframe: '1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'
            limit: Number of candles (1-300 for OKX)
            since: Unix timestamp in ms

        Returns:
            DataFrame with columns [open, high, low, close, volume],
            DatetimeIndex (UTC, no timezone), sorted ascending.

        Raises:
            DataFetchError: If exchange request fails.
            DataValidationError: If returned data fails validation.
        """
        try:
            raw = self.exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, limit=limit, since=since
            )
        except ccxt.BadSymbol as e:
            raise DataFetchError(f"Invalid symbol: {symbol}") from e
        except ccxt.NetworkError as e:
            raise DataFetchError(f"Network error: {e}") from e
        except ccxt.RateLimitExceeded as e:
            raise DataFetchError(f"Rate limit exceeded: {e}") from e
        except ccxt.ExchangeError as e:
            raise DataFetchError(f"Exchange error: {e}") from e

        if not raw:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        df = df[["open", "high", "low", "close", "volume"]]
        df = df.astype(
            {
                "open": "float64",
                "high": "float64",
                "low": "float64",
                "close": "float64",
                "volume": "float64",
            }
        )
        # Ensure UTC without timezone
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        validate_ohlcv(df)
        return df

    def fetch_range(
        self,
        symbol: str,
        timeframe: str,
        start: int,
        end: int,
    ) -> pd.DataFrame:
        """Fetch OHLCV data for a time range, chunking as needed.

        Args:
            symbol: Trading pair
            timeframe: K-line period
            start: Start time (Unix ms, inclusive)
            end: End time (Unix ms, inclusive)

        Returns:
            Concatenated DataFrame, deduplicated and sorted.
        """
        max_candles = 300
        chunks: list[pd.DataFrame] = []
        cursor = start

        while cursor < end:
            df = self.fetch(symbol, timeframe, limit=max_candles, since=cursor)
            if df.empty:
                break
            chunks.append(df)
            # Advance cursor past last candle
            cursor = int(df.index[-1].timestamp() * 1000) + 1
            time.sleep(0.2)  # Respect rate limits

        if not chunks:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        result = pd.concat(chunks)
        result = result[~result.index.duplicated(keep="last")]
        result.sort_index(inplace=True)

        # Filter to requested range
        start_ts = pd.Timestamp(start, unit="ms")
        end_ts = pd.Timestamp(end, unit="ms")
        result = result[(result.index >= start_ts) & (result.index <= end_ts)]

        return result
