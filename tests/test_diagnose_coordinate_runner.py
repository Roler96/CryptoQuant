import numpy as np
import pandas as pd
import pytest

from cq.research.split import ProtocolError
from scripts.diagnose_coordinate import assert_contiguous, fingerprint

BAR_MS = 300_000


def _contiguous_frame(days: int) -> pd.DataFrame:
    n = days * 288
    index = pd.to_datetime(np.arange(n) * BAR_MS, unit="ms", utc=True)
    return pd.DataFrame(
        {
            "open": np.ones(n),
            "high": np.ones(n),
            "low": np.ones(n),
            "close": np.ones(n),
            "volume": np.ones(n),
            "quote_volume": np.ones(n),
        },
        index=index,
    )


def test_contiguous_frame_is_accepted():
    assert_contiguous(_contiguous_frame(3))


def test_missing_bar_is_refused_rather_than_interpolated():
    frame = _contiguous_frame(3).drop(index=_contiguous_frame(3).index[100])
    with pytest.raises(ProtocolError, match="contiguous"):
        assert_contiguous(frame)


def test_fingerprint_is_stable_and_sensitive():
    frame = _contiguous_frame(1)
    assert fingerprint(frame) == fingerprint(frame.copy())
    altered = frame.copy()
    altered.iloc[0, altered.columns.get_loc("close")] = 2.0
    assert fingerprint(altered) != fingerprint(frame)
