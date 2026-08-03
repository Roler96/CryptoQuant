"""Load and validate the frozen DOGE-USDT spot 5m explore-window bars for the
bar-sequence-GBM study.

See docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md §1: the raw
fingerprint check must run BEFORE degenerate-bar filtering, so a source-data
change and a filtering bug produce distinguishable failures.
"""

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd

from cq.data.store import Store
from cq.research.split import data_fingerprint, explore_window

INST_ID = "DOGE-USDT"
TIMEFRAME = "5m"
EXPECTED_RAW_FINGERPRINT = "85cc617af4d57689"
EXPECTED_RAW_BAR_COUNT = 464_256


class FingerprintMismatchError(RuntimeError):
    """The raw pull does not match the frozen protocol snapshot."""


def load_explore_bars(store: Store) -> tuple[pd.DataFrame, int]:
    """The frozen explore-window bars, degenerate bars dropped.

    Returns (filtered_frame, dropped_count). Raises FingerprintMismatchError
    if the raw pull (before filtering) does not match the frozen protocol
    snapshot.
    """
    start_ms, end_ms = explore_window()
    raw = store.load_ohlcv(INST_ID, TIMEFRAME, start_ms=start_ms, end_ms=end_ms)

    fingerprint = data_fingerprint(raw)
    if fingerprint != EXPECTED_RAW_FINGERPRINT:
        raise FingerprintMismatchError(
            f"raw explore-window fingerprint {fingerprint} != frozen "
            f"{EXPECTED_RAW_FINGERPRINT} ({len(raw)} raw bars, expected "
            f"{EXPECTED_RAW_BAR_COUNT}) -- protocol requires re-freezing "
            f"before continuing, not silently proceeding"
        )

    filtered = cast(pd.DataFrame, raw[(raw["high"] > raw["low"]) & (raw["volume"] > 0)])
    dropped = len(raw) - len(filtered)
    return filtered, dropped


def log_returns(frame: pd.DataFrame) -> np.ndarray:
    """r[k] = log(close_{k+1} / close_k) for k=0..len(frame)-2."""
    closes = frame["close"].to_numpy()
    return np.log(closes[1:] / closes[:-1])
