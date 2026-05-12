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
    """Decorator for retry logic with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ccxt.RequestTimeout) as e:
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
                        raise OKXNetworkError(f"Network error after {max_retries} retries: {e}")
                except ccxt.RateLimitExceeded as e:
                    raise OKXRateLimitError(f"Rate limit exceeded: {e}")
                except ccxt.AuthenticationError as e:
                    raise OKXAuthenticationError(f"Invalid API credentials: {e}")
                except ccxt.ExchangeError as e:
                    raise OKXAPIError(f"Exchange error: {e}")

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
