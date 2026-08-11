"""Frozen two-leg input contract for SPDP v2."""

from __future__ import annotations

import hashlib
import math
import sqlite3
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cq.context import Series, series_fingerprint

HOUR_MS = 3_600_000
RawRow = tuple[int, float, float, float, float, float, float]


class DataContractError(RuntimeError):
    """The frozen discovery panel is incomplete or has changed."""


@dataclass(frozen=True)
class StudyData:
    spot: Series
    swap: Series
    spot_qv: Series
    swap_qv: Series
    spot_raw_fingerprint: str
    swap_raw_fingerprint: str

    @property
    def aux_fingerprints(self) -> tuple[tuple[str, str, str], ...]:
        return (
            (*self.spot_qv.key, series_fingerprint(self.spot_qv)),
            (*self.swap_qv.key, series_fingerprint(self.swap_qv)),
        )


def fingerprint_rows(rows: Sequence[RawRow]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(struct.pack("<qdddddd", *row))
    return digest.hexdigest()


def make_quote_series(
    inst_id: str,
    timestamps: np.ndarray,
    quote_volume: np.ndarray,
    raw_volume: np.ndarray,
) -> Series:
    quote = np.asarray(quote_volume, dtype=float)
    return Series(
        inst_id,
        "1h",
        np.asarray(timestamps, dtype=np.int64),
        quote,
        quote,
        quote,
        quote,
        np.asarray(raw_volume, dtype=float),
    )


def load_study_data(
    path: Path | str,
    start_ms: int,
    end_ms: int,
    *,
    expected_count: int | None,
    expected_spot_fingerprint: str | None = None,
    expected_swap_fingerprint: str | None = None,
) -> StudyData:
    spot_rows = _load_rows(path, "DOGE-USDT", start_ms, end_ms)
    swap_rows = _load_rows(path, "DOGE-USDT-SWAP", start_ms, end_ms)
    if [row[0] for row in spot_rows] != [row[0] for row in swap_rows]:
        raise DataContractError("spot and swap timestamps are not strictly aligned")
    _validate_rows(spot_rows, "spot", start_ms, end_ms, expected_count)
    _validate_rows(swap_rows, "swap", start_ms, end_ms, expected_count)

    spot_hash = fingerprint_rows(spot_rows)
    swap_hash = fingerprint_rows(swap_rows)
    if expected_spot_fingerprint is not None and spot_hash != expected_spot_fingerprint:
        raise DataContractError("spot fingerprint mismatch")
    if expected_swap_fingerprint is not None and swap_hash != expected_swap_fingerprint:
        raise DataContractError("swap fingerprint mismatch")

    spot = _primary_series("DOGE-USDT", spot_rows)
    swap = _primary_series("DOGE-USDT-SWAP", swap_rows)
    spot_quote = np.asarray([row[6] for row in spot_rows], dtype=float)
    swap_quote = np.asarray([row[6] for row in swap_rows], dtype=float)
    return StudyData(
        spot=spot,
        swap=swap,
        spot_qv=make_quote_series("DOGE-USDT-QV", spot.ts, spot_quote, spot.volume),
        swap_qv=make_quote_series(
            "DOGE-USDT-SWAP-QV", swap.ts, swap_quote, swap.volume
        ),
        spot_raw_fingerprint=spot_hash,
        swap_raw_fingerprint=swap_hash,
    )


def _load_rows(
    path: Path | str, inst_id: str, start_ms: int, end_ms: int
) -> list[RawRow]:
    connection = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        raw = connection.execute(
            """SELECT ts, open, high, low, close, volume, quote_volume
               FROM ohlcv
               WHERE inst_id=? AND timeframe='1h' AND ts>=? AND ts<?
               ORDER BY ts""",
            (inst_id, start_ms, end_ms),
        ).fetchall()
    finally:
        connection.close()
    rows: list[RawRow] = []
    for values in raw:
        if values[6] is None:
            raise DataContractError(f"{inst_id}: null quote_volume")
        rows.append(tuple([int(values[0]), *map(float, values[1:])]))  # type: ignore[arg-type]
    return rows


def _validate_rows(
    rows: list[RawRow],
    label: str,
    start_ms: int,
    end_ms: int,
    expected_count: int | None,
) -> None:
    if expected_count is not None and len(rows) != expected_count:
        raise DataContractError(
            f"{label} count mismatch: expected {expected_count}, got {len(rows)}"
        )
    timestamps = np.asarray([row[0] for row in rows], dtype=np.int64)
    if len(rows) and (int(timestamps[0]) != start_ms or int(timestamps[-1]) >= end_ms):
        raise DataContractError(f"{label} does not cover the frozen half-open range")
    if len(timestamps) > 1 and not bool(np.all(np.diff(timestamps) == HOUR_MS)):
        raise DataContractError(f"{label} timestamps are not contiguous native 1h bars")
    for index, (_, open_, high, low, close, volume, quote_volume) in enumerate(rows):
        if not all(
            math.isfinite(value)
            for value in (open_, high, low, close, volume, quote_volume)
        ):
            raise DataContractError(f"{label} non-finite value at row {index}")
        if min(open_, high, low, close) <= 0 or high < max(open_, close) or low > min(open_, close):
            raise DataContractError(f"{label} invalid OHLC at row {index}")
        if volume < 0 or quote_volume < 0:
            raise DataContractError(f"{label} volume and quote_volume must be non-negative")


def _primary_series(inst_id: str, rows: list[RawRow]) -> Series:
    columns = list(zip(*rows, strict=True))
    return Series(
        inst_id,
        "1h",
        np.asarray(columns[0], dtype=np.int64),
        np.asarray(columns[1], dtype=float),
        np.asarray(columns[2], dtype=float),
        np.asarray(columns[3], dtype=float),
        np.asarray(columns[4], dtype=float),
        np.asarray(columns[5], dtype=float),
    )
