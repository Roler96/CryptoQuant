"""Tests for ClosedBarFeed — unclosed candle stripping."""

import time
from unittest.mock import MagicMock

import pandas as pd

from cryptoquant.data.closed_bar import ClosedBarFeed


def _make_live_feed(df: pd.DataFrame, timeframe: str = "1h"):
    """Create a mock LiveDataFeed that returns the given DataFrame."""
    feed = MagicMock()
    feed.fetch.return_value = df
    feed.timeframe = timeframe
    feed.symbol = "BTC/USDT"
    feed.last_fetch_ts = int(time.time() * 1000)
    feed.last_quality_report = None
    feed.stats.return_value = {"last_fetch_ts": feed.last_fetch_ts}
    return feed


class TestClosedBarFeed:
    def test_all_bars_closed_passes_through(self, monkeypatch):
        """When all bars are closed, data passes through unchanged."""
        dates = pd.date_range("2024-01-01", periods=10, freq="1h")
        df = pd.DataFrame(
            {"open": [100] * 10, "high": [101] * 10, "low": [99] * 10,
             "close": [100] * 10, "volume": [1000] * 10},
            index=dates,
        )
        # Current time is well after all bars have closed
        fake_now = dates[-1].timestamp() + 7200  # 2 hours after last bar open
        monkeypatch.setattr(time, "time", lambda: fake_now)

        raw = _make_live_feed(df, timeframe="1h")
        cbf = ClosedBarFeed(raw)

        result, meta = cbf.fetch(lookback=10)

        assert len(result) == 10
        assert meta.stripped == 0
        assert meta.has_new_closed

    def test_unclosed_bar_stripped(self, monkeypatch):
        """When the last bar hasn't closed, it's stripped."""
        dates = pd.date_range("2024-01-01", periods=10, freq="1h")
        # Bar at 09:00 closes at 10:00
        df = pd.DataFrame(
            {"open": [100] * 10, "high": [101] * 10, "low": [99] * 10,
             "close": [100] * 10, "volume": [1000] * 10},
            index=dates,
        )
        # Current time is 09:30 — last bar (09:00) hasn't closed yet
        fake_now = pd.Timestamp("2024-01-01 09:30").timestamp()
        monkeypatch.setattr(time, "time", lambda: fake_now)

        raw = _make_live_feed(df, timeframe="1h")
        cbf = ClosedBarFeed(raw)

        result, meta = cbf.fetch(lookback=10)

        assert len(result) == 9, f"Expected 9 closed bars, got {len(result)}"
        assert meta.stripped == 1
        assert meta.has_new_closed  # bar 08:00 is new and closed

    def test_all_bars_unclosed_returns_empty(self, monkeypatch):
        """If ALL bars are still forming, return empty DataFrame."""
        dates = pd.date_range("2024-01-01", periods=3, freq="1h")
        df = pd.DataFrame(
            {"open": [100] * 3, "high": [101] * 3, "low": [99] * 3,
             "close": [100] * 3, "volume": [1000] * 3},
            index=dates,
        )
        # Current time is just after the first bar opened — none closed
        fake_now = pd.Timestamp("2024-01-01 00:01").timestamp()
        monkeypatch.setattr(time, "time", lambda: fake_now)

        raw = _make_live_feed(df, timeframe="1h")
        cbf = ClosedBarFeed(raw)

        result, meta = cbf.fetch(lookback=10)

        assert len(result) == 0
        assert meta.stripped == 3
        assert not meta.has_new_closed

    def test_has_new_closed_only_on_new_bar(self, monkeypatch):
        """has_new_closed is False when we've already seen this bar."""
        dates = pd.date_range("2024-01-01", periods=10, freq="1h")
        df = pd.DataFrame(
            {"open": [100] * 10, "high": [101] * 10, "low": [99] * 10,
             "close": [100] * 10, "volume": [1000] * 10},
            index=dates,
        )
        fake_now = dates[-1].timestamp() + 7200
        monkeypatch.setattr(time, "time", lambda: fake_now)

        raw = _make_live_feed(df, timeframe="1h")
        cbf = ClosedBarFeed(raw)

        # First fetch — new bar
        _, meta1 = cbf.fetch(lookback=10)
        assert meta1.has_new_closed

        # Second fetch — same bar, no new closed bar
        _, meta2 = cbf.fetch(lookback=10)
        assert not meta2.has_new_closed

    def test_empty_feed(self, monkeypatch):
        """Empty DataFrame from raw feed passes through."""
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        raw = _make_live_feed(df)
        cbf = ClosedBarFeed(raw)

        result, meta = cbf.fetch(lookback=10)

        assert result.empty
        assert not meta.has_new_closed
        assert meta.stripped == 0

    def test_5m_timeframe(self, monkeypatch):
        """Works correctly with 5-minute timeframe."""
        dates = pd.date_range("2024-01-01 09:55", periods=10, freq="5min")
        df = pd.DataFrame(
            {"open": [100] * 10, "high": [101] * 10, "low": [99] * 10,
             "close": [100] * 10, "volume": [1000] * 10},
            index=dates,
        )
        # Current time: 10:43. Last bar (10:40) closes at 10:45 — still forming!
        fake_now = pd.Timestamp("2024-01-01 10:43").timestamp()
        monkeypatch.setattr(time, "time", lambda: fake_now)

        raw = _make_live_feed(df, timeframe="5m")
        cbf = ClosedBarFeed(raw)

        result, meta = cbf.fetch(lookback=10)

        assert len(result) == 9, f"Expected 9 closed bars, got {len(result)}"
        assert meta.stripped == 1

    def test_delegates_properties(self, monkeypatch):
        """Properties pass through to underlying feed."""
        dates = pd.date_range("2024-01-01", periods=5, freq="1h")
        df = pd.DataFrame(
            {"open": [100] * 5, "high": [101] * 5, "low": [99] * 5,
             "close": [100] * 5, "volume": [1000] * 5},
            index=dates,
        )
        fake_now = dates[-1].timestamp() + 7200
        monkeypatch.setattr(time, "time", lambda: fake_now)

        raw = _make_live_feed(df)
        cbf = ClosedBarFeed(raw)

        assert cbf.symbol == "BTC/USDT"
        assert cbf.timeframe == "1h"
        assert cbf.last_fetch_ts == raw.last_fetch_ts
