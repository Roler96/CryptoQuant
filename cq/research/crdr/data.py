"""Frozen data contract for the CRDR v1 intraday study."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from cq.data.store import Store

START_MS = int(datetime(2021, 1, 1, tzinfo=UTC).timestamp() * 1000)
END_MS = int(datetime(2025, 6, 1, tzinfo=UTC).timestamp() * 1000)

FACTOR_INSTRUMENT = "BTC-USDT-SWAP"
TRADE_INSTRUMENTS = (
    "ETH-USDT-SWAP",
    "DOGE-USDT-SWAP",
    "SOL-USDT-SWAP",
    "XRP-USDT-SWAP",
    "ADA-USDT-SWAP",
    "AVAX-USDT-SWAP",
    "LINK-USDT-SWAP",
    "DOT-USDT-SWAP",
    "TRX-USDT-SWAP",
)
ALL_INSTRUMENTS = (FACTOR_INSTRUMENT, *TRADE_INSTRUMENTS)

EXPECTED_COUNTS = {
    "BTC-USDT-SWAP": 38_688,
    "ETH-USDT-SWAP": 38_688,
    "DOGE-USDT-SWAP": 38_688,
    "SOL-USDT-SWAP": 38_178,
    "XRP-USDT-SWAP": 38_688,
    "ADA-USDT-SWAP": 38_688,
    "AVAX-USDT-SWAP": 38_688,
    "LINK-USDT-SWAP": 38_688,
    "DOT-USDT-SWAP": 38_688,
    "TRX-USDT-SWAP": 38_688,
}
EXPECTED_FINGERPRINTS = {
    "BTC-USDT-SWAP": "8578f9430c5c9c1f",
    "ETH-USDT-SWAP": "c46330ef631c3324",
    "DOGE-USDT-SWAP": "2936fd79dae285ce",
    "SOL-USDT-SWAP": "79004ee9be68812e",
    "XRP-USDT-SWAP": "45acfefe394e77c7",
    "ADA-USDT-SWAP": "159287a8e0b475c1",
    "AVAX-USDT-SWAP": "e1b66c6d84d43742",
    "LINK-USDT-SWAP": "2a0fe09144991b53",
    "DOT-USDT-SWAP": "5e15986bdcccacd5",
    "TRX-USDT-SWAP": "4892ce33c2cd52d9",
}
EXPECTED_DROPPED_COUNTS = {
    "BTC-USDT-SWAP": 9,
    "ETH-USDT-SWAP": 10,
    "DOGE-USDT-SWAP": 10,
    "SOL-USDT-SWAP": 11,
    "XRP-USDT-SWAP": 10,
    "ADA-USDT-SWAP": 10,
    "AVAX-USDT-SWAP": 11,
    "LINK-USDT-SWAP": 10,
    "DOT-USDT-SWAP": 10,
    "TRX-USDT-SWAP": 10,
}

_REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


class DataContractError(RuntimeError):
    """The source bars differ from the CRDR preregistration snapshot."""


@dataclass(frozen=True)
class StudyPanel:
    """Aligned raw prices plus an explicit per-instrument validity mask."""

    opens: pd.DataFrame
    closes: pd.DataFrame
    valid: pd.DataFrame
    fingerprints: dict[str, str]
    raw_counts: dict[str, int]
    dropped_counts: dict[str, int]


def fingerprint_frame(frame: pd.DataFrame) -> str:
    """Hash raw ts/OHLCV rows in timestamp order before quality filtering."""
    digest = hashlib.sha256()
    for ts, row in frame.sort_index().iterrows():
        digest.update(
            struct.pack(
                "<qddddd",
                int(pd.Timestamp(ts).timestamp() * 1000),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
            )
        )
    return digest.hexdigest()[:16]


def panel_from_frames(frames: dict[str, pd.DataFrame]) -> StudyPanel:
    """Align frames on a complete hourly grid without filling missing bars."""
    if not frames:
        raise ValueError("CRDR requires at least one instrument frame")
    for instrument, frame in frames.items():
        missing = set(_REQUIRED_COLUMNS) - set(frame.columns)
        if missing:
            raise ValueError(f"{instrument}: missing OHLCV columns {sorted(missing)}")
        if frame.empty:
            raise ValueError(f"{instrument}: empty OHLCV frame")

    ordered = {instrument: frame.sort_index() for instrument, frame in frames.items()}
    start = min(frame.index.min() for frame in ordered.values())
    end = max(frame.index.max() for frame in ordered.values())
    index = pd.date_range(start, end, freq="1h", tz="UTC")

    opens: dict[str, pd.Series] = {}
    closes: dict[str, pd.Series] = {}
    validity: dict[str, pd.Series] = {}
    fingerprints: dict[str, str] = {}
    raw_counts: dict[str, int] = {}
    dropped_counts: dict[str, int] = {}

    for instrument, frame in ordered.items():
        numeric = frame.loc[:, _REQUIRED_COLUMNS]
        finite = pd.Series(
            np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1), index=frame.index
        )
        prices_positive = (numeric.loc[:, ("open", "high", "low", "close")] > 0).all(axis=1)
        good = finite & prices_positive & (numeric["high"] > numeric["low"]) & (
            numeric["volume"] > 0
        )

        opens[instrument] = frame["open"].reindex(index)
        closes[instrument] = frame["close"].reindex(index)
        validity[instrument] = good.reindex(index, fill_value=False)
        fingerprints[instrument] = fingerprint_frame(frame)
        raw_counts[instrument] = len(frame)
        dropped_counts[instrument] = int((~good).sum())

    return StudyPanel(
        opens=pd.DataFrame(opens, index=index),
        closes=pd.DataFrame(closes, index=index),
        valid=pd.DataFrame(validity, index=index, dtype=bool),
        fingerprints=fingerprints,
        raw_counts=raw_counts,
        dropped_counts=dropped_counts,
    )


def load_study_panel(store: Store) -> StudyPanel:
    """Load and validate the exact frozen CRDR explore-window snapshot."""
    frames = {
        instrument: store.load_ohlcv(instrument, "1h", START_MS, END_MS)
        for instrument in ALL_INSTRUMENTS
    }
    panel = panel_from_frames(frames)
    mismatches = [
        instrument
        for instrument in ALL_INSTRUMENTS
        if panel.raw_counts[instrument] != EXPECTED_COUNTS[instrument]
        or panel.fingerprints[instrument] != EXPECTED_FINGERPRINTS[instrument]
        or panel.dropped_counts[instrument] != EXPECTED_DROPPED_COUNTS[instrument]
    ]
    if mismatches:
        raise DataContractError(f"CRDR frozen data mismatch: {mismatches}")
    return panel
