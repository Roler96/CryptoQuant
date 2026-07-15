"""Shared utility helpers used across cryptoquant subpackages."""
import functools
import os
import random
import re
import time
from typing import cast

import ccxt
import pandas as pd
from loguru import logger

from cryptoquant.exceptions import DataValidationError

REQUIRED_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")

_TIMEFRAME_RE = re.compile(r"^(\d+)([mhdw])$")
_TIMEFRAME_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def get_proxy_from_env() -> str | None:
    """Get proxy URL from environment variables."""
    return (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )


def missing_ohlcv_columns(df: pd.DataFrame) -> list[str]:
    """Return which of the required OHLCV columns are absent from df."""
    return [c for c in REQUIRED_OHLCV_COLUMNS if c not in df.columns]


def timeframe_to_timedelta(timeframe: str) -> pd.Timedelta:
    """Convert an exchange timeframe ('5m', '4h', '1d') to a Timedelta.

    Never hand an exchange timeframe straight to pandas: their alias
    vocabularies overlap with different meanings. df.resample("5m") buckets
    by five *months* — pandas reads 'm' as month-end — and only emits a
    FutureWarning while doing it, so a 5-minute resample silently collapses
    the whole history into a couple of bars. Timedelta has no such
    ambiguity, and resample() accepts one directly.
    """
    match = _TIMEFRAME_RE.match(timeframe.strip())
    if not match:
        raise DataValidationError(
            f"Unsupported timeframe {timeframe!r}; expected <n><m|h|d|w>, e.g. '4h'"
        )
    amount, unit = match.groups()
    # cast: the stub admits NaTType, which a finite seconds value cannot produce.
    return cast(
        pd.Timedelta, pd.Timedelta(seconds=int(amount) * _TIMEFRAME_SECONDS[unit])
    )


def safe_filename(text: str, *, extra_chars: str = "", lower: bool = False) -> str:
    """Sanitize a symbol/strategy name for use in filenames or table names.

    Always replaces '/'; pass extra_chars for additional characters to
    replace (e.g. '-' or ' '), and lower=True to lowercase the result.
    """
    safe = text.replace("/", "_")
    for ch in extra_chars:
        safe = safe.replace(ch, "_")
    return safe.lower() if lower else safe


def retry_on_network(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.1,
):
    """Network error retry decorator (exponential backoff + jitter)."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ConnectionError, TimeoutError) as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2**attempt), max_delay)
                        delay *= 1 + random.uniform(-jitter, jitter)
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for "
                            f"{func.__name__} in {delay:.1f}s: {e}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_retries} retries exhausted for "
                            f"{func.__name__}: {e}"
                        )
            if last_error is not None:
                raise last_error
            raise RuntimeError("retry_on_network: unreachable — no error captured")

        return wrapper

    return decorator
