"""OHLCV data fetcher — ccxt wrapper for exchange data."""

import os

import ccxt
import pandas as pd
from loguru import logger

from cryptoquant.exceptions import DataFetchError, DataValidationError
from cryptoquant.execution.broker import retry_on_network


def _get_proxy_from_env() -> str | None:
    """Get proxy URL from environment variables."""
    return (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )


def validate_ohlcv(df: pd.DataFrame, strict: bool = False) -> None:
    """Validate OHLCV data integrity.

    Checks:
    - Required columns present
    - high >= low for all bars
    - open/close within [low, high]
    - volume >= 0
    - no NaN in critical columns
    - timestamp continuity (warn by default, raise when strict=True)

    Args:
        df: OHLCV DataFrame to validate.
        strict: If True, timestamp gaps raise DataValidationError.
            If False, gaps are logged as warnings only.

    Raises:
        DataValidationError: If data fails validation checks.
    """
    if df.empty:
        return

    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataValidationError(f"Missing columns: {missing}")

    mask = df["high"] < df["low"]
    if mask.any():
        raise DataValidationError(f"high < low at {mask.sum()} bars")

    for col in ("open", "close"):
        mask = (df[col] < df["low"]) | (df[col] > df["high"])
        if mask.any():
            raise DataValidationError(f"{col} outside [low, high] at {mask.sum()} bars")

    if (df["volume"] < 0).any():
        raise DataValidationError("Negative volume detected")

    for col in required:
        if df[col].isna().any():
            raise DataValidationError(f"NaN in column '{col}'")

    if len(df) >= 2 and isinstance(df.index, pd.DatetimeIndex):
        diffs = df.index.to_series().diff().dropna()
        if len(diffs) > 0:
            median_diff = diffs.median()
            gaps = diffs[diffs > median_diff * 1.1]
            if len(gaps) > 0:
                msg = (
                    f"Detected {len(gaps)} gap(s) in OHLCV timestamps, "
                    f"e.g. at {gaps.index[0]} (diff={gaps.iloc[0]})"
                )
                if strict:
                    raise DataValidationError(msg)
                logger.warning(msg)


class OHLCVFetcher:
    """Fetch OHLCV candles from exchange via ccxt.

    Phase 1: Public endpoints only (no API key needed for OHLCV).

    Args:
        exchange: Exchange name (e.g. 'okx', 'binance')
        testnet: Use sandbox/testnet mode
        timeout: Connection timeout in milliseconds
        max_candles: Max candles per single request (exchange limit)
        proxy: Proxy URL (e.g. 'http://127.0.0.1:7890'). If None, reads from env.
    """

    def __init__(
        self,
        exchange: str = "okx",
        testnet: bool = True,
        timeout: int = 30_000,
        max_candles: int = 300,
        proxy: str | None = None,
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
        self.timeout = timeout
        self.max_candles = max(1, max_candles)
        if testnet:
            self.exchange.set_sandbox_mode(True)

        # Configure proxy - ccxt sets trust_env=False, so we must set proxies manually
        proxy_url = proxy or _get_proxy_from_env()
        if proxy_url:
            self.exchange.session.proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
            logger.debug(f"OHLCVFetcher using proxy: {proxy_url}")

    def available_timeframes(self) -> list[str]:
        """Return list of timeframes supported by this exchange.

        Returns:
            List of timeframe strings (e.g. ['1m', '5m', '1h', '1d'])
        """
        if self.exchange.timeframes:
            return list(self.exchange.timeframes.keys())
        return []

    @retry_on_network(max_retries=3, base_delay=1.0)
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
            limit: Number of candles (clamped to [1, max_candles])
            since: Unix timestamp in ms

        Returns:
            DataFrame with columns [open, high, low, close, volume],
            DatetimeIndex (UTC, no timezone), sorted ascending.

        Raises:
            DataFetchError: If exchange request fails.
            DataValidationError: If returned data fails validation.
        """
        # Clamp limit to valid range [1, max_candles]
        limit = max(1, min(limit, self.max_candles))

        try:
            raw = self.exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, limit=limit, since=since
            )
        except ccxt.BadSymbol as e:
            raise DataFetchError(f"Invalid symbol: {symbol}") from e
        except ccxt.RateLimitExceeded as e:
            raise DataFetchError(f"Rate limit exceeded: {e}") from e
        except ccxt.NetworkError as e:
            raise DataFetchError(f"Network error: {e}") from e
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

        Raises:
            DataFetchError: If any chunk fails after retries.
                Error message includes number of successfully fetched chunks.
        """
        chunks: list[pd.DataFrame] = []
        cursor = start

        while cursor < end:
            try:
                df = self.fetch(symbol, timeframe, limit=self.max_candles, since=cursor)
            except DataFetchError as e:
                # Include progress info in error message
                raise DataFetchError(
                    f"fetch_range failed after {len(chunks)} successful chunk(s): {e}"
                ) from e

            if df.empty:
                break
            chunks.append(df)

            # Advance cursor past last candle.
            # OKX/Binance: timestamp = candle OPEN time. +1ms advances past it.
            # If an exchange uses CLOSE time semantics, this logic needs adjustment.
            cursor = int(df.index[-1].timestamp() * 1000) + 1

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
