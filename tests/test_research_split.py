import hashlib
import struct
from datetime import UTC, datetime

import pandas as pd

from cq.research.split import data_fingerprint, explore_window


def test_explore_window_matches_frozen_boundary():
    start_ms, end_ms = explore_window()
    assert start_ms == int(datetime(2021, 1, 1, tzinfo=UTC).timestamp() * 1000)
    assert end_ms == int(datetime(2025, 6, 1, tzinfo=UTC).timestamp() * 1000)


def test_fingerprint_matches_hand_computed_hash():
    frame = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.5, 2.5],
            "low": [0.5, 1.5],
            "close": [1.2, 2.2],
            "volume": [10.0, 20.0],
        },
        index=pd.to_datetime([1_700_000_000_000, 1_700_000_300_000], unit="ms", utc=True),
    )

    expected = hashlib.sha256()
    for ts, o, h, low_, c in [
        (1_700_000_000_000, 1.0, 1.5, 0.5, 1.2),
        (1_700_000_300_000, 2.0, 2.5, 1.5, 2.2),
    ]:
        expected.update(struct.pack("<qdddd", ts, o, h, low_, c))

    assert data_fingerprint(frame) == expected.hexdigest()[:16]


def test_fingerprint_is_order_independent_of_input_but_not_of_ts():
    # Feeding rows out of ts order must not change the fingerprint -- the
    # function sorts internally.
    frame = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.5, 2.5],
            "low": [0.5, 1.5],
            "close": [1.2, 2.2],
            "volume": [10.0, 20.0],
        },
        index=pd.to_datetime([1_700_000_300_000, 1_700_000_000_000], unit="ms", utc=True),
    )
    sorted_frame = frame.sort_index()
    assert data_fingerprint(frame) == data_fingerprint(sorted_frame)
