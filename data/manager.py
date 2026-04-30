"""OKX API client for CryptoQuant platform.

Provides rate-limited, retry-enabled access to OKX exchange data via ccxt.
"""

import os
import time
import threading
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Any
from functools import wraps

import ccxt
import structlog
from dotenv import load_dotenv

from data.models import OHLCVCandle, Ticker, OrderBook, OrderBookLevel, AccountBalance, Balance

load_dotenv()

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Token bucket rate limiter for API requests.

    OKX allows 20 requests per 2 seconds per IP.
    """

    def __init__(self, max_requests: int = 20, time_window: float = 2.0):
        self.max_requests = max_requests
        self.time_window = time_window
        self.tokens = max_requests
        self.last_update = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> float:
        """Acquire a token, waiting if necessary.

        Returns:
            Time waited in seconds
        """
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update

            # Replenish tokens based on elapsed time
            self.tokens = min(
                self.max_requests,
                self.tokens + elapsed * (self.max_requests / self.time_window)
            )
            self.last_update = now

            if self.tokens < 1:
                # Need to wait for token
                wait_time = (1 - self.tokens) * (self.time_window / self.max_requests)
                time.sleep(wait_time)
                self.tokens = 1
                self.last_update = time.monotonic()

            self.tokens -= 1
            return wait_time if self.tokens < 1 else 0.0


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

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
    """
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
                            max_retries=max_retries,
                            delay=delay,
                            error=str(e)
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
    """OKX API client with rate limiting and error handling.

    Uses ccxt library for exchange abstraction with:
    - Rate limiting (max 20 req/2s)
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
        enable_rate_limit: bool = True
    ):
        """Initialize OKX client.

        Args:
            sandbox: Use OKX demo trading environment
            api_key: OKX API key (or from OKX_API_KEY env var)
            api_secret: OKX API secret (or from OKX_API_SECRET env var)
            passphrase: OKX passphrase (or from OKX_PASSPHRASE env var)
            enable_rate_limit: Enable client-side rate limiting
        """
        self.sandbox = sandbox
        self.enable_rate_limit = enable_rate_limit
        self.rate_limiter = RateLimiter(max_requests=20, time_window=2.0) if enable_rate_limit else None

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
                has_passphrase=bool(self.passphrase)
            )
            raise OKXAuthenticationError(
                "Missing OKX API credentials. "
                "Set OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE environment variables."
            )

        # Initialize ccxt exchange
        config = {
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'password': self.passphrase,
            'enableRateLimit': True,  # ccxt built-in rate limiting
            'options': {
                'defaultType': 'spot',
            }
        }

        if sandbox:
            config['sandbox'] = True
            config['options']['sandbox'] = True

        try:
            self.exchange = ccxt.okx(config)
            logger.info(
                "okx_client_initialized",
                sandbox=sandbox,
                enable_rate_limit=enable_rate_limit
            )
        except Exception as e:
            logger.error("failed_to_initialize_exchange", error=str(e))
            raise OKXAPIError(f"Failed to initialize OKX exchange: {e}")

    def _apply_rate_limit(self):
        """Apply rate limiting before making request."""
        if self.rate_limiter:
            wait_time = self.rate_limiter.acquire()
            if wait_time > 0:
                logger.debug("rate_limit_wait", wait_time=wait_time)

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol format for OKX.

        Args:
            symbol: Symbol like "BTC/USDT" or "BTCUSDT"

        Returns:
            Normalized symbol for OKX (e.g., "BTC/USDT")
        """
        if '/' not in symbol:
            # Try to infer format: assume USDT quote for common pairs
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
        params: Optional[Dict] = None
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
        self._apply_rate_limit()
        symbol = self._normalize_symbol(symbol)

        try:
            ohlcv = self.exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=since,
                limit=limit,
                params=params or {}
            )

            candles = []
            for candle in ohlcv:
                try:
                    candles.append(OHLCVCandle(
                        timestamp=int(candle[0]),
                        open_price=Decimal(str(candle[1])),
                        high_price=Decimal(str(candle[2])),
                        low_price=Decimal(str(candle[3])),
                        close_price=Decimal(str(candle[4])),
                        volume=Decimal(str(candle[5])),
                        pair=symbol,
                        timeframe=timeframe
                    ))
                except (IndexError, InvalidOperation) as e:
                    logger.warning("invalid_candle_data", candle=candle, error=str(e))
                    continue

            logger.debug(
                "fetch_ohlcv_success",
                symbol=symbol,
                timeframe=timeframe,
                count=len(candles)
            )
            return candles

        except ccxt.NetworkError as e:
            raise OKXNetworkError(f"Network error fetching OHLCV: {e}")
        except ccxt.RequestTimeout as e:
            raise OKXTimeoutError(f"Timeout fetching OHLCV: {e}")
        except Exception as e:
            logger.error("fetch_ohlcv_failed", symbol=symbol, error=str(e))
            raise

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def fetch_ticker(self, symbol: str) -> Ticker:
        """Fetch current ticker data.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")

        Returns:
            Ticker object with current market data
        """
        self._apply_rate_limit()
        symbol = self._normalize_symbol(symbol)

        try:
            ticker = self.exchange.fetch_ticker(symbol)

            return Ticker(
                pair=symbol,
                bid=Decimal(str(ticker.get('bid', 0))),
                ask=Decimal(str(ticker.get('ask', 0))),
                last=Decimal(str(ticker.get('last', 0))),
                high=Decimal(str(ticker.get('high', 0))),
                low=Decimal(str(ticker.get('low', 0))),
                volume=Decimal(str(ticker.get('baseVolume', 0))),
                timestamp=int(ticker.get('timestamp', time.time() * 1000))
            )

        except ccxt.NetworkError as e:
            raise OKXNetworkError(f"Network error fetching ticker: {e}")
        except ccxt.RequestTimeout as e:
            raise OKXTimeoutError(f"Timeout fetching ticker: {e}")
        except Exception as e:
            logger.error("fetch_ticker_failed", symbol=symbol, error=str(e))
            raise

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def fetch_order_book(
        self,
        symbol: str,
        limit: Optional[int] = None
    ) -> OrderBook:
        """Fetch order book (market depth).

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            limit: Number of levels to fetch (default: exchange default)

        Returns:
            OrderBook object with bids and asks
        """
        self._apply_rate_limit()
        symbol = self._normalize_symbol(symbol)

        try:
            order_book = self.exchange.fetch_order_book(symbol, limit=limit)

            bids = [
                OrderBookLevel(
                    price=Decimal(str(bid[0])),
                    size=Decimal(str(bid[1]))
                )
                for bid in order_book.get('bids', [])
            ]

            asks = [
                OrderBookLevel(
                    price=Decimal(str(ask[0])),
                    size=Decimal(str(ask[1]))
                )
                for ask in order_book.get('asks', [])
            ]

            return OrderBook(
                pair=symbol,
                bids=bids,
                asks=asks,
                timestamp=int(order_book.get('timestamp', time.time() * 1000))
            )

        except ccxt.NetworkError as e:
            raise OKXNetworkError(f"Network error fetching order book: {e}")
        except ccxt.RequestTimeout as e:
            raise OKXTimeoutError(f"Timeout fetching order book: {e}")
        except Exception as e:
            logger.error("fetch_order_book_failed", symbol=symbol, error=str(e))
            raise

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def fetch_balance(self) -> AccountBalance:
        """Fetch account balance.

        Returns:
            AccountBalance object with all currency balances
        """
        self._apply_rate_limit()

        try:
            balance = self.exchange.fetch_balance()

            balances = {}
            for currency, data in balance.get('total', {}).items():
                if data and Decimal(str(data)) > 0:
                    free = balance.get('free', {}).get(currency, 0)
                    used = balance.get('used', {}).get(currency, 0)
                    total = balance.get('total', {}).get(currency, 0)

                    try:
                        balances[currency] = Balance(
                            currency=currency,
                            free=Decimal(str(free)) if free else Decimal('0'),
                            used=Decimal(str(used)) if used else Decimal('0'),
                            total=Decimal(str(total)) if total else Decimal('0')
                        )
                    except InvalidOperation:
                        logger.warning("invalid_balance_value", currency=currency, data=data)
                        continue

            return AccountBalance(
                balances=balances,
                timestamp=int(time.time() * 1000)
            )

        except ccxt.NetworkError as e:
            raise OKXNetworkError(f"Network error fetching balance: {e}")
        except ccxt.RequestTimeout as e:
            raise OKXTimeoutError(f"Timeout fetching balance: {e}")
        except ccxt.AuthenticationError as e:
            raise OKXAuthenticationError(f"Authentication failed: {e}")
        except Exception as e:
            logger.error("fetch_balance_failed", error=str(e))
            raise

    def get_exchange_status(self) -> Dict[str, Any]:
        """Get exchange status information.

        Returns:
            Dict with exchange status details
        """
        try:
            self._apply_rate_limit()
            status = self.exchange.fetch_status()
            return {
                'status': status.get('status', 'unknown'),
                'updated': status.get('updated'),
                'eta': status.get('eta'),
                'url': status.get('url')
            }
        except Exception as e:
            logger.error("fetch_status_failed", error=str(e))
            return {'status': 'error', 'error': str(e)}

    def get_markets(self) -> List[str]:
        """Get list of available trading pairs.

        Returns:
            List of symbol strings
        """
        try:
            self._apply_rate_limit()
            markets = self.exchange.load_markets()
            return list(markets.keys())
        except Exception as e:
            logger.error("load_markets_failed", error=str(e))
            raise OKXNetworkError(f"Failed to load markets: {e}")

    def close(self):
        """Close exchange connection and cleanup resources."""
        try:
            if hasattr(self.exchange, 'close'):
                self.exchange.close()
            logger.info("okx_client_closed")
        except Exception as e:
            logger.warning("error_closing_exchange", error=str(e))

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
