"""Frozen DOGE-USDT 1h discovery data contract for URA v1."""

from __future__ import annotations

import hashlib
import math
import sqlite3
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cq.context import Series

HOUR_MS = 3_600_000
START_MS = 1_609_459_200_000
END_MS = 1_748_736_000_000
EXPECTED_COUNT = 38_688
EXPECTED_FINGERPRINT = "11459117bfa9dcd09d942e9f0b4dfaf29c5e8bbb92272147cbbf8ba7bb28427f"
CANONICAL_NAN_BITS = 0x7FF8000000000000

RawRow = tuple[int, float, float, float, float, float, float | None]


class DataContractError(RuntimeError):
    """The local bars no longer match the preregistered source data."""


@dataclass(frozen=True)
class StudyData:
    series: Series
    quote_volume: np.ndarray
    raw_fingerprint: str
    zero_volume_count: int


def fingerprint_rows(rows: Sequence[RawRow]) -> str:
    digest = hashlib.sha256()
    for ts, open_, high, low, close, volume, quote_volume in rows:
        digest.update(struct.pack("<qddddd", ts, open_, high, low, close, volume))
        if quote_volume is None:
            digest.update(struct.pack("<Q", CANONICAL_NAN_BITS))
        else:
            digest.update(struct.pack("<d", quote_volume))
    return digest.hexdigest()


def load_study_data(
    db_path: Path | str,
    start_ms: int = START_MS,
    end_ms: int = END_MS,
    *,
    expected_count: int | None = EXPECTED_COUNT,
    expected_fingerprint: str | None = EXPECTED_FINGERPRINT,
) -> StudyData:
    """Load only the half-open frozen window through a read-only SQLite URI."""
    path = Path(db_path).resolve()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        raw = connection.execute(
            """SELECT ts, open, high, low, close, volume, quote_volume
               FROM ohlcv
               WHERE inst_id = ? AND timeframe = ? AND ts >= ? AND ts < ?
               ORDER BY ts""",
            ("DOGE-USDT", "1h", start_ms, end_ms),
        ).fetchall()
    finally:
        connection.close()

    rows: list[RawRow] = [
        (
            int(row[0]),
            float(row[1]),
            float(row[2]),
            float(row[3]),
            float(row[4]),
            float(row[5]),
            None if row[6] is None else float(row[6]),
        )
        for row in raw
    ]
    if expected_count is not None and len(rows) != expected_count:
        raise DataContractError(f"bar count {len(rows)} != frozen {expected_count}")
    if not rows:
        raise DataContractError("frozen query returned no bars")

    fingerprint = fingerprint_rows(rows)
    if expected_fingerprint is not None and fingerprint != expected_fingerprint:
        raise DataContractError(
            f"raw fingerprint {fingerprint} != frozen {expected_fingerprint}"
        )
    _validate_rows(rows, start_ms, end_ms)

    columns = list(zip(*rows, strict=True))
    quote_volume = np.asarray(
        [math.nan if value is None else value for value in columns[6]], dtype=float
    )
    quote_volume.setflags(write=False)
    volume = np.asarray(columns[5], dtype=float)
    return StudyData(
        series=Series(
            "DOGE-USDT",
            "1h",
            np.asarray(columns[0], dtype=np.int64),
            np.asarray(columns[1], dtype=float),
            np.asarray(columns[2], dtype=float),
            np.asarray(columns[3], dtype=float),
            np.asarray(columns[4], dtype=float),
            volume,
        ),
        quote_volume=quote_volume,
        raw_fingerprint=fingerprint,
        zero_volume_count=int(np.count_nonzero(volume <= 0.0)),
    )


def _validate_rows(rows: Sequence[RawRow], start_ms: int, end_ms: int) -> None:
    timestamps = np.asarray([row[0] for row in rows], dtype=np.int64)
    if timestamps[0] < start_ms or timestamps[-1] >= end_ms:
        raise DataContractError("query escaped its half-open bounds")
    if len(timestamps) > 1 and not bool(np.all(np.diff(timestamps) == HOUR_MS)):
        raise DataContractError("timestamps are not contiguous native 1h bars")

    for index, (_, open_, high, low, close, volume, quote_volume) in enumerate(rows):
        values = (open_, high, low, close, volume)
        if not all(math.isfinite(value) for value in values):
            raise DataContractError(f"non-finite OHLCV at row {index}")
        if min(open_, high, low, close) <= 0:
            raise DataContractError(f"non-positive price at row {index}")
        if high < max(open_, close) or low > min(open_, close) or high < low:
            raise DataContractError(f"invalid OHLC bounds at row {index}")
        if volume < 0:
            raise DataContractError(f"negative volume at row {index}")
        if quote_volume is not None and not math.isfinite(quote_volume):
            raise DataContractError(f"non-finite quote volume at row {index}")
