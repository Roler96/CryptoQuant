"""Explore/validate window boundary and data fingerprinting.

Rebuilt 2026-07-31 after the research subsystem purge (`a51cb62`) -- only
the two primitives the current bar-sequence-GBM study needs, not the full
assortment that existed before. See project memory `research-reset-2026-07-23`
for why FORWARD_FREEZE is 2025-06-01 and not the earlier 2026-07-20.
"""

from __future__ import annotations

import hashlib
import struct
from datetime import UTC, datetime

import pandas as pd

EXPLORE_START = int(datetime(2021, 1, 1, tzinfo=UTC).timestamp() * 1000)
FORWARD_FREEZE = int(datetime(2025, 6, 1, tzinfo=UTC).timestamp() * 1000)


def explore_window() -> tuple[int, int]:
    """The frozen explore boundary: [EXPLORE_START, FORWARD_FREEZE)."""
    return EXPLORE_START, FORWARD_FREEZE


def data_fingerprint(frame: pd.DataFrame) -> str:
    """A reproducibility fingerprint over (ts, open, high, low, close), ts-ordered.

    Truncated to 16 hex characters, matching the convention frozen in
    docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md.
    """
    ordered = frame.sort_index()
    ts_ms = ordered.index.astype("int64") // 1_000_000
    digest = hashlib.sha256()
    for ts, o, h, low_, c in zip(
        ts_ms, ordered["open"], ordered["high"], ordered["low"], ordered["close"], strict=True
    ):
        digest.update(struct.pack("<qdddd", int(ts), float(o), float(h), float(low_), float(c)))
    return digest.hexdigest()[:16]
