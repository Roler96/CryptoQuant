#!/usr/bin/env python
"""Frozen DOGE 5m synchronized impulse continuation study (SIC v1).

The rule, seven-version family, costs and gates were frozen in
``SYNCHRONIZED_IMPULSE_CONTINUATION_PROTOCOL_2026-07-23.md`` before any SIC
return was read. Signals use closed swap and spot bars and execute on the next
swap open. The discovery query is hard-capped before 2024.
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

from cq.research.metrics import bars_per_year, max_drawdown, sharpe_ratio
from cq.research.split import to_ms
from cq.research.stats import bootstrap_trades, sidak_correction
from research.explore_doge_5m_basis_shock_reversion import (
    BAR_MS,
    BASE_FEE_BPS,
    BASE_SLIPPAGE_BPS,
    DISCOVERY_END,
    DISCOVERY_START,
    FAMILY_TRIALS,
    INITIAL_CASH,
    SEED,
    STRESS_SLIPPAGE_BPS,
    PairCosts,
    _funding_safe,
    _load_pair,
    _next_funding_after,
)

SAMPLES = 10_000
OUTPUT_JSON = Path("reports/research/doge_5m_synchronized_impulse.json")
OUTPUT_MD = Path(
    "docs/research/doge-5m/SYNCHRONIZED_IMPULSE_CONTINUATION_RESULTS_2026-07-23.md"
)


@dataclass(frozen=True)
class SicParams:
    lookback: int = 2_016
    impulse_bars: int = 3
    score_threshold: float = 4.0
    volume_ratio: float = 3.0
    spot_fraction: float = 0.5
    hold_bars: int = 6
    cooldown_bars: int = 6
    weight: float = 0.5

    def __post_init__(self) -> None:
        if self.lookback < 2 or self.impulse_bars < 1:
            raise ValueError("lookback and impulse horizon must be positive")
        if self.score_threshold <= 0 or self.volume_ratio <= 0:
            raise ValueError("shock thresholds must be positive")
        if not 0 <= self.spot_fraction <= 1:
            raise ValueError("spot fraction must be in [0, 1]")
        if self.hold_bars < 1 or self.cooldown_bars < 0:
            raise ValueError("hold and cooldown bars must be non-negative")
        if not 0 < self.weight <= 1:
            raise ValueError("position weight must be in (0, 1]")


@dataclass(frozen=True)
class SicEpisode:
    entry_ts: int
    exit_ts: int
    entry_index: int
    exit_index: int
    side: int
    holding_bars: int
    entry_equity: float
    net_pnl: float
    return_pct: float
    entry_price: float
    exit_price: float
    signal_score: float
    signal_volume_ratio: float
    exit_reason: str


@dataclass
class SicPosition:
    entry_ts: int
    entry_index: int
    side: int
    entry_equity: float
    entry_fill: float
    quantity: float
    entry_fee: float
    signal_score: float
    signal_volume_ratio: float
    held_bars: int = 0


@dataclass(frozen=True)
class SicRun:
    timestamps: np.ndarray
    equity: np.ndarray
    episodes: tuple[SicEpisode, ...]
    initial_cash: float
    rejected_entries: int
    delayed_exits: int
    funding_crossings: int

    @property
    def final_equity(self) -> float:
        return float(self.equity[-1]) if len(self.equity) else self.initial_cash


def _add_causal_features(frame: pd.DataFrame, params: SicParams) -> pd.DataFrame:
    """Build impulse, volatility and volume features without the current baseline bar."""
    out = frame.copy()
    swap_log = out["swap_close"].astype(float).map(math.log)
    spot_log = out["spot_close"].astype(float).map(math.log)
    swap_return = swap_log.diff()
    sigma = (
        swap_return.shift(1)
        .rolling(params.lookback, min_periods=params.lookback)
        .std(ddof=1)
    )
    swap_impulse = swap_log.diff(params.impulse_bars)
    spot_impulse = spot_log.diff(params.impulse_bars)
    volume_median = (
        out["swap_volume"]
        .shift(1)
        .rolling(params.lookback, min_periods=params.lookback)
        .median()
    )
    recent_volume = out["swap_volume"].rolling(
        params.impulse_bars, min_periods=params.impulse_bars
    ).sum()
    out["swap_return"] = swap_return
    out["swap_impulse"] = swap_impulse
    out["spot_impulse"] = spot_impulse
    out["sigma"] = sigma
    out["shock_score"] = swap_impulse / (math.sqrt(params.impulse_bars) * sigma)
    out["volume_ratio"] = recent_volume / (
        params.impulse_bars * volume_median.where(volume_median > 0)
    )
    return out


def _entry_side(score: float, swap_impulse: float, spot_impulse: float) -> int:
    if not all(np.isfinite(value) for value in (score, swap_impulse, spot_impulse)):
        return 0
    if swap_impulse == 0 or spot_impulse == 0:
        return 0
    side = 1 if swap_impulse > 0 else -1
    return side if (spot_impulse > 0) == (swap_impulse > 0) else 0


def _entry_fill(
    equity: float,
    reference: float,
    side: int,
    costs: PairCosts,
    weight: float,
) -> tuple[float, float, float]:
    notional = equity * weight
    quantity = notional / reference
    fill = reference * (1.0 + side * costs.slippage_rate)
    fee = quantity * fill * costs.fee_rate
    return fill, quantity, fee


def _mark_equity(position: SicPosition, close: float) -> float:
    return (
        position.entry_equity
        + position.side * position.quantity * (close - position.entry_fill)
        - position.entry_fee
    )


def _close_position(
    position: SicPosition,
    reference: float,
    exit_ts: int,
    exit_index: int,
    reason: str,
    costs: PairCosts,
) -> tuple[float, SicEpisode]:
    fill = reference * (1.0 - position.side * costs.slippage_rate)
    exit_fee = position.quantity * fill * costs.fee_rate
    net_pnl = (
        position.side * position.quantity * (fill - position.entry_fill)
        - position.entry_fee
        - exit_fee
    )
    equity = position.entry_equity + net_pnl
    holding_bars = max(1, round((exit_ts - position.entry_ts) / BAR_MS))
    return equity, SicEpisode(
        entry_ts=position.entry_ts,
        exit_ts=exit_ts,
        entry_index=position.entry_index,
        exit_index=exit_index,
        side=position.side,
        holding_bars=holding_bars,
        entry_equity=position.entry_equity,
        net_pnl=net_pnl,
        return_pct=net_pnl / position.entry_equity,
        entry_price=position.entry_fill,
        exit_price=fill,
        signal_score=position.signal_score,
        signal_volume_ratio=position.signal_volume_ratio,
        exit_reason=reason,
    )


def _run(
    frame: pd.DataFrame,
    params: SicParams,
    costs: PairCosts,
    start_ms: int,
    end_ms: int,
    initial_cash: float = INITIAL_CASH,
) -> SicRun:
    ts = (frame.index.astype("int64") // 1_000_000).to_numpy(dtype=np.int64)
    swap_open = frame["swap_open"].to_numpy(dtype=float)
    swap_close = frame["swap_close"].to_numpy(dtype=float)
    swap_volume = frame["swap_volume"].to_numpy(dtype=float)
    swap_impulse = frame["swap_impulse"].to_numpy(dtype=float)
    spot_impulse = frame["spot_impulse"].to_numpy(dtype=float)
    score = frame["shock_score"].to_numpy(dtype=float)
    volume_ratio = frame["volume_ratio"].to_numpy(dtype=float)
    indexes = np.flatnonzero((ts >= start_ms) & (ts < end_ms))
    if len(indexes) == 0:
        raise ValueError("evaluation window contains no paired bars")

    capital = float(initial_cash)
    position: SicPosition | None = None
    pending_entry: tuple[int, float, float] | None = None
    pending_exit = False
    cooldown_until = -1
    timestamps: list[int] = []
    equity_curve: list[float] = []
    episodes: list[SicEpisode] = []
    rejected_entries = 0
    delayed_exits = 0
    funding_crossings = 0

    for idx in indexes:
        if pending_exit and position is not None:
            if swap_volume[idx] <= 0:
                delayed_exits += 1
            else:
                if _next_funding_after(position.entry_ts) <= int(ts[idx]):
                    funding_crossings += 1
                capital, episode = _close_position(
                    position,
                    swap_open[idx],
                    int(ts[idx]),
                    int(idx),
                    "fixed holding time",
                    costs,
                )
                episodes.append(episode)
                position = None
                pending_exit = False
                cooldown_until = int(idx) + params.cooldown_bars

        if pending_entry is not None and position is None:
            side, signal_score, signal_volume = pending_entry
            pending_entry = None
            if swap_volume[idx] <= 0 or not _funding_safe(
                int(ts[idx]), params.hold_bars
            ):
                rejected_entries += 1
            else:
                fill, quantity, fee = _entry_fill(
                    capital,
                    swap_open[idx],
                    side,
                    costs,
                    params.weight,
                )
                position = SicPosition(
                    entry_ts=int(ts[idx]),
                    entry_index=int(idx),
                    side=side,
                    entry_equity=capital,
                    entry_fill=fill,
                    quantity=quantity,
                    entry_fee=fee,
                    signal_score=signal_score,
                    signal_volume_ratio=signal_volume,
                )

        if position is None:
            marked = capital
        else:
            position.held_bars += 1
            marked = _mark_equity(position, swap_close[idx])
        timestamps.append(int(ts[idx]))
        equity_curve.append(marked)

        if position is not None:
            if position.held_bars >= params.hold_bars:
                pending_exit = True
            continue
        if idx < cooldown_until or idx + 1 >= len(frame) or ts[idx + 1] >= end_ms:
            continue
        side = _entry_side(score[idx], swap_impulse[idx], spot_impulse[idx])
        confirmed = (
            side != 0
            and abs(score[idx]) >= params.score_threshold
            and np.isfinite(volume_ratio[idx])
            and volume_ratio[idx] >= params.volume_ratio
            and abs(spot_impulse[idx])
            >= params.spot_fraction * abs(swap_impulse[idx])
        )
        if not confirmed:
            continue
        entry_ts = int(ts[idx + 1])
        if not _funding_safe(entry_ts, params.hold_bars):
            continue
        pending_entry = (side, float(score[idx]), float(volume_ratio[idx]))

    if position is not None:
        last_idx = int(indexes[-1])
        exit_ts = int(ts[last_idx] + BAR_MS)
        if _next_funding_after(position.entry_ts) <= exit_ts:
            funding_crossings += 1
        capital, episode = _close_position(
            position,
            swap_close[last_idx],
            exit_ts,
            last_idx,
            "evaluation boundary",
            costs,
        )
        episodes.append(episode)
        equity_curve[-1] = capital

    return SicRun(
        timestamps=np.asarray(timestamps, dtype=np.int64),
        equity=np.asarray(equity_curve, dtype=float),
        episodes=tuple(episodes),
        initial_cash=initial_cash,
        rejected_entries=rejected_entries,
        delayed_exits=delayed_exits,
        funding_crossings=funding_crossings,
    )


def _summary(run: SicRun) -> dict[str, Any]:
    returns = (
        np.diff(run.equity) / run.equity[:-1]
        if len(run.equity) > 1
        else np.zeros(0, dtype=float)
    )
    episode_returns = np.asarray([e.return_pct for e in run.episodes], dtype=float)
    pnls = np.asarray([e.net_pnl for e in run.episodes], dtype=float)
    bootstrap = bootstrap_trades(episode_returns, samples=SAMPLES, seed=SEED)
    positive = pnls[pnls > 0]
    negative = pnls[pnls < 0]
    best = float(np.max(pnls)) if len(pnls) else 0.0
    longs = sum(e.side > 0 for e in run.episodes)
    shorts = sum(e.side < 0 for e in run.episodes)
    return {
        "return": run.final_equity / run.initial_cash - 1.0,
        "sharpe": sharpe_ratio(returns, bars_per_year(run.timestamps)),
        "max_drawdown": max_drawdown(run.equity),
        "trades": len(run.episodes),
        "longs": longs,
        "shorts": shorts,
        "win_rate": float(np.mean(pnls > 0)) if len(pnls) else 0.0,
        "profit_factor": (
            float(np.sum(positive) / -np.sum(negative))
            if len(negative)
            else None
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
    }


def _episode_returns_at(
    frame: pd.DataFrame,
    entries: np.ndarray,
    exits: np.ndarray,
    sides: np.ndarray,
    costs: PairCosts,
    weight: float,
) -> np.ndarray:
    opens = frame["swap_open"].to_numpy(dtype=float)
    entry = opens[entries]
    exit_ = opens[exits]
    quantity = weight / entry
    entry_fill = entry * (1.0 + sides * costs.slippage_rate)
    exit_fill = exit_ * (1.0 - sides * costs.slippage_rate)
    fees = quantity * (entry_fill + exit_fill) * costs.fee_rate
    return sides * quantity * (exit_fill - entry_fill) - fees


def _matched_random_null(
    frame: pd.DataFrame,
    run: SicRun,
    params: SicParams,
    costs: PairCosts,
    start_ms: int,
    end_ms: int,
) -> dict[str, float | int]:
    if not run.episodes:
        return {
            "samples": SAMPLES,
            "observed": 0.0,
            "null_median": 0.0,
            "raw_p": 1.0,
            "sidak_p": 1.0,
        }
    ts = (frame.index.astype("int64") // 1_000_000).to_numpy(dtype=np.int64)
    volume = frame["swap_volume"].to_numpy(dtype=float)
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
            & (volume > 0)
        )
        candidates = candidates[candidates + duration < len(frame)]
        candidates = candidates[ts[candidates + duration] < min(year_end, end_ms)]
        candidates = candidates[volume[candidates + duration] > 0]
        candidates = candidates[
            np.fromiter(
                (_funding_safe(int(ts[i]), params.hold_bars) for i in candidates),
                dtype=bool,
                count=len(candidates),
            )
        ]
        if len(candidates) == 0:
            raise RuntimeError(f"no random candidates for {year}, hold={duration}")
        entries = rng.choice(candidates, size=SAMPLES, replace=True)
        exits = entries + duration
        sides = np.full(SAMPLES, episode.side, dtype=float)
        totals *= 1.0 + _episode_returns_at(
            frame, entries, exits, sides, costs, params.weight
        )

    null_returns = totals - 1.0
    observed = float(np.prod(1.0 + np.asarray([e.return_pct for e in run.episodes])) - 1)
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


def _sign_flip_diagnostic(
    frame: pd.DataFrame,
    run: SicRun,
    params: SicParams,
    costs: PairCosts,
) -> dict[str, float | int]:
    """Post-result sign control on identical entries; never a candidate or gate."""
    if not run.episodes:
        return {
            "episodes": 0,
            "continuation_zero_cost_compound": 0.0,
            "continuation_zero_cost_mean": 0.0,
            "flipped_net_compound": 0.0,
            "flipped_net_mean": 0.0,
        }
    entries = np.asarray([episode.entry_index for episode in run.episodes], dtype=int)
    exits = np.asarray([episode.exit_index for episode in run.episodes], dtype=int)
    sides = np.asarray([episode.side for episode in run.episodes], dtype=float)
    zero_cost = _episode_returns_at(
        frame,
        entries,
        exits,
        sides,
        PairCosts(fee_bps=0.0, slippage_bps=0.0),
        params.weight,
    )
    flipped = _episode_returns_at(
        frame,
        entries,
        exits,
        -sides,
        costs,
        params.weight,
    )
    return {
        "episodes": len(run.episodes),
        "continuation_zero_cost_compound": float(np.prod(1.0 + zero_cost) - 1.0),
        "continuation_zero_cost_mean": float(np.mean(zero_cost)),
        "flipped_net_compound": float(np.prod(1.0 + flipped) - 1.0),
        "flipped_net_mean": float(np.mean(flipped)),
    }


def _variant_params() -> dict[str, SicParams]:
    return {
        "main": SicParams(),
        "score3": SicParams(score_threshold=3.0),
        "score5": SicParams(score_threshold=5.0),
        "volume2": SicParams(volume_ratio=2.0),
        "volume5": SicParams(volume_ratio=5.0),
        "hold3": SicParams(hold_bars=3),
        "hold12": SicParams(hold_bars=12),
    }


def _yearly(
    frame: pd.DataFrame, params: SicParams, costs: PairCosts, years: range
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year in years:
        summary = _summary(
            _run(
                frame,
                params,
                costs,
                to_ms(f"{year}-01-01"),
                to_ms(f"{year + 1}-01-01"),
            )
        )
        rows.append(
            {
                "year": year,
                "return": summary["return"],
                "sharpe": summary["sharpe"],
                "max_drawdown": summary["max_drawdown"],
                "trades": summary["trades"],
                "longs": summary["longs"],
                "shorts": summary["shorts"],
                "funding_crossings": summary["funding_crossings"],
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
        ("15bps/side return > 0", main["return"] > 0),
        ("annualized Sharpe >= 0.75", main["sharpe"] >= 0.75),
        ("MaxDD <= 20%", main["max_drawdown"] <= 0.20),
        ("at least 100 episodes", main["trades"] >= 100),
        (
            "at least two positive discovery years",
            sum(row["return"] > 0 for row in yearly) >= 2,
        ),
        ("25bps/side stress return > 0", stress["return"] > 0),
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
        ("Sharpe >= 0.50", main["sharpe"] >= 0.50),
        ("MaxDD <= 20%", main["max_drawdown"] <= 0.20),
        ("at least 25 episodes", main["trades"] >= 25),
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


def _diagnostics(
    frame: pd.DataFrame, params: SicParams, start_ms: int, end_ms: int
) -> dict[str, Any]:
    ts = (frame.index.astype("int64") // 1_000_000).to_numpy(dtype=np.int64)
    mask = (ts >= start_ms) & (ts < end_ms)
    score = frame.loc[mask, "shock_score"].to_numpy(dtype=float)
    volume = frame.loc[mask, "volume_ratio"].to_numpy(dtype=float)
    swap_impulse = frame.loc[mask, "swap_impulse"].to_numpy(dtype=float)
    spot_impulse = frame.loc[mask, "spot_impulse"].to_numpy(dtype=float)
    finite_score = score[np.isfinite(score)]
    same_sign = (swap_impulse > 0) == (spot_impulse > 0)
    confirmed = (
        np.isfinite(score)
        & np.isfinite(volume)
        & (np.abs(score) >= params.score_threshold)
        & (volume >= params.volume_ratio)
        & same_sign
        & (swap_impulse != 0)
        & (spot_impulse != 0)
        & (np.abs(spot_impulse) >= params.spot_fraction * np.abs(swap_impulse))
    )
    return {
        "finite_score_bars": len(finite_score),
        "abs_score_percentiles": {
            str(q): float(np.percentile(np.abs(finite_score), q))
            for q in (50, 90, 95, 99, 99.9)
        },
        "raw_confirmed_bars": int(np.sum(confirmed)),
        "positive_confirmed_bars": int(np.sum(confirmed & (swap_impulse > 0))),
        "negative_confirmed_bars": int(np.sum(confirmed & (swap_impulse < 0))),
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    discovery = payload["discovery"]
    main = discovery["main"]
    stress = discovery["stress"]
    null = discovery["matched_random_null"]
    lines = [
        "# DOGE 5m 现货确认的永续冲击延续结果 (SIC v1)",
        "",
        f"**{discovery['gate']['verdict']}。**",
        "",
        "SIC 在极端 15m 永续价格/量能冲击且现货同向确认后,",
        "于下一根 5m open 顺势持有 0.5x 永续 30 分钟。",
        "",
        "## 发现窗口 (2021-2023)",
        "",
        "| Metric | 主成本 15bps/边 | 压力 25bps/边 |",
        "|---|---:|---:|",
        f"| Return | {_pct(main['return'])} | {_pct(stress['return'])} |",
        f"| Sharpe | {main['sharpe']:.2f} | {stress['sharpe']:.2f} |",
        f"| MaxDD | {_pct(-main['max_drawdown'])} | {_pct(-stress['max_drawdown'])} |",
        f"| Episodes | {main['trades']} | {stress['trades']} |",
        f"| Long / Short | {main['longs']} / {main['shorts']} | "
        f"{stress['longs']} / {stress['shorts']} |",
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
        "| Year | Return | Sharpe | MaxDD | Episodes | Long/Short |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in discovery["yearly"]:
        lines.append(
            f"| {row['year']} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} | "
            f"{row['longs']}/{row['shorts']} |"
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
        f"- Observed compound: `{_pct(float(null['observed']))}`",
        f"- Matched-random median: `{_pct(float(null['null_median']))}`",
        f"- raw p: `{float(null['raw_p']):.4f}`; Sidak p (7): "
        f"`{float(null['sidak_p']):.4f}`",
        "",
    ]
    for check in discovery["gate"]["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- {mark}: {check['name']}")

    sign_flip = discovery["posthoc_sign_flip_diagnostic"]
    lines += [
        "",
        "### 事后符号诊断 (非候选)",
        "",
        f"- 原方向零成本复合收益: "
        f"`{_pct(sign_flip['continuation_zero_cost_compound'])}`; "
        f"平均每笔 `{_pct(sign_flip['continuation_zero_cost_mean'])}`",
        f"- 相同入场/持仓机械反向、计主成本: "
        f"`{_pct(sign_flip['flipped_net_compound'])}`; "
        f"平均每笔 `{_pct(sign_flip['flipped_net_mean'])}`",
        "- 该诊断在看到 continuation 失败后才计算, 不得作为新候选或用来打开后续年份。",
    ]

    chronological = payload["chronological_validation"]
    if chronological:
        lines += ["", "## 顺序验证", ""]
        for stage in chronological:
            row = stage["main"]
            lines += [
                f"### {stage['year']}: {stage['gate']['verdict']}",
                "",
                f"- Return `{_pct(row['return'])}`; Sharpe `{row['sharpe']:.2f}`; "
                f"MaxDD `{_pct(-row['max_drawdown'])}`; episodes `{row['trades']}`",
                f"- Stress `{_pct(stage['stress']['return'])}`; less-best "
                f"`{_pct(row['return_less_best_1'])}`",
                "",
            ]
    else:
        lines += [
            "",
            "## 顺序验证",
            "",
            "发现门未通过, 最终 runner 没有查询或计算 2024+ 的 SIC 收益。",
        ]

    provenance = payload["provenance"]
    diagnostics = payload["diagnostics"]
    lines += [
        "",
        "## 数据与限制",
        "",
        f"- Paired bars: `{provenance['paired_bars']}`; range `{provenance['range']}`",
        f"- Raw confirmed bars: `{diagnostics['raw_confirmed_bars']}` "
        f"(positive `{diagnostics['positive_confirmed_bars']}`, "
        f"negative `{diagnostics['negative_confirmed_bars']}`)",
        f"- Spot fingerprint: `{provenance['spot_fingerprint']}`",
        f"- Swap fingerprint: `{provenance['swap_fingerprint']}`",
        "- K 线 volume 不区分主动方向或强平, 且没有历史盘口和实际动态 funding schedule。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    discovery_start = to_ms(DISCOVERY_START)
    discovery_end = to_ms(DISCOVERY_END)
    raw, provenance = _load_pair(end_ms=discovery_end)
    params_by_name = _variant_params()
    frame = _add_causal_features(raw, params_by_name["main"])
    costs = PairCosts(fee_bps=BASE_FEE_BPS, slippage_bps=BASE_SLIPPAGE_BPS)
    stress_costs = PairCosts(
        fee_bps=BASE_FEE_BPS, slippage_bps=STRESS_SLIPPAGE_BPS
    )

    variant_runs = {
        name: _run(frame, params, costs, discovery_start, discovery_end)
        for name, params in params_by_name.items()
    }
    variants = {name: _summary(run) for name, run in variant_runs.items()}
    main_run = variant_runs["main"]
    main_summary = variants["main"]
    stress_summary = _summary(
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
    sign_flip = _sign_flip_diagnostic(
        frame, main_run, params_by_name["main"], costs
    )
    gate = _discovery_gate(
        main_summary, stress_summary, yearly, variants, null
    )

    chronological: list[dict[str, Any]] = []
    if gate["passed"]:
        for year in (2024, 2025):
            start_ms = to_ms(f"{year}-01-01")
            end_ms = to_ms(f"{year + 1}-01-01")
            validation_raw, _ = _load_pair(end_ms=end_ms)
            validation_frame = _add_causal_features(
                validation_raw, params_by_name["main"]
            )
            validation_main = _summary(
                _run(
                    validation_frame,
                    params_by_name["main"],
                    costs,
                    start_ms,
                    end_ms,
                )
            )
            validation_stress = _summary(
                _run(
                    validation_frame,
                    params_by_name["main"],
                    stress_costs,
                    start_ms,
                    end_ms,
                )
            )
            validation_gate = _validation_gate(
                validation_main, validation_stress
            )
            chronological.append(
                {
                    "year": year,
                    "main": validation_main,
                    "stress": validation_stress,
                    "gate": validation_gate,
                }
            )
            if not validation_gate["passed"]:
                break

    payload: dict[str, Any] = {
        "study": "doge-5m-synchronized-impulse-continuation-v1",
        "stage": "frozen-discovery",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "protocol": str(
            Path(
                "docs/research/doge-5m/"
                "SYNCHRONIZED_IMPULSE_CONTINUATION_PROTOCOL_2026-07-23.md"
            )
        ),
        "params": {name: asdict(params) for name, params in params_by_name.items()},
        "costs": {
            "main": asdict(costs),
            "stress": asdict(stress_costs),
        },
        "provenance": provenance,
        "diagnostics": _diagnostics(
            frame, params_by_name["main"], discovery_start, discovery_end
        ),
        "discovery": {
            "window": f"{DISCOVERY_START}..{DISCOVERY_END} exclusive",
            "main": main_summary,
            "stress": stress_summary,
            "yearly": yearly,
            "variants": variants,
            "matched_random_null": null,
            "posthoc_sign_flip_diagnostic": sign_flip,
            "gate": gate,
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
