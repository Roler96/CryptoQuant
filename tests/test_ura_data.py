"""URA v1 frozen-data contract tests."""

from __future__ import annotations

import sqlite3
import struct
from hashlib import sha256

import pytest

from cq.research.ura.data import DataContractError, load_study_data

HOUR = 3_600_000


def _database(path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE ohlcv (
        inst_id TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        ts INTEGER NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        quote_volume REAL,
        PRIMARY KEY (inst_id, timeframe, ts)
        )"""
    )
    for index in range(4):
        connection.execute(
            "INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "DOGE-USDT",
                "1h",
                index * HOUR,
                1.0 + index,
                1.2 + index,
                0.8 + index,
                1.1 + index,
                100.0 + index,
                None if index == 1 else 200.0 + index,
            ),
        )
    connection.commit()
    connection.close()


def _expected_hash() -> str:
    digest = sha256()
    for index in range(3):
        values = (
            index * HOUR,
            1.0 + index,
            1.2 + index,
            0.8 + index,
            1.1 + index,
            100.0 + index,
        )
        digest.update(struct.pack("<qddddd", *values))
        if index == 1:
            digest.update(struct.pack("<Q", 0x7FF8000000000000))
        else:
            digest.update(struct.pack("<d", 200.0 + index))
    return digest.hexdigest()


def test_readonly_half_open_load_and_canonical_hash(tmp_path) -> None:
    path = tmp_path / "bars.db"
    _database(path)

    data = load_study_data(
        path,
        start_ms=0,
        end_ms=3 * HOUR,
        expected_count=3,
        expected_fingerprint=_expected_hash(),
    )

    assert data.series.ts.tolist() == [0, HOUR, 2 * HOUR]
    assert data.quote_volume.tolist()[1] != data.quote_volume.tolist()[1]
    assert data.raw_fingerprint == _expected_hash()
    assert data.zero_volume_count == 0


def test_frozen_count_and_hash_mismatch_fail_closed(tmp_path) -> None:
    path = tmp_path / "bars.db"
    _database(path)

    with pytest.raises(DataContractError, match="count"):
        load_study_data(path, 0, 3 * HOUR, expected_count=4)
    with pytest.raises(DataContractError, match="fingerprint"):
        load_study_data(
            path,
            0,
            3 * HOUR,
            expected_count=None,
            expected_fingerprint="wrong",
        )


def test_gap_and_invalid_ohlc_fail_closed(tmp_path) -> None:
    path = tmp_path / "bars.db"
    _database(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "DELETE FROM ohlcv WHERE inst_id='DOGE-USDT' AND timeframe='1h' AND ts=?",
        (HOUR,),
    )
    connection.commit()
    connection.close()

    with pytest.raises(DataContractError, match="contiguous"):
        load_study_data(
            path,
            0,
            4 * HOUR,
            expected_count=None,
            expected_fingerprint=None,
        )
