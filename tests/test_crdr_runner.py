from __future__ import annotations

import numpy as np
import pandas as pd

from cq.research.crdr import runner
from cq.research.crdr.data import ALL_INSTRUMENTS, DataContractError, panel_from_frames


def _panel(hours: int = 3_400):
    index = pd.date_range("2021-01-01", periods=hours, freq="1h", tz="UTC")
    step = np.arange(hours, dtype=float)
    btc_returns = 0.0002 + 0.0001 * np.sin(step / 11.0)
    frames = {}
    for position, instrument in enumerate(ALL_INSTRUMENTS):
        beta = 1.0 if position == 0 else 0.55 + position * 0.08
        idiosyncratic = (
            np.zeros(hours)
            if position == 0
            else 0.00008 * position * np.cos(step / (7.0 + position))
        )
        close = np.exp(np.log(100.0 + position) + np.cumsum(beta * btc_returns + idiosyncratic))
        frames[instrument] = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": np.full(hours, 100.0 + position),
            },
            index=index,
        )
    return panel_from_frames(frames)


def test_runner_emits_every_frozen_variant_and_provenance(monkeypatch) -> None:
    monkeypatch.setattr(runner, "load_study_panel", lambda store: _panel())

    report = runner.run_study(object(), bootstrap_samples=20)  # type: ignore[arg-type]

    assert report["study_tag"] == "crypto-cross-sectional-residual-dispersion-reversion-v1"
    assert set(report["neighbors"]) == {
        "signal_4h",
        "signal_8h",
        "hold_4h",
        "hold_5h",
        "gate_q70",
        "gate_q90",
    }
    assert set(report["ablations"]) == {
        "raw_reversal",
        "ungated_residual_reversal",
        "residual_continuation",
    }
    assert report["data"]["end_exclusive"] == "2025-06-01T00:00:00+00:00"
    assert report["parameters"]["signal_hours"] == 6
    assert report["parameters"]["hold_hours"] == 6
    assert report["main"]["hours"] == (3_400 - 2_880)
    assert report["ablations"]["residual_continuation"]["episode_count"] == report["main"][
        "episode_count"
    ]
    assert len(report["segments"]) == 5
    assert len(report["episodes"]) == report["main"]["episode_count"]


def test_data_contract_failure_returns_invalid_without_running_models(monkeypatch) -> None:
    def fail_contract(store):
        raise DataContractError("deliberate mismatch")

    monkeypatch.setattr(runner, "load_study_panel", fail_contract)

    report = runner.run_study(object(), bootstrap_samples=20)  # type: ignore[arg-type]

    assert report["gates"]["G0"] is False
    assert report["gates"]["verdict"] == "INVALID"
    assert report["error"] == "deliberate mismatch"
