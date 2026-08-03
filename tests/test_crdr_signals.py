from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from cq.research.crdr.data import ALL_INSTRUMENTS, TRADE_INSTRUMENTS, StudyPanel, panel_from_frames
from cq.research.crdr.signals import (
    SignalConfig,
    causal_threshold,
    estimate_residuals,
    generate_signals,
    rank_weights,
)


def _panel(hours: int = 3_400, *, with_idiosyncratic_returns: bool = True) -> StudyPanel:
    index = pd.date_range("2021-01-01", periods=hours, freq="1h", tz="UTC")
    step = np.arange(hours, dtype=float)
    btc_returns = 0.0002 + 0.0001 * np.sin(step / 11.0)
    frames: dict[str, pd.DataFrame] = {}
    for position, instrument in enumerate(ALL_INSTRUMENTS):
        beta = 1.0 if position == 0 else 0.55 + position * 0.08
        idiosyncratic = np.zeros(hours)
        if position and with_idiosyncratic_returns:
            idiosyncratic = 0.00002 * position * np.cos(step / (7.0 + position))
        log_close = np.log(100.0 + position) + np.cumsum(beta * btc_returns + idiosyncratic)
        close = np.exp(log_close)
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


def _replace_closes(panel: StudyPanel, closes: pd.DataFrame) -> StudyPanel:
    return replace(panel, closes=closes)


def test_beta_window_excludes_current_six_hour_signal() -> None:
    panel = _panel()
    checkpoint = pd.Timestamp("2021-05-01 00:00", tz="UTC")
    before = estimate_residuals(panel, checkpoint, SignalConfig())
    assert before is not None
    changed_closes = panel.closes.copy()
    signal_bars = pd.date_range(
        checkpoint - pd.Timedelta(hours=6),
        checkpoint - pd.Timedelta(hours=1),
        freq="1h",
    )
    changed_closes.loc[signal_bars, TRADE_INSTRUMENTS[0]] *= np.linspace(1.01, 1.06, 6)

    after = estimate_residuals(_replace_closes(panel, changed_closes), checkpoint, SignalConfig())

    assert after is not None
    assert dict(before.betas) == pytest.approx(dict(after.betas))
    assert dict(before.residuals)[TRADE_INSTRUMENTS[0]] != pytest.approx(
        dict(after.residuals)[TRADE_INSTRUMENTS[0]]
    )


def test_estimated_betas_match_known_linear_exposures() -> None:
    panel = _panel(with_idiosyncratic_returns=False)
    snapshot = estimate_residuals(
        panel,
        pd.Timestamp("2021-05-01 00:00", tz="UTC"),
        SignalConfig(),
    )

    assert snapshot is not None
    betas = dict(snapshot.betas)
    for position, instrument in enumerate(TRADE_INSTRUMENTS, start=1):
        assert betas[instrument] == pytest.approx(0.55 + position * 0.08, abs=1e-9)


def test_causal_threshold_excludes_current_observation() -> None:
    index = pd.date_range("2021-01-01", periods=271, freq="8h", tz="UTC")
    history = pd.Series([1.0] * 270 + [100.0], index=index)

    threshold = causal_threshold(
        history,
        checkpoint=index[-1],
        days=90,
        quantile=0.80,
        minimum=250,
    )

    assert threshold == pytest.approx(1.0)


def test_causal_threshold_requires_250_valid_observations() -> None:
    index = pd.date_range("2021-01-01", periods=249, freq="8h", tz="UTC")
    history = pd.Series(np.arange(249, dtype=float), index=index)

    assert causal_threshold(
        history,
        checkpoint=index[-1] + pd.Timedelta(hours=8),
        days=90,
        quantile=0.80,
        minimum=250,
    ) is None


def test_rank_weights_are_neutral_and_continuation_is_exact_inverse() -> None:
    residuals = {instrument: float(rank) for rank, instrument in enumerate(TRADE_INSTRUMENTS)}

    reversal = rank_weights(residuals, continuation=False)
    continuation = rank_weights(residuals, continuation=True)

    assert reversal is not None
    assert continuation is not None
    assert sum(reversal.values()) == pytest.approx(0.0)
    assert sum(abs(weight) for weight in reversal.values()) == pytest.approx(1.0)
    assert continuation == {instrument: -weight for instrument, weight in reversal.items()}


def test_rank_weights_skip_a_tie_at_a_selection_boundary() -> None:
    residuals = {instrument: float(rank) for rank, instrument in enumerate(TRADE_INSTRUMENTS)}
    residuals[TRADE_INSTRUMENTS[2]] = residuals[TRADE_INSTRUMENTS[1]]

    assert rank_weights(residuals) is None


def test_generated_events_use_frozen_checkpoints_and_execution_delay() -> None:
    events = generate_signals(_panel(), SignalConfig(), gated=False)

    assert events
    for event in events:
        assert event.checkpoint.hour in {0, 8, 16}
        assert event.entry_time == event.checkpoint + pd.Timedelta(hours=1)
        assert event.exit_time == event.checkpoint + pd.Timedelta(hours=7)


def test_invalid_bar_in_beta_window_rejects_the_checkpoint() -> None:
    panel = _panel()
    checkpoint = pd.Timestamp("2021-05-01 00:00", tz="UTC")
    valid = panel.valid.copy()
    valid.loc[checkpoint - pd.Timedelta(hours=100), TRADE_INSTRUMENTS[0]] = False

    assert estimate_residuals(replace(panel, valid=valid), checkpoint, SignalConfig()) is None


def test_signal_generation_is_prefix_invariant() -> None:
    panel = _panel()
    cutoff = panel.opens.index[3_000]
    mask = panel.opens.index <= cutoff
    prefix = StudyPanel(
        opens=panel.opens.loc[mask],
        closes=panel.closes.loc[mask],
        valid=panel.valid.loc[mask],
        fingerprints=panel.fingerprints,
        raw_counts=panel.raw_counts,
        dropped_counts=panel.dropped_counts,
    )

    left = generate_signals(prefix, SignalConfig(), gated=False)
    right = [
        event
        for event in generate_signals(panel, SignalConfig(), gated=False)
        if event.exit_time <= cutoff
    ]

    assert left == right
