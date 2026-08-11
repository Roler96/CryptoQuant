"""SPDP v2 gate ordering and mandatory G1 short-circuit tests."""

from __future__ import annotations

import numpy as np

from cq.context import Series
from cq.research.spdp.data import HOUR_MS, StudyData, make_quote_series


def _small_panel(length: int = 820) -> StudyData:
    ts = np.arange(length, dtype=np.int64) * HOUR_MS
    returns = np.where(np.arange(length) % 2 == 0, 0.001, -0.001)
    close = np.exp(np.cumsum(returns))
    anchor = close[730]
    close[731:743] = anchor * np.exp(np.linspace(0.01, 0.12, 12))
    volume = np.full(length, 100.0)
    spot_quote = np.full(length, 10.0)
    swap_quote = np.full(length, 90.0)
    spot_quote[731:743] = 90.0
    swap_quote[731:743] = 10.0
    spot = Series("DOGE-USDT", "1h", ts, close, close, close, close, volume)
    swap = Series("DOGE-USDT-SWAP", "1h", ts, close, close, close, close, volume)
    return StudyData(
        spot,
        swap,
        make_quote_series("DOGE-USDT-QV", ts, spot_quote, volume),
        make_quote_series("DOGE-USDT-SWAP-QV", ts, swap_quote, volume),
        "spot-hash",
        "swap-hash",
    )


def test_g1_failure_never_calls_real_engine_or_reads_returns(monkeypatch) -> None:
    from cq.research.spdp import runner

    monkeypatch.setattr(runner, "load_study_data", lambda *args, **kwargs: _small_panel())

    def forbidden(*args, **kwargs):
        raise AssertionError("G1 failure must short-circuit before real engine execution")

    monkeypatch.setattr(runner, "run_spdp", forbidden)
    payload = runner.run_discovery("unused.db")

    assert payload["status"] == "DISCOVERY_FAIL"
    assert payload["gates"]["G0_integrity"] == "PASS"
    assert payload["gates"]["G1_capacity"] == "FAIL"
    assert all(
        payload["gates"][name] == "NOT_RUN"
        for name in (
            "G2_main_economics",
            "G3_stress_outliers",
            "G4_calendar",
            "G5_bootstrap",
            "G6_neighborhood",
            "G7_mechanism",
            "G8_matched_random",
        )
    )
    assert payload["main"] is None
    assert payload["holdout_accessed"] is False
