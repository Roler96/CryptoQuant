#!/usr/bin/env python
"""Frozen DOGE 5m spot/perpetual basis-shock reversion study.

The formula, family, costs, chronological gates and funding-window exclusion
were frozen in ``BASIS_SHOCK_REVERSION_PROTOCOL_2026-07-23.md`` before any BSR
return was read.  This is a two-leg research simulator because the production
engine intentionally models one instrument per portfolio.  It preserves the
same causal convention: a signal made from bar t's close fills both legs at
bar t+1's open.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cq.context import Series, series_fingerprint
from cq.data.quality import check_ohlcv
from cq.data.store import Store
from cq.research.metrics import bars_per_year, max_drawdown, sharpe_ratio
from cq.research.split import to_ms
from cq.research.stats import bootstrap_trades, sidak_correction

DB_PATH = "data/cq.db"
SPOT_INSTRUMENT = "DOGE-USDT"
SWAP_INSTRUMENT = "DOGE-USDT-SWAP"
TIMEFRAME = "5m"
BAR_MS = 5 * 60 * 1000
FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000
INITIAL_CASH = 10_000.0
DISCOVERY_START = "2021-01-01"
DISCOVERY_END = "2024-01-01"
BASE_FEE_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
STRESS_SLIPPAGE_BPS = 15.0
FAMILY_TRIALS = 7
SAMPLES = 10_000
SEED = 20260723
OUTPUT_JSON = Path("reports/research/doge_5m_basis_shock_reversion.json")
OUTPUT_MD = Path(
    "docs/research/doge-5m/BASIS_SHOCK_REVERSION_RESULTS_2026-07-23.md"
)


@dataclass(frozen=True)
class BsrParams:
    """Frozen BSR signal and risk parameters."""

    lookback: int = 2_016
    entry_z: float = 4.0
    basis_floor: float = 0.006
    exit_z: float = 0.5
    stop_widen: float = 0.010
    max_hold_bars: int = 12
    cooldown_bars: int = 12
    leg_weight: float = 0.5

    def __post_init__(self) -> None:
        if self.lookback < 2:
            raise ValueError("lookback must be at least two bars")
        if self.entry_z <= self.exit_z:
            raise ValueError("entry z must exceed exit z")
        if self.basis_floor < 0 or self.stop_widen <= 0:
            raise ValueError("basis thresholds must be non-negative")
        if self.max_hold_bars < 1 or self.cooldown_bars < 0:
            raise ValueError("hold and cooldown bars must be non-negative")
        if not 0 < self.leg_weight <= 0.5:
            raise ValueError("each leg weight must be in (0, 0.5]")


@dataclass(frozen=True)
class PairCosts:
    """Per-leg, per-side taker execution costs."""

    fee_bps: float = BASE_FEE_BPS
    slippage_bps: float = BASE_SLIPPAGE_BPS

    def __post_init__(self) -> None:
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("costs cannot be negative")

    @property
    def fee_rate(self) -> float:
        return self.fee_bps / 10_000

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000

    @property
    def per_side_bps(self) -> float:
        return self.fee_bps + self.slippage_bps


@dataclass(frozen=True)
class PairEpisode:
    entry_ts: int
    exit_ts: int
    entry_index: int
    exit_index: int
    holding_bars: int
    entry_equity: float
    net_pnl: float
    return_pct: float
    signal_basis: float
    entry_basis: float
    exit_basis: float
    exit_reason: str


@dataclass
class PairPosition:
    entry_ts: int
    entry_index: int
    entry_equity: float
    signal_basis: float
    entry_basis: float
    spot_entry_fill: float
    swap_entry_fill: float
    spot_quantity: float
    swap_quantity: float
    entry_fees: float
    held_bars: int = 0


@dataclass(frozen=True)
class PairRun:
    timestamps: np.ndarray
    equity: np.ndarray
    episodes: tuple[PairEpisode, ...]
    initial_cash: float
    rejected_entries: int
    delayed_exits: int
    funding_crossings: int

    @property
    def final_equity(self) -> float:
        return float(self.equity[-1]) if len(self.equity) else self.initial_cash


def _series_from_frame(inst_id: str, frame: pd.DataFrame) -> Series:
    return Series(
        inst_id=inst_id,
        timeframe=TIMEFRAME,
        ts=(frame.index.astype("int64") // 1_000_000).to_numpy(),
        open=frame["open"].to_numpy(dtype=float),
        high=frame["high"].to_numpy(dtype=float),
        low=frame["low"].to_numpy(dtype=float),
        close=frame["close"].to_numpy(dtype=float),
        volume=frame["volume"].to_numpy(dtype=float),
    )


def _load_pair(end_ms: int | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    with Store(DB_PATH) as store:
        spot = store.load_ohlcv(SPOT_INSTRUMENT, TIMEFRAME, end_ms=end_ms)
        swap = store.load_ohlcv(SWAP_INSTRUMENT, TIMEFRAME, end_ms=end_ms)

    spot_quality = check_ohlcv(spot, SPOT_INSTRUMENT, TIMEFRAME)
    swap_quality = check_ohlcv(swap, SWAP_INSTRUMENT, TIMEFRAME)
    if not spot_quality.clean or not swap_quality.clean:
        raise RuntimeError(
            "BSR requires clean native 5m data:\n"
            f"{spot_quality.summary()}\n{swap_quality.summary()}"
        )

    common = spot.index.intersection(swap.index)
    if len(common) == 0:
        raise RuntimeError("spot and swap have no paired 5m bars")
    spot_only = spot.index.difference(swap.index)
    swap_only = swap.index.difference(spot.index)
    paired = pd.DataFrame(index=common)
    for prefix, source in (("spot", spot), ("swap", swap)):
        aligned = source.loc[common]
        for column in ("open", "high", "low", "close", "volume"):
            paired[f"{prefix}_{column}"] = aligned[column].to_numpy(dtype=float)

    spot_series = _series_from_frame(SPOT_INSTRUMENT, spot.loc[common])
    swap_series = _series_from_frame(SWAP_INSTRUMENT, swap.loc[common])
    provenance = {
        "spot_bars": len(spot),
        "swap_bars": len(swap),
        "paired_bars": len(paired),
        "spot_only_bars": len(spot_only),
        "swap_only_bars": len(swap_only),
        "spot_zero_volume_bars": len(spot_quality.zero_volume_bars),
        "swap_zero_volume_bars": len(swap_quality.zero_volume_bars),
        "spot_quality": spot_quality.summary(),
        "swap_quality": swap_quality.summary(),
        "spot_fingerprint": series_fingerprint(spot_series),
        "swap_fingerprint": series_fingerprint(swap_series),
        "range": f"{paired.index[0]}..{paired.index[-1]}",
    }
    return paired, provenance


def _add_causal_features(frame: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Return a copy with a basis z-score built strictly from earlier bars."""
    out = frame.copy()
    basis = np.log(out["swap_close"] / out["spot_close"])
    history = basis.shift(1)
    mean = history.rolling(lookback, min_periods=lookback).mean()
    std = history.rolling(lookback, min_periods=lookback).std(ddof=1)
    out["basis"] = basis
    out["basis_mean"] = mean
    out["basis_std"] = std
    out["basis_z"] = (basis - mean) / std.where(std > 0)
    return out


def _next_funding_after(ts_ms: int) -> int:
    """Next default 00/08/16 UTC settlement strictly after an entry open."""
    return (ts_ms // FUNDING_INTERVAL_MS + 1) * FUNDING_INTERVAL_MS


def _funding_safe(ts_ms: int, max_hold_bars: int) -> bool:
    planned_exit = ts_ms + max_hold_bars * BAR_MS
    return planned_exit < _next_funding_after(ts_ms)


def _entry_fills(
    equity: float,
    spot_open: float,
    swap_open: float,
    costs: PairCosts,
    leg_weight: float,
) -> tuple[float, float, float, float, float]:
    notional = equity * leg_weight
    spot_quantity = notional / spot_open
    swap_quantity = notional / swap_open
    spot_fill = spot_open * (1.0 + costs.slippage_rate)
    swap_fill = swap_open * (1.0 - costs.slippage_rate)
    fees = costs.fee_rate * (
        spot_quantity * spot_fill + swap_quantity * swap_fill
    )
    return spot_fill, swap_fill, spot_quantity, swap_quantity, fees


def _mark_equity(position: PairPosition, spot_close: float, swap_close: float) -> float:
    gross_pnl = (
        position.spot_quantity * (spot_close - position.spot_entry_fill)
        + position.swap_quantity * (position.swap_entry_fill - swap_close)
    )
    return position.entry_equity + gross_pnl - position.entry_fees


def _close_position(
    position: PairPosition,
    spot_reference: float,
    swap_reference: float,
    exit_ts: int,
    exit_index: int,
    exit_reason: str,
    costs: PairCosts,
) -> tuple[float, PairEpisode]:
    spot_fill = spot_reference * (1.0 - costs.slippage_rate)
    swap_fill = swap_reference * (1.0 + costs.slippage_rate)
    exit_fees = costs.fee_rate * (
        position.spot_quantity * spot_fill + position.swap_quantity * swap_fill
    )
    gross_pnl = (
        position.spot_quantity * (spot_fill - position.spot_entry_fill)
        + position.swap_quantity * (position.swap_entry_fill - swap_fill)
    )
    net_pnl = gross_pnl - position.entry_fees - exit_fees
    final_equity = position.entry_equity + net_pnl
    holding_bars = max(1, round((exit_ts - position.entry_ts) / BAR_MS))
    episode = PairEpisode(
        entry_ts=position.entry_ts,
        exit_ts=exit_ts,
        entry_index=position.entry_index,
        exit_index=exit_index,
        holding_bars=holding_bars,
        entry_equity=position.entry_equity,
        net_pnl=net_pnl,
        return_pct=net_pnl / position.entry_equity,
        signal_basis=position.signal_basis,
        entry_basis=position.entry_basis,
        exit_basis=float(math.log(swap_reference / spot_reference)),
        exit_reason=exit_reason,
    )
    return final_equity, episode


def _run(
    frame: pd.DataFrame,
    params: BsrParams,
    costs: PairCosts,
    start_ms: int,
    end_ms: int,
    initial_cash: float = INITIAL_CASH,
) -> PairRun:
    """Replay one non-overlapping two-leg portfolio over an evaluation window."""
    ts = (frame.index.astype("int64") // 1_000_000).to_numpy(dtype=np.int64)
    spot_open = frame["spot_open"].to_numpy(dtype=float)
    spot_close = frame["spot_close"].to_numpy(dtype=float)
    spot_volume = frame["spot_volume"].to_numpy(dtype=float)
    swap_open = frame["swap_open"].to_numpy(dtype=float)
    swap_close = frame["swap_close"].to_numpy(dtype=float)
    swap_volume = frame["swap_volume"].to_numpy(dtype=float)
    basis = frame["basis"].to_numpy(dtype=float)
    basis_mean = frame["basis_mean"].to_numpy(dtype=float)
    basis_z = frame["basis_z"].to_numpy(dtype=float)

    indexes = np.flatnonzero((ts >= start_ms) & (ts < end_ms))
    if len(indexes) == 0:
        raise ValueError("evaluation window contains no paired bars")

    capital = float(initial_cash)
    position: PairPosition | None = None
    pending_entry: float | None = None
    pending_exit: str | None = None
    cooldown_until = -1
    episodes: list[PairEpisode] = []
    timestamps: list[int] = []
    equity_curve: list[float] = []
    rejected_entries = 0
    delayed_exits = 0
    funding_crossings = 0

    for idx in indexes:
        # Execute the decision made on the previous bar at this bar's open.
        if pending_exit is not None and position is not None:
            if spot_volume[idx] <= 0 or swap_volume[idx] <= 0:
                delayed_exits += 1
            else:
                if _next_funding_after(position.entry_ts) <= int(ts[idx]):
                    funding_crossings += 1
                capital, episode = _close_position(
                    position,
                    spot_open[idx],
                    swap_open[idx],
                    int(ts[idx]),
                    int(idx),
                    pending_exit,
                    costs,
                )
                episodes.append(episode)
                position = None
                pending_exit = None
                cooldown_until = int(idx) + params.cooldown_bars

        if pending_entry is not None and position is None:
            signal_basis = pending_entry
            pending_entry = None
            if (
                spot_volume[idx] <= 0
                or swap_volume[idx] <= 0
                or not _funding_safe(int(ts[idx]), params.max_hold_bars)
            ):
                rejected_entries += 1
            else:
                (
                    spot_fill,
                    swap_fill,
                    spot_quantity,
                    swap_quantity,
                    entry_fees,
                ) = _entry_fills(
                    capital,
                    spot_open[idx],
                    swap_open[idx],
                    costs,
                    params.leg_weight,
                )
                position = PairPosition(
                    entry_ts=int(ts[idx]),
                    entry_index=int(idx),
                    entry_equity=capital,
                    signal_basis=signal_basis,
                    entry_basis=float(math.log(swap_open[idx] / spot_open[idx])),
                    spot_entry_fill=spot_fill,
                    swap_entry_fill=swap_fill,
                    spot_quantity=spot_quantity,
                    swap_quantity=swap_quantity,
                    entry_fees=entry_fees,
                )

        if position is None:
            marked = capital
        else:
            position.held_bars += 1
            marked = _mark_equity(position, spot_close[idx], swap_close[idx])

        timestamps.append(int(ts[idx]))
        equity_curve.append(marked)

        # Decide only after this bar has closed. A pending exit remains pending
        # across a zero-volume execution bar rather than being overwritten.
        if position is not None:
            if pending_exit is None:
                normalized = np.isfinite(basis_z[idx]) and basis_z[idx] <= params.exit_z
                widened = basis[idx] - position.signal_basis >= params.stop_widen
                timed_out = position.held_bars >= params.max_hold_bars
                if normalized:
                    pending_exit = "basis normalized"
                elif widened:
                    pending_exit = "adverse basis stop"
                elif timed_out:
                    pending_exit = "maximum holding time"
            continue

        if pending_entry is not None or idx < cooldown_until:
            continue
        if idx + 1 >= len(frame) or ts[idx + 1] >= end_ms:
            continue
        if not (
            np.isfinite(basis_z[idx])
            and np.isfinite(basis_mean[idx])
            and basis_z[idx] >= params.entry_z
            and basis[idx] - basis_mean[idx] >= params.basis_floor
        ):
            continue
        entry_ts = int(ts[idx + 1])
        if not _funding_safe(entry_ts, params.max_hold_bars):
            continue
        pending_entry = float(basis[idx])

    # The evaluation boundary is a hard cash boundary. Close at the final
    # paired close, charging both legs' adverse slippage and fees.
    if position is not None:
        last_idx = int(indexes[-1])
        exit_ts = int(ts[last_idx] + BAR_MS)
        if _next_funding_after(position.entry_ts) <= exit_ts:
            funding_crossings += 1
        capital, episode = _close_position(
            position,
            spot_close[last_idx],
            swap_close[last_idx],
            exit_ts,
            last_idx,
            "evaluation boundary",
            costs,
        )
        episodes.append(episode)
        equity_curve[-1] = capital

    return PairRun(
        timestamps=np.asarray(timestamps, dtype=np.int64),
        equity=np.asarray(equity_curve, dtype=float),
        episodes=tuple(episodes),
        initial_cash=initial_cash,
        rejected_entries=rejected_entries,
        delayed_exits=delayed_exits,
        funding_crossings=funding_crossings,
    )


def _summary(run: PairRun) -> dict[str, Any]:
    returns = (
        np.diff(run.equity) / run.equity[:-1]
        if len(run.equity) > 1
        else np.zeros(0, dtype=float)
    )
    periods = bars_per_year(run.timestamps)
    episode_returns = np.asarray([e.return_pct for e in run.episodes], dtype=float)
    bootstrap = bootstrap_trades(episode_returns, samples=SAMPLES, seed=SEED)
    pnls = np.asarray([e.net_pnl for e in run.episodes], dtype=float)
    positive = pnls[pnls > 0]
    negative = pnls[pnls < 0]
    best = float(np.max(pnls)) if len(pnls) else 0.0
    exit_reasons: dict[str, int] = {}
    for episode in run.episodes:
        exit_reasons[episode.exit_reason] = exit_reasons.get(episode.exit_reason, 0) + 1
    return {
        "return": run.final_equity / run.initial_cash - 1.0,
        "sharpe": sharpe_ratio(returns, periods),
        "max_drawdown": max_drawdown(run.equity),
        "trades": len(run.episodes),
        "win_rate": float(np.mean(pnls > 0)) if len(pnls) else 0.0,
        "profit_factor": (
            float(np.sum(positive) / -np.sum(negative))
            if len(negative)
            else (math.inf if len(positive) else 0.0)
        ),
        "mean_episode_return": float(np.mean(episode_returns))
        if len(episode_returns)
        else 0.0,
        "median_episode_return": float(np.median(episode_returns))
        if len(episode_returns)
        else 0.0,
        "mean_hold_minutes": (
            float(np.mean([e.holding_bars for e in run.episodes]) * 5)
            if run.episodes
            else 0.0
        ),
        "return_less_best_1": (run.final_equity - best) / run.initial_cash - 1.0,
        "best_episode_pnl": best,
        "bootstrap_probability_of_loss": bootstrap.probability_of_loss,
        "bootstrap_p05": bootstrap.percentile_05,
        "bootstrap_median": bootstrap.median,
        "bootstrap_p95": bootstrap.percentile_95,
        "rejected_entries": run.rejected_entries,
        "delayed_exits": run.delayed_exits,
        "funding_crossings": run.funding_crossings,
        "exit_reasons": exit_reasons,
    }


def _pair_episode_returns(
    frame: pd.DataFrame,
    entry_indexes: np.ndarray,
    exit_indexes: np.ndarray,
    costs: PairCosts,
    leg_weight: float,
) -> np.ndarray:
    spot_entry = frame["spot_open"].to_numpy(dtype=float)[entry_indexes]
    swap_entry = frame["swap_open"].to_numpy(dtype=float)[entry_indexes]
    spot_exit = frame["spot_open"].to_numpy(dtype=float)[exit_indexes]
    swap_exit = frame["swap_open"].to_numpy(dtype=float)[exit_indexes]
    spot_quantity = leg_weight / spot_entry
    swap_quantity = leg_weight / swap_entry
    spot_entry_fill = spot_entry * (1 + costs.slippage_rate)
    swap_entry_fill = swap_entry * (1 - costs.slippage_rate)
    spot_exit_fill = spot_exit * (1 - costs.slippage_rate)
    swap_exit_fill = swap_exit * (1 + costs.slippage_rate)
    fees = costs.fee_rate * (
        spot_quantity * (spot_entry_fill + spot_exit_fill)
        + swap_quantity * (swap_entry_fill + swap_exit_fill)
    )
    return (
        spot_quantity * (spot_exit_fill - spot_entry_fill)
        + swap_quantity * (swap_entry_fill - swap_exit_fill)
        - fees
    )


def _matched_random_null(
    frame: pd.DataFrame,
    run: PairRun,
    params: BsrParams,
    costs: PairCosts,
    start_ms: int,
    end_ms: int,
) -> dict[str, float | int]:
    """Random entries matched by entry year and realised holding length."""
    if not run.episodes:
        return {
            "samples": SAMPLES,
            "observed": 0.0,
            "null_median": 0.0,
            "raw_p": 1.0,
            "sidak_p": 1.0,
        }

    ts = (frame.index.astype("int64") // 1_000_000).to_numpy(dtype=np.int64)
    spot_volume = frame["spot_volume"].to_numpy(dtype=float)
    swap_volume = frame["swap_volume"].to_numpy(dtype=float)
    evaluation = (ts >= start_ms) & (ts < end_ms)
    rng = np.random.default_rng(SEED)
    totals = np.ones(SAMPLES, dtype=float)

    for episode in run.episodes:
        duration = episode.holding_bars
        year = dt.datetime.fromtimestamp(episode.entry_ts / 1000, dt.UTC).year
        year_start = to_ms(f"{year}-01-01")
        year_end = to_ms(f"{year + 1}-01-01")
        candidates = np.flatnonzero(
            evaluation
            & (ts >= year_start)
            & (ts < year_end)
            & (spot_volume > 0)
            & (swap_volume > 0)
        )
        candidates = candidates[candidates + duration < len(frame)]
        candidates = candidates[ts[candidates + duration] < min(end_ms, year_end)]
        candidates = candidates[
            (spot_volume[candidates + duration] > 0)
            & (swap_volume[candidates + duration] > 0)
        ]
        candidates = candidates[
            np.fromiter(
                (_funding_safe(int(ts[i]), params.max_hold_bars) for i in candidates),
                dtype=bool,
                count=len(candidates),
            )
        ]
        if len(candidates) == 0:
            raise RuntimeError(f"no matched random entries for {year}, hold={duration}")
        entries = rng.choice(candidates, size=SAMPLES, replace=True)
        exits = entries + duration
        totals *= 1.0 + _pair_episode_returns(
            frame, entries, exits, costs, params.leg_weight
        )

    null_returns = totals - 1.0
    observed = float(np.prod(1.0 + np.asarray([e.return_pct for e in run.episodes])) - 1.0)
    raw_p = float((np.sum(null_returns >= observed) + 1) / (SAMPLES + 1))
    return {
        "samples": SAMPLES,
        "observed": observed,
        "null_median": float(np.median(null_returns)),
        "null_p05": float(np.percentile(null_returns, 5)),
        "null_p95": float(np.percentile(null_returns, 95)),
        "raw_p": raw_p,
        "sidak_p": sidak_correction(raw_p, FAMILY_TRIALS),
    }


def _variant_params() -> dict[str, BsrParams]:
    return {
        "main": BsrParams(),
        "z3": BsrParams(entry_z=3.0),
        "z5": BsrParams(entry_z=5.0),
        "floor40": BsrParams(basis_floor=0.004),
        "floor80": BsrParams(basis_floor=0.008),
        "hold6": BsrParams(max_hold_bars=6),
        "hold24": BsrParams(max_hold_bars=24),
    }


def _yearly(
    frame: pd.DataFrame,
    params: BsrParams,
    costs: PairCosts,
    years: range,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year in years:
        run = _run(
            frame,
            params,
            costs,
            to_ms(f"{year}-01-01"),
            to_ms(f"{year + 1}-01-01"),
        )
        row = _summary(run)
        rows.append(
            {
                "year": year,
                "return": row["return"],
                "sharpe": row["sharpe"],
                "max_drawdown": row["max_drawdown"],
                "trades": row["trades"],
                "funding_crossings": row["funding_crossings"],
            }
        )
    return rows


def _discovery_gate(
    main: dict[str, Any],
    stress: dict[str, Any],
    yearly: list[dict[str, Any]],
    variants: dict[str, dict[str, Any]],
    null: dict[str, float | int],
) -> dict[str, Any]:
    checks = [
        ("15bps/leg/side return > 0", main["return"] > 0),
        ("annualized Sharpe >= 1.0", main["sharpe"] >= 1.0),
        ("MaxDD <= 10%", main["max_drawdown"] <= 0.10),
        ("at least 50 closed episodes", main["trades"] >= 50),
        (
            "at least two positive discovery years",
            sum(row["return"] > 0 for row in yearly) >= 2,
        ),
        ("25bps/leg/side stress return > 0", stress["return"] > 0),
        ("return less best episode PnL > 0", main["return_less_best_1"] > 0),
        ("episode bootstrap P5 > 0", main["bootstrap_p05"] > 0),
        (
            "at least five of seven frozen versions positive",
            sum(row["return"] > 0 for row in variants.values()) >= 5,
        ),
        ("matched-random Sidak p <= 0.10", float(null["sidak_p"]) <= 0.10),
        ("no unmodelled funding crossings", main["funding_crossings"] == 0),
    ]
    passed = all(bool(value) for _, value in checks)
    return {
        "passed": passed,
        "verdict": "DISCOVERY PASS" if passed else "DISCOVERY FAIL",
        "checks": [{"name": name, "passed": bool(value)} for name, value in checks],
    }


def _validation_gate(
    main: dict[str, Any], stress: dict[str, Any]
) -> dict[str, Any]:
    checks = [
        ("return > 0", main["return"] > 0),
        ("Sharpe >= 0.75", main["sharpe"] >= 0.75),
        ("MaxDD <= 10%", main["max_drawdown"] <= 0.10),
        ("at least 15 episodes", main["trades"] >= 15),
        ("stress return > 0", stress["return"] > 0),
        ("return less best episode PnL > 0", main["return_less_best_1"] > 0),
        ("no unmodelled funding crossings", main["funding_crossings"] == 0),
    ]
    passed = all(bool(value) for _, value in checks)
    return {
        "passed": passed,
        "verdict": "VALIDATION PASS" if passed else "VALIDATION FAIL",
        "checks": [{"name": name, "passed": bool(value)} for name, value in checks],
    }


def _basis_diagnostics(
    frame: pd.DataFrame, start_ms: int, end_ms: int
) -> dict[str, Any]:
    ts = (frame.index.astype("int64") // 1_000_000).to_numpy(dtype=np.int64)
    mask = (ts >= start_ms) & (ts < end_ms)
    basis = frame.loc[mask, "basis"].to_numpy(dtype=float)
    z = frame.loc[mask, "basis_z"].to_numpy(dtype=float)
    finite_z = z[np.isfinite(z)]
    return {
        "basis_bps_percentiles": {
            str(q): float(np.percentile(basis, q) * 10_000)
            for q in (0.1, 1, 5, 50, 95, 99, 99.9)
        },
        "finite_z_bars": len(finite_z),
        "bars_z_ge_4": int(np.sum(finite_z >= 4.0)),
        "bars_excess_ge_60bps": int(
            np.sum(
                (
                    frame.loc[mask, "basis"] - frame.loc[mask, "basis_mean"]
                ).to_numpy(dtype=float)
                >= 0.006
            )
        ),
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    discovery = payload["discovery"]
    main = discovery["main"]
    stress = discovery["stress"]
    null = discovery["matched_random_null"]
    lines = [
        "# DOGE 5m 现货-永续基差冲击回归结果 (BSR v1)",
        "",
        f"**{discovery['gate']['verdict']}。**",
        "",
        "这是 5 分钟级双腿日内策略研究, 不是撮合级 HFT。信号在闭合 bar 后产生,",
        "两腿都在下一根 open 以 taker 成本成交; 没有历史盘口或挂单成交假设。",
        "",
        "## 发现窗口 (2021-2023)",
        "",
        "| Metric | 主成本 15bps/腿/边 | 压力 25bps/腿/边 |",
        "|---|---:|---:|",
        f"| Return | {_pct(main['return'])} | {_pct(stress['return'])} |",
        f"| Sharpe | {main['sharpe']:.2f} | {stress['sharpe']:.2f} |",
        f"| MaxDD | {_pct(-main['max_drawdown'])} | {_pct(-stress['max_drawdown'])} |",
        f"| Episodes | {main['trades']} | {stress['trades']} |",
        f"| Win rate | {_pct(main['win_rate'])} | {_pct(stress['win_rate'])} |",
        f"| Mean episode | {_pct(main['mean_episode_return'])} | "
        f"{_pct(stress['mean_episode_return'])} |",
        f"| Return less best PnL | {_pct(main['return_less_best_1'])} | "
        f"{_pct(stress['return_less_best_1'])} |",
        f"| Bootstrap P5 | {_pct(main['bootstrap_p05'])} | "
        f"{_pct(stress['bootstrap_p05'])} |",
        "",
        "### 年度",
        "",
        "| Year | Return | Sharpe | MaxDD | Episodes |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in discovery["yearly"]:
        lines.append(
            f"| {row['year']} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} |"
        )
    lines += [
        "",
        "### 冻结邻域",
        "",
        "| Version | Return | Sharpe | MaxDD | Episodes |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, row in discovery["variants"].items():
        lines.append(
            f"| {name} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} |"
        )
    lines += [
        "",
        "### 随机入场与发现门",
        "",
        f"- Observed episode compound: `{_pct(float(null['observed']))}`",
        f"- Matched-random median: `{_pct(float(null['null_median']))}`",
        f"- raw p: `{float(null['raw_p']):.4f}`; Sidak p (7): "
        f"`{float(null['sidak_p']):.4f}`",
        "",
    ]
    for check in discovery["gate"]["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- {mark}: {check['name']}")

    chronological = payload.get("chronological_validation", [])
    if chronological:
        lines += ["", "## 顺序验证", ""]
        for stage in chronological:
            row = stage["main"]
            lines += [
                f"### {stage['year']}: {stage['gate']['verdict']}",
                "",
                f"- Return `{_pct(row['return'])}`; Sharpe `{row['sharpe']:.2f}`; "
                f"MaxDD `{_pct(-row['max_drawdown'])}`; episodes `{row['trades']}`",
                f"- 25bps stress `{_pct(stage['stress']['return'])}`; "
                f"less-best `{_pct(row['return_less_best_1'])}`",
                "",
            ]
    else:
        lines += [
            "",
            "## 顺序验证",
            "",
            "发现门未通过, 按预注册规则没有读取 2024/2025/2026 的 BSR 收益;",
            "不能从后续年份寻找救援参数。",
        ]

    diagnostics = payload["basis_diagnostics"]
    provenance = payload["provenance"]
    lines += [
        "",
        "## 数据与限制",
        "",
        f"- Paired bars: `{provenance['paired_bars']}`; range `{provenance['range']}`",
        f"- Spot/swap zero-volume bars: `{provenance['spot_zero_volume_bars']}` / "
        f"`{provenance['swap_zero_volume_bars']}`",
        f"- Discovery bars with z>=4: `{diagnostics['bars_z_ge_4']}`; "
        f"excess basis >=60bps: `{diagnostics['bars_excess_ge_60bps']}`",
        f"- Spot fingerprint: `{provenance['spot_fingerprint']}`",
        f"- Swap fingerprint: `{provenance['swap_fingerprint']}`",
        "- 缺少历史 bid/ask、盘口深度、两腿原子成交、逐笔数据和实际历史 funding schedule;",
        "  即使过门也只能进入实时盘口 shadow, 不批准真实资金。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    discovery_start = to_ms(DISCOVERY_START)
    discovery_end = to_ms(DISCOVERY_END)
    frame, provenance = _load_pair(end_ms=discovery_end)
    frame = _add_causal_features(frame, BsrParams().lookback)
    costs = PairCosts()
    stress_costs = PairCosts(slippage_bps=STRESS_SLIPPAGE_BPS)
    params_by_name = _variant_params()

    variant_runs = {
        name: _run(frame, params, costs, discovery_start, discovery_end)
        for name, params in params_by_name.items()
    }
    variants = {name: _summary(run) for name, run in variant_runs.items()}
    main_run = variant_runs["main"]
    main = variants["main"]
    stress = _summary(
        _run(
            frame,
            params_by_name["main"],
            stress_costs,
            discovery_start,
            discovery_end,
        )
    )
    yearly = _yearly(frame, params_by_name["main"], costs, range(2021, 2024))
    null = _matched_random_null(
        frame,
        main_run,
        params_by_name["main"],
        costs,
        discovery_start,
        discovery_end,
    )
    discovery_gate = _discovery_gate(main, stress, yearly, variants, null)

    chronological: list[dict[str, Any]] = []
    if discovery_gate["passed"]:
        for year in (2024, 2025):
            start_ms = to_ms(f"{year}-01-01")
            end_ms = to_ms(f"{year + 1}-01-01")
            validation_frame, _ = _load_pair(end_ms=end_ms)
            validation_frame = _add_causal_features(
                validation_frame, params_by_name["main"].lookback
            )
            stage_main = _summary(
                _run(
                    validation_frame,
                    params_by_name["main"],
                    costs,
                    start_ms,
                    end_ms,
                )
            )
            stage_stress = _summary(
                _run(
                    validation_frame,
                    params_by_name["main"],
                    stress_costs,
                    start_ms,
                    end_ms,
                )
            )
            stage_gate = _validation_gate(stage_main, stage_stress)
            chronological.append(
                {
                    "year": year,
                    "main": stage_main,
                    "stress": stage_stress,
                    "gate": stage_gate,
                }
            )
            if not stage_gate["passed"]:
                break

    payload: dict[str, Any] = {
        "study": "doge-5m-basis-shock-reversion-v1",
        "stage": "frozen-discovery",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "protocol": str(
            Path(
                "docs/research/doge-5m/"
                "BASIS_SHOCK_REVERSION_PROTOCOL_2026-07-23.md"
            )
        ),
        "params": {name: asdict(params) for name, params in params_by_name.items()},
        "costs": {
            "main": asdict(costs),
            "stress": asdict(stress_costs),
        },
        "provenance": provenance,
        "basis_diagnostics": _basis_diagnostics(
            frame, discovery_start, discovery_end
        ),
        "discovery": {
            "window": f"{DISCOVERY_START}..{DISCOVERY_END} exclusive",
            "main": main,
            "stress": stress,
            "yearly": yearly,
            "variants": variants,
            "matched_random_null": null,
            "gate": discovery_gate,
        },
        "chronological_validation": chronological,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    report = _render(payload)
    OUTPUT_MD.write_text(report, encoding="utf-8")
    print(report)
    print(f"JSON: {OUTPUT_JSON}")
    print(f"REPORT: {OUTPUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
