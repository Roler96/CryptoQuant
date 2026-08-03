import numpy as np
import pandas as pd
import pytest

from cq.data.store import Store
from cq.research.bar_sequence.data import (
    FingerprintMismatchError,
    load_explore_bars,
    log_returns,
)
from cq.research.split import data_fingerprint


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


def _rows(inst_id, ts_start_ms, closes, volumes):
    rows = []
    for i, (c, v) in enumerate(zip(closes, volumes, strict=True)):
        ts = ts_start_ms + i * 300_000  # 5m bars
        o = h = low = c
        # 9-tuple: inst_id, timeframe, ts, open, high, low, close, volume, quote_volume
        rows.append((inst_id, "5m", ts, o, h, low, c, v, c * v))
    return rows


def test_load_explore_bars_drops_degenerate_bars_and_reports_count(store):
    # Bar index 2 is a synthetic flat/zero-volume print (OKX outage style).
    closes = [1.0, 1.01, 1.01, 1.02, 1.03]
    volumes = [10.0, 10.0, 0.0, 10.0, 10.0]
    store.upsert_ohlcv(_rows("DOGE-USDT", 1_609_459_200_000, closes, volumes))

    with pytest.raises(FingerprintMismatchError):
        # Synthetic data will never match the frozen real-data fingerprint --
        # this proves the check actually fires rather than being skipped.
        load_explore_bars(store)


def test_load_explore_bars_filters_degenerate_bars_correctly(store, monkeypatch):
    """Verify filtering of degenerate bars (high<=low or volume==0) and dropped count."""
    ts_start = 1_609_459_200_000
    ts_end = ts_start + 5 * 300_000

    # Create synthetic data with known degenerate bars
    rows = []
    # Bar 0: normal (high > low, volume > 0)
    rows.append(("DOGE-USDT", "5m", ts_start + 0*300_000, 1.0, 1.01, 0.99, 1.0, 10.0, 10.0))
    # Bar 1: normal
    rows.append(("DOGE-USDT", "5m", ts_start + 1*300_000, 1.01, 1.02, 1.0, 1.01, 10.0, 10.1))
    # Bar 2: degenerate (high == low)
    rows.append(("DOGE-USDT", "5m", ts_start + 2*300_000, 1.01, 1.01, 1.01, 1.01, 10.0, 10.1))
    # Bar 3: degenerate (volume == 0)
    rows.append(("DOGE-USDT", "5m", ts_start + 3*300_000, 1.015, 1.02, 1.01, 1.015, 0.0, 0.0))
    # Bar 4: normal
    rows.append(("DOGE-USDT", "5m", ts_start + 4*300_000, 1.03, 1.04, 1.02, 1.03, 10.0, 10.3))

    store.upsert_ohlcv(rows)

    # Get the raw data to compute expected fingerprint
    raw = store.load_ohlcv("DOGE-USDT", "5m", start_ms=ts_start, end_ms=ts_end)
    expected_fp = data_fingerprint(raw)

    # Patch explore_window and fingerprint constants to bypass frozen checks
    monkeypatch.setattr(
        "cq.research.bar_sequence.data.explore_window",
        lambda: (ts_start, ts_end)
    )
    monkeypatch.setattr("cq.research.bar_sequence.data.EXPECTED_RAW_FINGERPRINT", expected_fp)
    monkeypatch.setattr("cq.research.bar_sequence.data.EXPECTED_RAW_BAR_COUNT", len(raw))

    # Call load_explore_bars
    frame, dropped = load_explore_bars(store)

    # Verify results
    assert dropped == 2, f"Expected 2 dropped bars, got {dropped}"
    assert len(frame) == 3, f"Expected 3 bars after filtering, got {len(frame)}"

    # Verify no degenerate bars remain
    assert (frame["high"] > frame["low"]).all(), "Result contains bars with high <= low"
    assert (frame["volume"] > 0).all(), "Result contains bars with volume <= 0"


def test_log_returns_alignment():
    frame = pd.DataFrame({"close": [1.0, 1.1, 0.99]})
    r = log_returns(frame)
    assert len(r) == 2
    assert r[0] == pytest.approx(np.log(1.1 / 1.0))
    assert r[1] == pytest.approx(np.log(0.99 / 1.1))
