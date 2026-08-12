"""Unit tests for the frozen DSPR cross-asset batch runner."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.run_dspr_cross_asset_validation import BAR_MS, _calendar_segments, _validate_frame


def _frame(timestamps: np.ndarray) -> pd.DataFrame:
    prices = np.linspace(1.0, 1.1, len(timestamps))
    return pd.DataFrame(
        {
            "ts": timestamps,
            "open": prices,
            "high": prices + 0.01,
            "low": prices - 0.01,
            "close": prices,
            "volume": np.ones(len(timestamps)),
        }
    )


def test_validate_frame_accepts_contiguous_legal_bars() -> None:
    _validate_frame(_frame(np.arange(3, dtype=np.int64) * BAR_MS), "TEST-USDT-SWAP")


def test_validate_frame_rejects_a_gap() -> None:
    with pytest.raises(RuntimeError, match="not contiguous"):
        _validate_frame(_frame(np.array([0, BAR_MS, 3 * BAR_MS])), "TEST-USDT-SWAP")


def test_calendar_segments_marks_only_whole_years_complete() -> None:
    index = pd.date_range("2021-06-01", "2023-01-01", freq="5min", inclusive="left", tz="UTC")
    frame = pd.DataFrame(index=index)

    segments = _calendar_segments(frame)

    assert [(year, complete) for year, _, _, complete in segments] == [
        (2021, False),
        (2022, True),
    ]
