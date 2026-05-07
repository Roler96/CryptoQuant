"""Datetime utility functions for timestamp conversion."""

from datetime import datetime, timezone, timedelta

UTC8 = timezone(timedelta(hours=8))


def convert_to_utc8_str(timestamp_ms: int) -> str:
    """Convert millisecond timestamp to UTC+8 datetime string."""
    timestamp_seconds = timestamp_ms / 1000
    dt = datetime.fromtimestamp(timestamp_seconds, tz=UTC8)
    return dt.strftime('%Y-%m-%d %H:%M:%S')
