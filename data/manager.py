"""OKX API client for CryptoQuant platform.

Provides retry-enabled access to OKX exchange OHLCV data via ccxt.
Rate limiting is handled by ccxt's built-in mechanism.
"""

import os
import time
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Any, Dict, List, Optional

import ccxt
import structlog
from dotenv import load_dotenv

from data.models import OHLCVCandle

load_dotenv()

logger = structlog.get_logger(__name__)


class OKXAPIError(Exception):
    """Base exception for OKX API errors."""

    def __init__(self, message: str, error_code: Optional[str] = None):
        super().__init__(message)
        self.error_code = error_code


class OKXAuthenticationError(OKXAPIError):
    """Raised when API credentials are invalid."""
    pass


class OKXRateLimitError(OKXAPIError):
    """Raised when rate limit is exceeded."""
    pass


class OKXTimeoutError(OKXAPIError):
    """Raised when request times out."""
    pass


class OKXNetworkError(OKXAPIError):
    """Raised when network error occurs."""
    pass


def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0):
    """Decorator for retry logic with exponential backoff.

    Catches both raw ccxt exceptions and custom OKXAPIError subclasses so
    that retries work even when the wrapped function converts ccxt errors
    to domain exceptions before re-raising.

    Retry behaviour by exception type:
    - Network / Timeout errors: retry with exponential backoff
    - Rate limit errors: retry with longer backoff (2x the normal delay)
    - Authentication / other exchange errors: fail immediately (no retry)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ccxt.RequestTimeout,
                        OKXNetworkError, OKXTimeoutError) as e:
                    # Network/timeout — retryable
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(
                            "api_retry",
                            function=func.__name__,
                            attempt=attempt + 1,
                            delay=delay,
                            error=str(e),
                        )
                        time.sleep(delay)
                    else:
                        raise
                except (ccxt.RateLimitExceeded, OKXRateLimitError) as e:
                    # Rate limit — retryable with longer delay
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** (attempt + 2)), max_delay)
                        logger.warning(
                            "api_rate_limit_retry",
                            function=func.__name__,
                            attempt=attempt + 1,
                            delay=delay,
                            error=str(e),
                        )
                        time.sleep(delay)
                    else:
                        if isinstance(e, OKXRateLimitError):
                            raise
                        raise OKXRateLimitError(
                            f"Rate limit exceeded after {max_retries} retries: {e}"
                        )
                except ccxt.AuthenticationError as e:
                    raise OKXAuthenticationError(f"Invalid API credentials: {e}")
                except ccxt.ExchangeError as e:
                    raise OKXAPIError(f"Exchange error: {e}")

            # Should not reach here, but safety net
            if last_exception:
                raise OKXNetworkError(f"Failed after {max_retries} retries: {last_exception}")

        return wrapper
    return decorator


class OKXClient:
    """OKX API client for OHLCV data.

    Uses ccxt library with:
    - Built-in rate limiting (enableRateLimit=True)
    - Retry with exponential backoff
    - Environment-based credential loading
    - Sandbox mode support
    """

    def __init__(
        self,
        sandbox: bool = True,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None,
    ):
        self.sandbox = sandbox

        # Load credentials from environment or parameters
        if sandbox:
            self.api_key = api_key or os.getenv("OKX_SANDBOX_API_KEY") or os.getenv("OKX_API_KEY")
            self.api_secret = api_secret or os.getenv("OKX_SANDBOX_API_SECRET") or os.getenv("OKX_API_SECRET")
            self.passphrase = passphrase or os.getenv("OKX_SANDBOX_PASSPHRASE") or os.getenv("OKX_PASSPHRASE")
        else:
            self.api_key = api_key or os.getenv("OKX_API_KEY")
            self.api_secret = api_secret or os.getenv("OKX_API_SECRET")
            self.passphrase = passphrase or os.getenv("OKX_PASSPHRASE")

        if not all([self.api_key, self.api_secret, self.passphrase]):
            logger.warning(
                "missing_credentials",
                sandbox=sandbox,
                has_key=bool(self.api_key),
                has_secret=bool(self.api_secret),
                has_passphrase=bool(self.passphrase),
            )
            raise OKXAuthenticationError(
                "Missing OKX API credentials. "
                "Set OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE environment variables."
            )

        config = {
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'password': self.passphrase,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        }

        if sandbox:
            config['sandbox'] = True
            config['options']['sandbox'] = True

        # Proxy support: read from environment (covers WSL / corporate setups)
        proxy = (
            os.getenv("HTTPS_PROXY")
            or os.getenv("HTTP_PROXY")
            or os.getenv("https_proxy")
            or os.getenv("http_proxy")
        )
        if proxy:
            config['proxies'] = {'http': proxy, 'https': proxy}
            config['aiohttp_proxy'] = proxy
            logger.info("okx_proxy_configured", proxy=proxy)

        try:
            self.exchange = ccxt.okx(config)
            logger.info("okx_client_initialized", sandbox=sandbox)
        except Exception as e:
            logger.error("failed_to_initialize_exchange", error=str(e))
            raise OKXAPIError(f"Failed to initialize OKX exchange: {e}")

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol format for OKX."""
        if '/' not in symbol:
            if symbol.endswith('USDT'):
                base = symbol[:-4]
                return f"{base}/USDT"
        return symbol

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1h',
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict] = None,
    ) -> List[OHLCVCandle]:
        """Fetch OHLCV candlestick data.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (e.g., "1m", "5m", "1h", "1d")
            since: Unix timestamp in milliseconds to fetch from
            limit: Maximum number of candles to fetch
            params: Additional exchange-specific parameters

        Returns:
            List of OHLCVCandle objects

        Raises:
            OKXAuthenticationError: If credentials are invalid
            OKXRateLimitError: If rate limit is exceeded
            OKXNetworkError: If network error occurs
        """
        symbol = self._normalize_symbol(symbol)

        try:
            ohlcv = self.exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=since,
                limit=limit,
                params=params or {},
            )

            candles = []
            for candle in ohlcv:
                try:
                    candles.append(OHLCVCandle(
                        pair=symbol,
                        timeframe=timeframe,
                        timestamp=int(candle[0]),
                        open=Decimal(str(candle[1])),
                        high=Decimal(str(candle[2])),
                        low=Decimal(str(candle[3])),
                        close=Decimal(str(candle[4])),
                        volume=Decimal(str(candle[5])),
                    ))
                except (IndexError, InvalidOperation) as e:
                    logger.warning("invalid_candle_data", candle=candle, error=str(e))
                    continue

            logger.debug(
                "fetch_ohlcv_success",
                symbol=symbol,
                timeframe=timeframe,
                count=len(candles),
            )
            return candles

        except ccxt.NetworkError as e:
            raise OKXNetworkError(f"Network error fetching OHLCV: {e}")
        except ccxt.RequestTimeout as e:
            raise OKXTimeoutError(f"Timeout fetching OHLCV: {e}")
        except Exception as e:
            logger.error("fetch_ohlcv_failed", symbol=symbol, error=str(e))
            raise

    def _probe_valid_since(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
    ) -> Optional[int]:
        """Binary-search for the earliest `since` that returns data from OKX.

        OKX returns an empty list when `since` is before the pair's listing date.
        This method finds a valid starting timestamp by bisecting between
        `since_ms` (too early) and `until_ms` (known to have data).

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            since_ms: The original too-early start timestamp
            until_ms: The known-valid end boundary

        Returns:
            A valid `since` timestamp in ms, or None if no data exists at all
        """
        lo, hi = since_ms, until_ms
        # Get timeframe duration in ms for minimum step
        tf_ms = self._timeframe_to_ms(timeframe)
        result_since: Optional[int] = None

        logger.debug(
            "probe_valid_since_start",
            symbol=symbol,
            timeframe=timeframe,
            lo=lo,
            hi=hi,
        )

        while hi - lo > tf_ms:
            mid = lo + (hi - lo) // 2
            batch = self.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=mid,
                limit=1,
            )
            if batch:
                # mid works, try earlier
                result_since = mid
                hi = mid
            else:
                # mid too early, try later
                lo = mid
            time.sleep(0.1)

        # If we found a valid point, use it (align to candle boundary)
        if result_since is not None:
            # Fetch from just before to get the exact first candle
            batch = self.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=result_since,
                limit=1,
            )
            if batch:
                return batch[0].timestamp

        return result_since

    @staticmethod
    def _timeframe_to_ms(timeframe: str) -> int:
        """Convert a timeframe string (e.g., '1h', '4h', '1d') to milliseconds."""
        units = {'m': 60_000, 'h': 3_600_000, 'd': 86_400_000, 'w': 604_800_000}
        for suffix, multiplier in units.items():
            if timeframe.endswith(suffix):
                try:
                    return int(timeframe[:-1]) * multiplier
                except ValueError:
                    break
        # Fallback: assume 1h
        return 3_600_000

    def fetch_ohlcv_history(
        self,
        symbol: str,
        timeframe: str = '1h',
        since: Optional[int] = None,
        until: Optional[int] = None,
        page_size: int = 100,
        sleep_between_pages: float = 0.1,
    ) -> List[OHLCVCandle]:
        """Fetch historical OHLCV data with automatic pagination.

        Loops through fetch_ohlcv() pages until all data in the requested
        range has been collected. OKX returns at most 100 candles per call,
        so this method handles the pagination transparently.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (e.g., "1h", "4h", "1d")
            since: Start timestamp in ms (inclusive). Required.
            until: End timestamp in ms (inclusive). None = up to latest.
            page_size: Candles per request (max 100, default 100)
            sleep_between_pages: Seconds to sleep between pages (default 0.1s)

        Returns:
            List of OHLCVCandle objects sorted by timestamp ascending

        Raises:
            ValueError: If since is not provided
            OKXAPIError: On unrecoverable API errors
        """
        if since is None:
            raise ValueError("since is required for fetch_ohlcv_history")

        all_candles: List[OHLCVCandle] = []
        cursor = since
        seen_timestamps: set[int] = set()
        probed_since = False  # Track if we adjusted cursor via probing

        while True:
            batch = self.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=cursor,
                limit=page_size,
            )

            if not batch:
                # If this is the very first request, the empty result likely
                # means `since` is before the exchange listed this pair.
                # Probe forward to find a valid starting point.
                if not all_candles and not probed_since:
                    # Use `until` if available, otherwise use current time as hi bound
                    probe_until = until if until is not None else int(time.time() * 1000)
                    if probe_until > cursor:
                        cursor = self._probe_valid_since(symbol, timeframe, cursor, probe_until)
                        probed_since = True
                        if cursor is not None:
                            logger.info(
                                "fetch_ohlcv_history_probed_since",
                                symbol=symbol,
                                timeframe=timeframe,
                                adjusted_since=cursor,
                            )
                            continue
                break

            # Deduplicate: ccxt may return the candle at `since` again
            new_candles = [c for c in batch if c.timestamp not in seen_timestamps]
            for c in new_candles:
                seen_timestamps.add(c.timestamp)

            # Filter by until boundary
            if until is not None:
                new_candles = [c for c in new_candles if c.timestamp <= until]

            all_candles.extend(new_candles)

            # Stop if we got fewer than page_size (last page)
            if len(batch) < page_size:
                break

            # Stop if we've reached the until boundary
            if until is not None and batch[-1].timestamp >= until:
                break

            # Advance cursor past the last received candle
            cursor = batch[-1].timestamp + 1

            logger.debug(
                "fetch_ohlcv_history_page",
                symbol=symbol,
                timeframe=timeframe,
                total_so_far=len(all_candles),
                next_cursor=cursor,
            )

            time.sleep(sleep_between_pages)

        # Sort by timestamp (should already be sorted, but ensure it)
        all_candles.sort(key=lambda c: c.timestamp)

        logger.info(
            "fetch_ohlcv_history_complete",
            symbol=symbol,
            timeframe=timeframe,
            total_candles=len(all_candles),
        )

        return all_candles

    def close(self):
        """Close exchange connection and cleanup resources."""
        try:
            if hasattr(self.exchange, 'close'):
                self.exchange.close()
            logger.info("okx_client_closed")
        except Exception as e:
            logger.warning("error_closing_exchange", error=str(e))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
