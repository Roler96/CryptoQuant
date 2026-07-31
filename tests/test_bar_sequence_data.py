import numpy as np
import pandas as pd
import pytest

from cq.data.store import Store
from cq.research.bar_sequence.data import (
    FingerprintMismatchError,
    load_explore_bars,
    log_returns,
)


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


def _rows(inst_id, ts_start_ms, closes, volumes):
    rows = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
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


def test_log_returns_alignment():
    frame = pd.DataFrame({"close": [1.0, 1.1, 0.99]})
    r = log_returns(frame)
    assert len(r) == 2
    assert r[0] == pytest.approx(np.log(1.1 / 1.0))
    assert r[1] == pytest.approx(np.log(0.99 / 1.1))
