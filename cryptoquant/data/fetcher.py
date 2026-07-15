"""OHLCV data fetcher — ccxt wrapper for exchange data."""
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false

import ccxt
import pandas as pd
from loguru import logger

from cryptoquant.exceptions import DataFetchError, DataValidationError
from cryptoquant.utils import (
    REQUIRED_OHLCV_COLUMNS,
    get_proxy_from_env,
    missing_ohlcv_columns,
    retry_on_network,
)

# Fallback probe stride for exchanges whose timeframe we can't measure.
_LEADING_GAP_SKIP_MS = 30 * 86_400_000


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

    missing = missing_ohlcv_columns(df)
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

    for col in REQUIRED_OHLCV_COLUMNS:
        if df[col].isna().sum() > 0:
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
        max_retries: Retry attempts for transient network errors.
        retry_base_delay: Base seconds for retry backoff. Set 0 in tests.
    """

    def __init__(
        self,
        exchange: str = "okx",
        testnet: bool = True,
        timeout: int = 30_000,
        max_candles: int = 300,
        proxy: str | None = None,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        market_type: str = "spot",
    ):
        if market_type not in {"spot", "swap", "future"}:
            raise ValueError(f"Unsupported market_type: {market_type}")
        exchange_class = getattr(ccxt, exchange)
        self.exchange: ccxt.Exchange = exchange_class(
            {
                "enableRateLimit": True,
                "timeout": timeout,
                "options": {"defaultType": market_type},
            }
        )
        self.exchange_name = exchange
        self.market_type = market_type
        self.max_candles = max(1, max_candles)
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        if testnet:
            self.exchange.set_sandbox_mode(True)

        # Configure proxy - ccxt sets trust_env=False, so we must set proxies manually
        proxy_url = proxy or get_proxy_from_env()
        if proxy_url:
            if self.exchange.session is not None:
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

    def _probe_stride_ms(self, timeframe: str, limit: int) -> int:
        """How far to jump when probing past a leading gap.

        One request spans limit * timeframe of wall clock, and OKX answers
        empty for a window with no data rather than skipping to the next
        listed candle. Striding by exactly that window is therefore the
        largest jump that cannot step over bars we never looked at: a fixed
        stride would silently drop data on short timeframes, where 300x1m
        spans only 5 hours.
        """
        try:
            tf_seconds = self.exchange.parse_timeframe(timeframe)
        except Exception:
            return _LEADING_GAP_SKIP_MS
        return max(1, int(tf_seconds) * 1000 * limit)

    def _fetch_ohlcv(
        self, symbol: str, timeframe: str, limit: int, since: int | None
    ) -> list:
        """Call ccxt, retrying transient network failures.

        Raw ccxt exceptions escape on purpose: retry_on_network only
        recognizes ccxt's own network types, so wrapping them in
        DataFetchError must happen in fetch() *after* retries are spent.
        Permanent failures (BadSymbol, ExchangeError) are not network
        types and so propagate on the first attempt.
        """

        @retry_on_network(
            max_retries=self.max_retries, base_delay=self.retry_base_delay
        )
        def fetch_ohlcv() -> list:
            return self.exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, limit=limit, since=since
            )

        return fetch_ohlcv()

    def fetch(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 300,
        since: int | None = None,
        strict: bool = False,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles and return as DataFrame.

        Args:
            symbol: Trading pair, e.g. 'BTC/USDT'
            timeframe: '1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'
            limit: Number of candles (clamped to [1, max_candles])
            since: Unix timestamp in ms
            strict: If True, timestamp gaps raise instead of warning.

        Returns:
            DataFrame with columns [open, high, low, close, volume],
            DatetimeIndex (UTC, no timezone), sorted ascending.

        Raises:
            DataFetchError: If the timeframe is unsupported or the request fails.
            DataValidationError: If returned data fails validation.
        """
        # Clamp limit to valid range [1, max_candles]
        limit = max(1, min(limit, self.max_candles))

        # Exchanges that don't advertise timeframes get no check rather than
        # a spurious rejection.
        supported = self.available_timeframes()
        if supported and timeframe not in supported:
            raise DataFetchError(
                f"Timeframe '{timeframe}' not supported by {self.exchange_name}. "
                f"Available: {', '.join(supported)}"
            )

        try:
            raw = self._fetch_ohlcv(symbol, timeframe, limit, since)
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
        df = pd.DataFrame(
            df.astype(
                {
                    "open": "float64",
                    "high": "float64",
                    "low": "float64",
                    "close": "float64",
                    "volume": "float64",
                }
            )
        )

        validate_ohlcv(df, strict=strict)
        return df

    def fetch_range(
        self,
        symbol: str,
        timeframe: str,
        start: int,
        end: int,
        strict: bool = False,
    ) -> pd.DataFrame:
        """Fetch OHLCV data for a time range, chunking as needed.

        Args:
            symbol: Trading pair
            timeframe: K-line period
            start: Start time (Unix ms, inclusive)
            end: End time (Unix ms, inclusive)
            strict: If True, gaps in the assembled series raise instead of warning.

        Returns:
            Concatenated DataFrame, deduplicated and sorted.

        Raises:
            DataFetchError: If any chunk fails after retries.
                Error message includes number of successfully fetched chunks.
            DataValidationError: If the assembled series fails validation.
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
                if chunks:
                    break  # caught up to the end of available data
                # Nothing yet: the symbol likely wasn't listed at `start`.
                # Probe forward instead of abandoning the whole range. The
                # `cursor < end` bound caps how far this walks.
                cursor += self._probe_stride_ms(timeframe, self.max_candles)
                logger.debug(
                    f"{symbol} {timeframe}: no data yet, probing from "
                    f"{pd.Timestamp(cursor, unit='ms')}"
                )
                continue

            chunks.append(df)

            # Advance cursor past last candle.
            # OKX/Binance: timestamp = candle OPEN time. +1ms advances past it.
            # If an exchange uses CLOSE time semantics, this logic needs adjustment.
            next_cursor = int(pd.Timestamp(df.index[-1]).timestamp() * 1000) + 1
            if next_cursor <= cursor:
                # The exchange ignored `since` and replayed a window we already
                # hold. Without this guard the cursor creeps 1ms per request
                # and the loop never reaches `end`.
                logger.warning(
                    f"{symbol} {timeframe}: cursor stalled at "
                    f"{pd.Timestamp(cursor, unit='ms')}, stopping early"
                )
                break
            cursor = next_cursor

            logger.debug(
                f"{symbol} {timeframe}: +{len(df)} bars through {df.index[-1]} "
                f"({sum(len(c) for c in chunks)} total)"
            )

        if not chunks:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        result = pd.concat(chunks)
        result = result[~result.index.duplicated(keep="last")]
        result.sort_index(inplace=True)

        # Filter to requested range
        start_ts = pd.Timestamp(start, unit="ms")
        end_ts = pd.Timestamp(end, unit="ms")
        result = result[(result.index >= start_ts) & (result.index <= end_ts)]

        result = pd.DataFrame(result)
        # Per-chunk validation can't see gaps that straddle a chunk boundary,
        # so the assembled series gets the strict check.
        validate_ohlcv(result, strict=strict)
        return result
