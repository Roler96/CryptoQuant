"""Unified exception hierarchy for CryptoQuant."""


class CryptoQuantError(Exception):
    """Base exception for all CryptoQuant errors."""


class DataError(CryptoQuantError):
    """Data fetch/store related errors."""


class DataFetchError(DataError):
    """Failed to fetch data from exchange."""


class DataValidationError(DataError):
    """OHLCV data validation failed."""


class StrategyError(CryptoQuantError):
    """Strategy related errors."""


class ExecutionError(CryptoQuantError):
    """Order execution related errors."""


class InsufficientFundsError(ExecutionError):
    """Insufficient balance."""


class OrderRejectedError(ExecutionError):
    """Order rejected by exchange."""


class RiskError(CryptoQuantError):
    """Risk management related errors."""


class EmergencyStopError(RiskError):
    """Emergency stop triggered."""
