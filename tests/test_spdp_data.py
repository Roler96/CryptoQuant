"""SPDP v2 frozen two-leg data and provenance tests."""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from cq.context import series_fingerprint
from cq.research.spdp.data import HOUR_MS, DataContractError, load_study_data


def _database(
    path, *, swap_offset: int = 0, null_quote: bool = False, zero_quote: bool = False
) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE ohlcv (
        inst_id TEXT NOT NULL, timeframe TEXT NOT NULL, ts INTEGER NOT NULL,
        open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
        close REAL NOT NULL, volume REAL NOT NULL, quote_volume REAL,
        PRIMARY KEY (inst_id, timeframe, ts))"""
    )
    for inst_id, offset in (("DOGE-USDT", 0), ("DOGE-USDT-SWAP", swap_offset)):
        for index in range(5):
            close = 1.0 + index / 100.0
            connection.execute(
                "INSERT INTO ohlcv VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    inst_id,
                    "1h",
                    (index + offset) * HOUR_MS,
                    close,
                    close + 0.01,
                    close - 0.01,
                    close,
                    100.0 + index,
                    (
                        None
                        if null_quote and inst_id == "DOGE-USDT" and index == 2
                        else (
                            0.0
                            if zero_quote and index == 2
                            else 200.0 + index
                        )
                    ),
                ),
            )
    connection.commit()
    connection.close()


def test_loads_aligned_raw_legs_and_builds_manifest_bound_quote_series(tmp_path) -> None:
    path = tmp_path / "bars.db"
    _database(path)

    data = load_study_data(path, 0, 5 * HOUR_MS, expected_count=5)

    assert data.spot.ts.tolist() == data.swap.ts.tolist()
    assert data.spot_qv.key == ("DOGE-USDT-QV", "1h")
    assert data.swap_qv.key == ("DOGE-USDT-SWAP-QV", "1h")
    assert data.spot_qv.close.tolist() == [200.0, 201.0, 202.0, 203.0, 204.0]
    assert data.spot_qv.volume.tolist() == [100.0, 101.0, 102.0, 103.0, 104.0]
    assert np.array_equal(data.spot_qv.open, data.spot_qv.close)
    assert np.array_equal(data.spot_qv.high, data.spot_qv.close)
    assert np.array_equal(data.spot_qv.low, data.spot_qv.close)
    assert data.aux_fingerprints == (
        ("DOGE-USDT-QV", "1h", series_fingerprint(data.spot_qv)),
        ("DOGE-USDT-SWAP-QV", "1h", series_fingerprint(data.swap_qv)),
    )
    assert len(data.spot_raw_fingerprint) == 64
    assert len(data.swap_raw_fingerprint) == 64
    with pytest.raises(ValueError):
        data.spot_qv.close[0] = 999.0


def test_alignment_and_positive_quote_volume_fail_closed(tmp_path) -> None:
    misaligned = tmp_path / "misaligned.db"
    _database(misaligned, swap_offset=1)
    with pytest.raises(DataContractError, match="aligned"):
        load_study_data(misaligned, 0, 5 * HOUR_MS, expected_count=None)

    missing = tmp_path / "missing.db"
    _database(missing, null_quote=True)
    with pytest.raises(DataContractError, match="quote_volume"):
        load_study_data(missing, 0, 5 * HOUR_MS, expected_count=5)


def test_zero_volume_is_preserved_for_window_and_execution_level_checks(tmp_path) -> None:
    path = tmp_path / "zero.db"
    _database(path, zero_quote=True)

    data = load_study_data(path, 0, 5 * HOUR_MS, expected_count=5)

    assert data.spot_qv.close[2] == 0.0
    assert data.swap_qv.close[2] == 0.0
