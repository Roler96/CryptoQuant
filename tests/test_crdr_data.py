import hashlib
import struct
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from cq.research.crdr.data import (
    ALL_INSTRUMENTS,
    END_MS,
    START_MS,
    DataContractError,
    fingerprint_frame,
    load_study_panel,
    panel_from_frames,
)


def _frame(
    start: str = "2021-01-01",
    periods: int = 4,
    *,
    offset: float = 0.0,
) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="1h", tz="UTC")
    close = np.arange(1, periods + 1, dtype=float) + offset
    return pd.DataFrame(
        {
            "open": close - 0.05,
            "high": close + 0.10,
            "low": close - 0.10,
            "close": close,
            "volume": np.full(periods, 10.0),
            "quote_volume": np.full(periods, 100.0),
        },
        index=index,
    )


def test_fingerprint_matches_hand_packed_ts_ohlcv_rows() -> None:
    frame = _frame(periods=2).iloc[::-1]
    expected = hashlib.sha256()
    for ts, row in frame.sort_index().iterrows():
        expected.update(
            struct.pack(
                "<qddddd",
                int(ts.timestamp() * 1000),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
            )
        )

    assert fingerprint_frame(frame) == expected.hexdigest()[:16]


def test_fingerprint_includes_volume() -> None:
    frame = _frame()
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("volume")] = 11.0

    assert fingerprint_frame(frame) != fingerprint_frame(changed)


def test_panel_keeps_missing_and_degenerate_bars_invalid_without_filling() -> None:
    first = _frame()
    second = _frame(offset=10.0).iloc[[0, 2, 3]].copy()
    second.loc[second.index[1], "volume"] = 0.0

    panel = panel_from_frames({"A": first, "B": second})

    assert panel.valid.loc[first.index[0], ["A", "B"]].all()
    assert not panel.valid.loc[first.index[1], "B"]
    assert not panel.valid.loc[first.index[2], "B"]
    assert np.isnan(panel.opens.loc[first.index[1], "B"])
    assert panel.dropped_counts == {"A": 0, "B": 1}


@pytest.mark.parametrize(
    ("column", "bad_value"),
    [("open", 0.0), ("close", np.inf), ("high", 1.0), ("low", 20.0)],
)
def test_panel_rejects_nonpositive_nonfinite_and_nonpositive_range_bars(
    column: str,
    bad_value: float,
) -> None:
    frame = _frame(offset=10.0)
    frame.loc[frame.index[1], column] = bad_value

    panel = panel_from_frames({"A": frame})

    assert not panel.valid.loc[frame.index[1], "A"]
    assert panel.dropped_counts["A"] == 1


class _RecordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int | None, int | None]] = []

    def load_ohlcv(
        self,
        inst_id: str,
        timeframe: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> pd.DataFrame:
        self.calls.append((inst_id, timeframe, start_ms, end_ms))
        return _frame()


def test_frozen_loader_queries_every_instrument_without_touching_holdout() -> None:
    store = _RecordingStore()

    with pytest.raises(DataContractError, match="frozen data mismatch"):
        load_study_panel(store)  # type: ignore[arg-type]

    assert store.calls == [(inst, "1h", START_MS, END_MS) for inst in ALL_INSTRUMENTS]
    assert int(datetime(2021, 1, 1, tzinfo=UTC).timestamp() * 1000) == START_MS
    assert int(datetime(2025, 6, 1, tzinfo=UTC).timestamp() * 1000) == END_MS
