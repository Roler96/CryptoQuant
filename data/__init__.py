"""Data module for CryptoQuant platform.

Provides OKX API client, data models, and storage for market data access.
"""

from data.models import (
    OHLCVCandle,
    Ticker,
    OrderBook,
    OrderBookLevel,
    Balance,
    AccountBalance,
)

from data.manager import (
    OKXClient,
    RateLimiter,
    OKXAPIError,
    OKXAuthenticationError,
    OKXRateLimitError,
    OKXTimeoutError,
    OKXNetworkError,
    retry_with_backoff,
)

from data.storage import (
    save_historical_data,
    load_historical_data,
    load_historical_candles,
    get_metadata,
    get_data_info,
    delete_historical_data,
    list_available_data,
    get_last_timestamp,
    check_data_exists,
)

from data.validation import (
    validate_ohlcv_data,
    check_missing_timestamps,
    check_price_anomalies,
    check_volume_validation,
    validate_data_file,
    auto_repair_data,
    ValidationReport,
    ValidationIssue,
    VALIDATION_PASS,
    VALIDATION_WARN,
    VALIDATION_FAIL,
)

__all__ = [
    # Data models
    "OHLCVCandle",
    "Ticker",
    "OrderBook",
    "OrderBookLevel",
    "Balance",
    "AccountBalance",
    # Client
    "OKXClient",
    "RateLimiter",
    # Exceptions
    "OKXAPIError",
    "OKXAuthenticationError",
    "OKXRateLimitError",
    "OKXTimeoutError",
    "OKXNetworkError",
    # Decorators
    "retry_with_backoff",
    # Storage functions
    "save_historical_data",
    "load_historical_data",
    "load_historical_candles",
    "get_metadata",
    "get_data_info",
    "delete_historical_data",
    "list_available_data",
    "get_last_timestamp",
    "check_data_exists",
    # Validation functions
    "validate_ohlcv_data",
    "check_missing_timestamps",
    "check_price_anomalies",
    "check_volume_validation",
    "validate_data_file",
    "auto_repair_data",
    "ValidationReport",
    "ValidationIssue",
    "VALIDATION_PASS",
    "VALIDATION_WARN",
    "VALIDATION_FAIL",
]
