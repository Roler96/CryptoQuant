"""Causal residual-dispersion signals for CRDR v1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from cq.research.crdr.data import FACTOR_INSTRUMENT, TRADE_INSTRUMENTS, StudyPanel


@dataclass(frozen=True)
class SignalConfig:
    beta_hours: int = 720
    signal_hours: int = 6
    dispersion_days: int = 90
    dispersion_quantile: float = 0.80
    hold_hours: int = 6
    minimum_dispersion_history: int = 250

    def __post_init__(self) -> None:
        for name in ("beta_hours", "signal_hours", "dispersion_days", "hold_hours"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if not 0 < self.dispersion_quantile < 1:
            raise ValueError("dispersion_quantile must be between zero and one")
        if self.minimum_dispersion_history < 1:
            raise ValueError("minimum_dispersion_history must be positive")


@dataclass(frozen=True)
class ResidualSnapshot:
    checkpoint: pd.Timestamp
    betas: tuple[tuple[str, float], ...]
    raw_returns: tuple[tuple[str, float], ...]
    residuals: tuple[tuple[str, float], ...]
    dispersion: float


@dataclass(frozen=True)
class SignalEvent:
    checkpoint: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    dispersion: float
    threshold: float | None
    residuals: tuple[tuple[str, float], ...]
    weights: tuple[tuple[str, float], ...]


def estimate_residuals(
    panel: StudyPanel,
    checkpoint: pd.Timestamp,
    config: SignalConfig,
    *,
    residualized: bool = True,
) -> ResidualSnapshot | None:
    """Estimate trailing returns after a non-overlapping causal beta window."""
    required_bars = config.beta_hours + config.signal_hours + 1
    bar_times = pd.date_range(
        checkpoint - pd.Timedelta(hours=required_bars),
        checkpoint - pd.Timedelta(hours=1),
        freq="1h",
    )
    if len(bar_times) != required_bars:
        raise AssertionError("unexpected CRDR window length")

    entry_time = checkpoint + pd.Timedelta(hours=1)
    exit_time = entry_time + pd.Timedelta(hours=config.hold_hours)
    execution_times = pd.DatetimeIndex([entry_time, exit_time])
    required_instruments = (FACTOR_INSTRUMENT, *TRADE_INSTRUMENTS)

    valid_window = panel.valid.reindex(index=bar_times, columns=required_instruments)
    valid_execution = panel.valid.reindex(index=execution_times, columns=required_instruments)
    if valid_window.isna().to_numpy().any() or valid_execution.isna().to_numpy().any():
        return None
    if not valid_window.to_numpy(dtype=bool).all():
        return None
    if not valid_execution.to_numpy(dtype=bool).all():
        return None

    closes = panel.closes.loc[bar_times, required_instruments].to_numpy(dtype=float)
    beta_prices = closes[: config.beta_hours + 1]
    beta_returns = np.diff(np.log(beta_prices), axis=0)
    btc_beta_returns = beta_returns[:, 0]
    btc_variance = float(np.var(btc_beta_returns, ddof=1))
    if not np.isfinite(btc_variance) or btc_variance <= 0:
        return None

    signal_returns = np.log(closes[-1] / closes[config.beta_hours])
    btc_signal_return = float(signal_returns[0])
    betas: dict[str, float] = {}
    raw_returns: dict[str, float] = {}
    residuals: dict[str, float] = {}
    for column, instrument in enumerate(TRADE_INSTRUMENTS, start=1):
        covariance = float(np.cov(beta_returns[:, column], btc_beta_returns, ddof=1)[0, 1])
        beta = covariance / btc_variance
        raw_return = float(signal_returns[column])
        residual = raw_return - beta * btc_signal_return if residualized else raw_return
        if not all(np.isfinite(value) for value in (beta, raw_return, residual)):
            return None
        betas[instrument] = beta
        raw_returns[instrument] = raw_return
        residuals[instrument] = residual

    cross_section = np.fromiter(residuals.values(), dtype=float)
    low, high = np.quantile(cross_section, [0.10, 0.90], method="linear")
    return ResidualSnapshot(
        checkpoint=checkpoint,
        betas=tuple(betas.items()),
        raw_returns=tuple(raw_returns.items()),
        residuals=tuple(residuals.items()),
        dispersion=float(high - low),
    )


def causal_threshold(
    history: pd.Series,
    checkpoint: pd.Timestamp,
    days: int,
    quantile: float,
    *,
    minimum: int = 250,
) -> float | None:
    """A linear quantile over prior calendar observations, excluding current."""
    if history.empty:
        return None
    lower = checkpoint - pd.Timedelta(days=days)
    prior = history.loc[(history.index >= lower) & (history.index < checkpoint)].dropna()
    if len(prior) < minimum:
        return None
    return float(np.quantile(prior.to_numpy(dtype=float), quantile, method="linear"))


def rank_weights(
    residuals: Mapping[str, float],
    *,
    continuation: bool = False,
) -> dict[str, float] | None:
    """Select two extremes per side, refusing ties at either rank boundary."""
    if set(residuals) != set(TRADE_INSTRUMENTS):
        raise ValueError("CRDR ranking requires the frozen nine-instrument universe")
    ordered = sorted(residuals.items(), key=lambda item: (item[1], item[0]))
    if ordered[1][1] == ordered[2][1] or ordered[-3][1] == ordered[-2][1]:
        return None

    weights = {instrument: 0.0 for instrument in TRADE_INSTRUMENTS}
    for instrument, _ in ordered[:2]:
        weights[instrument] = 0.25
    for instrument, _ in ordered[-2:]:
        weights[instrument] = -0.25
    if continuation:
        weights = {instrument: -weight for instrument, weight in weights.items()}
    return weights


def generate_signals(
    panel: StudyPanel,
    config: SignalConfig,
    *,
    residualized: bool = True,
    gated: bool = True,
    continuation: bool = False,
) -> list[SignalEvent]:
    """Generate frozen CRDR events while retaining all valid dispersion history."""
    history_times: list[pd.Timestamp] = []
    history_values: list[float] = []
    events: list[SignalEvent] = []

    for checkpoint in panel.opens.index:
        if checkpoint.hour not in {0, 8, 16}:
            continue
        snapshot = estimate_residuals(
            panel,
            checkpoint,
            config,
            residualized=residualized,
        )
        if snapshot is None:
            continue

        history = pd.Series(history_values, index=pd.DatetimeIndex(history_times), dtype=float)
        threshold = causal_threshold(
            history,
            checkpoint,
            config.dispersion_days,
            config.dispersion_quantile,
            minimum=config.minimum_dispersion_history,
        )
        history_times.append(checkpoint)
        history_values.append(snapshot.dispersion)

        if gated and (threshold is None or snapshot.dispersion <= threshold):
            continue
        weights = rank_weights(dict(snapshot.residuals), continuation=continuation)
        if weights is None:
            continue
        entry_time = checkpoint + pd.Timedelta(hours=1)
        exit_time = entry_time + pd.Timedelta(hours=config.hold_hours)
        events.append(
            SignalEvent(
                checkpoint=checkpoint,
                entry_time=entry_time,
                exit_time=exit_time,
                dispersion=snapshot.dispersion,
                threshold=threshold,
                residuals=snapshot.residuals,
                weights=tuple(weights.items()),
            )
        )
    return events
