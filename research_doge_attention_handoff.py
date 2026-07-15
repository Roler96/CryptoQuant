"""Offline research harness for a DOGE market-structure event strategy.

The hypothesis is deliberately not a conventional price-indicator rule.  It
looks for an extreme six-hour BTC selloff, then asks whether DOGE perpetual
activity has risen relative to DOGE spot activity.  If so, it buys DOGE spot
at the next hourly open and holds for twelve hours.

All signal and execution inputs come from the existing OKX tables.  The local
Binance BTC table is optional and is used only by ``robustness`` as a data-
quality cross-check; it never enters the baseline signal.

This is a discovery harness, not a production strategy.  The repository's
single-feed Strategy/LiveEngine contract cannot yet supply BTC, DOGE spot and
DOGE swap inputs to one live strategy.

Usage:
    uv run python research_doge_attention_handoff.py baseline
    uv run python research_doge_attention_handoff.py robustness
    uv run python research_doge_attention_handoff.py all
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from cryptoquant.data.fetcher import validate_ohlcv
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.engine.latency import RandomLatency
from cryptoquant.risk.sizer import FixedSizer
from cryptoquant.strategy.base import Strategy
from cryptoquant.utils import dataframe_fingerprint
from strategies.doge_attention_handoff_spot import DogeAttentionHandoffSpot



def _timestamp(value: str) -> pd.Timestamp:
    """Narrow pandas' Timestamp-or-NaT constructor type for constants."""
    return cast(pd.Timestamp, pd.Timestamp(value))


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    """Return one numeric column with a type stable across pandas stubs."""
    column = frame[name]
    if not isinstance(column, pd.Series):  # pragma: no cover - string key is scalar
        raise TypeError(f"Expected Series for column {name}")
    return column.astype(float)


def _log_series(series: pd.Series) -> pd.Series:
    """Apply log while preserving Series/index typing."""
    return pd.Series(
        np.log(series.to_numpy(dtype=float)),
        index=series.index,
        dtype=float,
    )


DATA_START: pd.Timestamp = _timestamp("2021-01-01 00:00:00")
DATA_END: pd.Timestamp = _timestamp("2026-07-13 00:00:00")  # exclusive
INITIAL_CAPITAL = 10_000.0
BASE_COMMISSION_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
DEPLOY_POSITION_PCT = 10.0

SEGMENTS: tuple[tuple[str, pd.Timestamp, pd.Timestamp], ...] = (
    ("discovery_train", _timestamp("2021-01-01"), _timestamp("2024-07-01")),
    (
        "discovery_validation",
        _timestamp("2024-07-01"),
        _timestamp("2025-07-01"),
    ),
    ("historical_audit", _timestamp("2025-07-01"), DATA_END),
)


@dataclass(frozen=True)
class SignalSpec:
    """Frozen, causal signal definition in hourly bars."""

    btc_shock_hours: int = 6
    btc_shock_quantile: float = 0.025
    shock_history_hours: int = 90 * 24
    shock_min_history_hours: int = 45 * 24
    volume_block_hours: int = 6
    attention_baseline_hours: int = 24
    hold_hours: int = 12
    cooldown_hours: int = 48


@dataclass(frozen=True)
class MarketSnapshot:
    doge_spot: pd.DataFrame
    doge_swap: pd.DataFrame
    btc_spot: pd.DataFrame
    binance_btc_spot: pd.DataFrame | None = None


@dataclass(frozen=True)
class Evaluation:
    label: str
    return_pct: float
    sharpe: float
    max_drawdown_pct: float
    trades: int
    win_rate_pct: float
    profit_factor: float
    mean_trade_bps: float
    median_trade_bps: float
    worst_trade_pct: float
    exposure_pct: float


class EventPulseStrategy(Strategy):
    """Research-only adapter from a frozen event series to BacktestEngine."""

    timeframe = "1h"
    min_bars = 2
    version = "1.0.0-research-only"
    signal_is_position = False

    def __init__(self, signals: pd.Series):
        self._signals = signals.astype(int).copy()
        super().__init__()

    @property
    def name(self) -> str:
        return "DogeAttentionHandoffResearch"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        self.preprocess(df)
        return self._signals.reindex(df.index).fillna(0).astype(int)


def _load_table(connection: sqlite3.Connection, table: str) -> pd.DataFrame:
    frame = pd.read_sql_query(
        f"SELECT timestamp, open, high, low, close, volume "
        f"FROM {table} ORDER BY timestamp",
        connection,
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms")
    return frame.set_index("timestamp")


def load_snapshot() -> MarketSnapshot:
    """Load a read-only, frozen OKX snapshot and optional audit venue."""
    db_path = Path(__file__).resolve().parent / "data" / "cryptoquant.db"
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        spot = _load_table(connection, "ohlcv_okx_DOGE_USDT_1h")
        swap = _load_table(connection, "ohlcv_okx_DOGE_USDT_SWAP_1h")
        btc = _load_table(connection, "ohlcv_okx_BTC_USDT_1h")
        has_binance = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='ohlcv_binance_BTC_USDT_1h'"
        ).fetchone()
        binance = (
            _load_table(connection, "ohlcv_binance_BTC_USDT_1h")
            if has_binance
            else None
        )
    finally:
        connection.close()

    expected = pd.date_range(
        DATA_START,
        DATA_END - pd.Timedelta(hours=1),
        freq="1h",
    )
    spot = spot.reindex(expected)
    swap = swap.reindex(expected)
    if spot.isna().to_numpy().any() or swap.isna().to_numpy().any():
        raise RuntimeError("DOGE spot/swap snapshot is not a complete hourly panel")
    validate_ohlcv(spot, strict=True)
    validate_ohlcv(swap, strict=True)

    # BTC is intentionally reindexed rather than gap-filled.  A signal is
    # disabled unless every BTC close in its shock window is present.
    btc = btc.reindex(expected)
    if binance is not None:
        binance = binance.reindex(expected)
    return MarketSnapshot(spot, swap, btc, binance)


def build_features(snapshot: MarketSnapshot, spec: SignalSpec) -> pd.DataFrame:
    """Construct causal crash and relative-participation features."""
    btc_close = _column(snapshot.btc_spot, "close")
    btc_impulse = _log_series(btc_close).diff(spec.btc_shock_hours)
    btc_observation_count = cast(
        pd.Series,
        btc_close.notna()
        .rolling(spec.btc_shock_hours + 1, min_periods=spec.btc_shock_hours + 1)
        .sum(),
    )
    btc_complete = btc_observation_count.eq(spec.btc_shock_hours + 1)
    shock_cut = (
        btc_impulse.shift(1)
        .rolling(
            spec.shock_history_hours,
            min_periods=spec.shock_min_history_hours,
        )
        .quantile(spec.btc_shock_quantile)
    )

    spot_block = cast(
        pd.Series,
        _column(snapshot.doge_spot, "volume").rolling(
            spec.volume_block_hours,
            min_periods=spec.volume_block_hours,
        ).sum(),
    )
    swap_block = cast(
        pd.Series,
        _column(snapshot.doge_swap, "volume").rolling(
            spec.volume_block_hours,
            min_periods=spec.volume_block_hours,
        ).sum(),
    )
    log_spot_block = _log_series(spot_block.where(spot_block > 0))
    log_swap_block = _log_series(swap_block.where(swap_block > 0))
    log_ratio = log_swap_block - log_spot_block

    # Exclude the latest volume_block_hours observations from the baseline.
    # Otherwise its rolling blocks overlap the current event block and leak
    # much of the shock into its own comparator.
    ratio_baseline = (
        log_ratio.shift(spec.volume_block_hours)
        .rolling(
            spec.attention_baseline_hours,
            min_periods=spec.attention_baseline_hours,
        )
        .median()
    )
    attention = log_ratio - ratio_baseline

    # Unit-robust ablation: normalize each venue against its own past first,
    # then subtract.  Fixed contract/base-volume multipliers cancel.
    spot_baseline = (
        log_spot_block.shift(spec.volume_block_hours)
        .rolling(
            spec.attention_baseline_hours,
            min_periods=spec.attention_baseline_hours,
        )
        .median()
    )
    swap_baseline = (
        log_swap_block.shift(spec.volume_block_hours)
        .rolling(
            spec.attention_baseline_hours,
            min_periods=spec.attention_baseline_hours,
        )
        .median()
    )
    attention_self_normalized = (
        (log_swap_block - swap_baseline) - (log_spot_block - spot_baseline)
    )

    features = pd.DataFrame(index=snapshot.doge_spot.index)
    features["btc_impulse"] = btc_impulse
    features["btc_shock_cut"] = shock_cut
    features["btc_window_complete"] = btc_complete
    features["btc_crash"] = btc_complete & (btc_impulse < shock_cut)
    features["log_volume_ratio"] = log_ratio
    features["attention"] = attention
    features["attention_self_normalized"] = attention_self_normalized
    return features


def build_event_signal(features: pd.DataFrame, mode: str = "attention_positive") -> pd.Series:
    """Return raw long-entry events for a named mechanism or placebo."""
    crash = features["btc_crash"].fillna(False)
    if mode == "attention_positive":
        gate = features["attention"] > 0
    elif mode == "attention_nonpositive":
        gate = features["attention"] <= 0
    elif mode == "self_normalized_positive":
        gate = features["attention_self_normalized"] > 0
    elif mode == "attention_lagged_24h":
        gate = features["attention"].shift(24) > 0
    elif mode == "crash_only":
        gate = pd.Series(True, index=features.index)
    else:
        raise ValueError(f"Unknown signal mode: {mode}")
    return (crash & gate.fillna(False)).astype(int)


def build_production_frame(snapshot: MarketSnapshot) -> pd.DataFrame:
    """Assemble exactly the frame consumed by the shipped spot strategy."""
    frame = snapshot.doge_spot.copy()
    frame["swap_volume"] = _column(snapshot.doge_swap, "volume")
    frame["btc_close"] = _column(snapshot.btc_spot, "close")
    return frame


def assert_production_signal_parity(
    snapshot: MarketSnapshot,
    research_events: pd.Series,
    spec: SignalSpec,
) -> None:
    """Fail the signed baseline if research and shipped signals diverge."""
    if spec != SignalSpec():
        raise ValueError("Production parity is defined only for the frozen SignalSpec")
    # Production must emit a current signal without asking whether twelve
    # future bars exist. Complete-trade censoring belongs only to a historical
    # backtest at the right edge of its sample.
    expected = apply_cooldown(
        research_events,
        spec,
        require_complete_trade=False,
    )
    actual = DogeAttentionHandoffSpot().generate_signal(
        build_production_frame(snapshot)
    )
    pd.testing.assert_series_equal(actual, expected, check_names=False)


def apply_cooldown(
    events: pd.Series,
    spec: SignalSpec,
    *,
    delay_hours: int = 0,
    require_complete_trade: bool = True,
) -> pd.Series:
    """Keep causal, non-overlapping events with a signal-to-signal cooldown."""
    selected = pd.Series(0, index=events.index, dtype=int)
    blocked_until = -1
    n = len(events)
    for position in np.flatnonzero(events.fillna(0).to_numpy(dtype=int)):
        entry_position = position + 1 + delay_hours
        exit_position = entry_position + spec.hold_hours
        if position < blocked_until or (
            require_complete_trade and exit_position >= n
        ):
            continue
        selected.iloc[position] = 1
        blocked_until = max(position + spec.cooldown_hours, exit_position)
    return selected


def evaluate(
    snapshot: MarketSnapshot,
    raw_events: pd.Series,
    spec: SignalSpec,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    label: str,
    position_pct: float = 100.0,
    commission_bps: float = BASE_COMMISSION_BPS,
    slippage_bps: float = BASE_SLIPPAGE_BPS,
    delay_hours: int = 0,
) -> Evaluation:
    """Backtest one cold-start interval with next-open execution."""
    sample = snapshot.doge_spot.loc[
        (snapshot.doge_spot.index >= start)
        & (snapshot.doge_spot.index < end)
    ]
    interval_events = raw_events.reindex(sample.index).fillna(0).astype(int)
    selected = apply_cooldown(interval_events, spec, delay_hours=delay_hours)
    strategy = EventPulseStrategy(selected)
    sizer = (
        None
        if position_pct >= 100
        else FixedSizer(risk_pct=position_pct, min_order=0.0)
    )
    engine = BacktestEngine(
        initial_capital=INITIAL_CAPITAL,
        commission=commission_bps / 10_000,
        slippage=slippage_bps / 10_000,
        sizer=sizer,
    )
    if delay_hours:
        engine.latency_model = RandomLatency(
            min_bars=delay_hours,
            max_bars=delay_hours,
            seed=0,
        )
    result = engine.run(
        sample,
        strategy,
        symbol="DOGE/USDT",
        max_hold_bars=spec.hold_hours,
    )
    expected_trades = int(selected.sum())
    if len(result.trades) != expected_trades:
        raise RuntimeError(
            f"Event/execution mismatch for {label}: "
            f"selected={expected_trades}, trades={len(result.trades)}"
        )

    trade_pnls = np.array([trade.pnl_pct for trade in result.trades], dtype=float)
    period_hours = max(1.0, (end - start).total_seconds() / 3600)
    exposure_hours = sum(trade.hold_hours for trade in result.trades)
    metrics = result.metrics
    return Evaluation(
        label=label,
        return_pct=metrics.total_return_pct,
        sharpe=metrics.sharpe_ratio,
        max_drawdown_pct=-metrics.max_drawdown_pct,
        trades=metrics.total_trades,
        win_rate_pct=metrics.win_rate_pct,
        profit_factor=metrics.profit_factor,
        mean_trade_bps=float(trade_pnls.mean() * 100) if len(trade_pnls) else 0.0,
        median_trade_bps=float(np.median(trade_pnls) * 100) if len(trade_pnls) else 0.0,
        worst_trade_pct=float(trade_pnls.min()) if len(trade_pnls) else 0.0,
        exposure_pct=exposure_hours / period_hours * 100,
    )


def _frame(evaluations: list[Evaluation]) -> pd.DataFrame:
    return pd.DataFrame([evaluation.__dict__ for evaluation in evaluations])


def _print_frame(frame: pd.DataFrame) -> None:
    print(frame.to_string(index=False, float_format=lambda value: f"{value:.3f}"))


def print_snapshot(snapshot: MarketSnapshot) -> None:
    print(
        f"OKX hourly snapshot: rows={len(snapshot.doge_spot)}, "
        f"range={snapshot.doge_spot.index[0]}..{snapshot.doge_spot.index[-1]}, "
        f"BTC_missing={int(snapshot.btc_spot['close'].isna().sum())}"
    )
    print(f"DOGE spot sha256={dataframe_fingerprint(snapshot.doge_spot)}")
    print(f"DOGE swap sha256={dataframe_fingerprint(snapshot.doge_swap)}")
    print(f"OKX BTC sha256={dataframe_fingerprint(snapshot.btc_spot)}")


def run_baseline(snapshot: MarketSnapshot, spec: SignalSpec) -> None:
    features = build_features(snapshot, spec)
    raw_events = build_event_signal(features)
    assert_production_signal_parity(snapshot, raw_events, spec)

    evaluations = [
        evaluate(
            snapshot,
            raw_events,
            spec,
            DATA_START,
            DATA_END,
            label="full_signal_1x_15bps_side",
        ),
        evaluate(
            snapshot,
            raw_events,
            spec,
            DATA_START,
            DATA_END,
            label="full_deploy_10pct_15bps_side",
            position_pct=DEPLOY_POSITION_PCT,
        ),
    ]
    evaluations.extend(
        evaluate(
            snapshot,
            raw_events,
            spec,
            start,
            end,
            label=f"{label}_deploy_10pct",
            position_pct=DEPLOY_POSITION_PCT,
        )
        for label, start, end in SEGMENTS
    )
    for year in range(2021, 2027):
        start = _timestamp(f"{year}-01-01")
        end = min(_timestamp(f"{year + 1}-01-01"), DATA_END)
        evaluations.append(
            evaluate(
                snapshot,
                raw_events,
                spec,
                start,
                end,
                label=f"year_{year}_deploy_10pct",
                position_pct=DEPLOY_POSITION_PCT,
            )
        )

    print("\nBASELINE AND TIME SEGMENTS")
    _print_frame(_frame(evaluations))

    ablations = []
    for mode in (
        "attention_positive",
        "attention_nonpositive",
        "crash_only",
        "attention_lagged_24h",
        "self_normalized_positive",
    ):
        events = build_event_signal(features, mode)
        ablations.append(
            evaluate(
                snapshot,
                events,
                spec,
                DATA_START,
                DATA_END,
                label=mode,
                position_pct=DEPLOY_POSITION_PCT,
            )
        )
    print("\nMECHANISM ABLATIONS")
    _print_frame(_frame(ablations))


def _segment_edges(
    snapshot: MarketSnapshot,
    events: pd.Series,
    spec: SignalSpec,
) -> list[Evaluation]:
    return [
        evaluate(
            snapshot,
            events,
            spec,
            start,
            end,
            label=label,
            position_pct=DEPLOY_POSITION_PCT,
        )
        for label, start, end in SEGMENTS
    ]


def _neighborhood_specs(spec: SignalSpec) -> list[tuple[str, SignalSpec]]:
    variants: list[tuple[str, SignalSpec]] = []
    for value in (3, 4, 6, 8, 12):
        variants.append((f"btc_shock_hours={value}", replace(spec, btc_shock_hours=value)))
    for value in (0.01, 0.025, 0.05):
        variants.append(
            (f"btc_shock_quantile={value}", replace(spec, btc_shock_quantile=value))
        )
    for value in (6, 8, 12, 18, 24):
        variants.append((f"hold_hours={value}", replace(spec, hold_hours=value)))
    for value in (3, 6, 12):
        variants.append(
            (f"volume_block_hours={value}", replace(spec, volume_block_hours=value))
        )
    for value in (12, 24, 48):
        variants.append(
            (
                f"attention_baseline_hours={value}",
                replace(spec, attention_baseline_hours=value),
            )
        )
    for value in (24, 48, 72):
        variants.append(
            (f"cooldown_hours={value}", replace(spec, cooldown_hours=value))
        )
    for days in (60, 90, 180):
        variants.append(
            (
                f"shock_history_days={days}",
                replace(
                    spec,
                    shock_history_hours=days * 24,
                    shock_min_history_hours=(days * 24) // 2,
                ),
            )
        )
    # Deduplicate the frozen center points repeated by each one-factor list.
    unique: dict[SignalSpec, str] = {}
    for label, variant in variants:
        unique.setdefault(variant, label)
    return [(label, variant) for variant, label in unique.items()]


def _run_data_guard(
    snapshot: MarketSnapshot,
    features: pd.DataFrame,
    events: pd.Series,
    spec: SignalSpec,
) -> None:
    if snapshot.binance_btc_spot is None:
        print("\nDATA GUARD: skipped (local Binance BTC audit table is absent)")
        return
    secondary = _column(snapshot.binance_btc_spot, "close")
    last_secondary = secondary.last_valid_index()
    if not isinstance(last_secondary, pd.Timestamp):
        print("\nDATA GUARD: skipped (local Binance BTC audit table is empty)")
        return
    secondary_end = cast(
        pd.Timestamp,
        last_secondary + pd.Timedelta(hours=1),
    )
    audit_end: pd.Timestamp = min(DATA_END, secondary_end)
    okx_close = _column(snapshot.btc_spot, "close")
    okx_return = _log_series(okx_close).diff()
    secondary_return = _log_series(secondary).diff()
    return_gap_bps = (
        (okx_return - secondary_return)
        .abs()
        .rolling(spec.btc_shock_hours, min_periods=spec.btc_shock_hours)
        .max()
        * 10_000
    )
    price_gap_bps = (
        _log_series(okx_close / secondary)
        .abs()
        .rolling(spec.btc_shock_hours, min_periods=spec.btc_shock_hours)
        .max()
        * 10_000
    )
    guard = (return_gap_bps <= 20) & (price_gap_bps <= 20)
    # Freeze the originally accepted events first, then delete suspect ones.
    # Filtering raw events before cooldown could silently replace a deleted
    # event with a later event from the same crash cluster and flatter the
    # audit result.
    audit_events = events.loc[
        (events.index >= DATA_START) & (events.index < audit_end)
    ]
    accepted_events = apply_cooldown(audit_events, spec)
    guarded_events = accepted_events.where(
        guard.reindex(accepted_events.index).fillna(False), 0
    ).astype(int)
    comparisons = [
        evaluate(
            snapshot,
            accepted_events,
            spec,
            DATA_START,
            audit_end,
            label="same_range_unfiltered",
            position_pct=DEPLOY_POSITION_PCT,
        ),
        evaluate(
            snapshot,
            guarded_events,
            spec,
            DATA_START,
            audit_end,
            label="exclude_cross_venue_gap_gt_20bps",
            position_pct=DEPLOY_POSITION_PCT,
        ),
    ]
    print(f"\nDATA GUARD THROUGH {audit_end} (secondary venue is audit-only)")
    _print_frame(_frame(comparisons))


def run_robustness(snapshot: MarketSnapshot, spec: SignalSpec) -> None:
    features = build_features(snapshot, spec)
    raw_events = build_event_signal(features)

    stress = []
    for slippage_bps in (5.0, 15.0, 40.0):
        stress.append(
            evaluate(
                snapshot,
                raw_events,
                spec,
                DATA_START,
                DATA_END,
                label=f"cost_{BASE_COMMISSION_BPS + slippage_bps:.0f}bps_side",
                position_pct=DEPLOY_POSITION_PCT,
                slippage_bps=slippage_bps,
            )
        )
    for delay in (1, 2, 4):
        stress.append(
            evaluate(
                snapshot,
                raw_events,
                spec,
                DATA_START,
                DATA_END,
                label=f"entry_delay_{delay}h",
                position_pct=DEPLOY_POSITION_PCT,
                delay_hours=delay,
            )
        )
    print("\nCOST AND DELAY STRESS")
    _print_frame(_frame(stress))

    neighborhood_rows = []
    for label, variant in _neighborhood_specs(spec):
        variant_features = build_features(snapshot, variant)
        events = build_event_signal(variant_features)
        full = evaluate(
            snapshot,
            events,
            variant,
            DATA_START,
            DATA_END,
            label=label,
            position_pct=DEPLOY_POSITION_PCT,
        )
        segments = _segment_edges(snapshot, events, variant)
        neighborhood_rows.append(
            {
                "variant": label,
                "trades": full.trades,
                "return_pct": full.return_pct,
                "mean_trade_bps": full.mean_trade_bps,
                "development_bps": segments[0].mean_trade_bps,
                "validation_bps": segments[1].mean_trade_bps,
                "audit_bps": segments[2].mean_trade_bps,
                "positive_segments": sum(
                    evaluation.mean_trade_bps > 0 for evaluation in segments
                ),
            }
        )
    print("\nONE-FACTOR PARAMETER NEIGHBORHOOD (not ranked)")
    _print_frame(pd.DataFrame(neighborhood_rows))

    _run_data_guard(snapshot, features, raw_events, spec)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "robustness", "all"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    snapshot = load_snapshot()
    spec = SignalSpec()
    print_snapshot(snapshot)
    print(f"Frozen signal spec: {spec}")
    if args.phase in ("baseline", "all"):
        run_baseline(snapshot, spec)
    if args.phase in ("robustness", "all"):
        run_robustness(snapshot, spec)


if __name__ == "__main__":
    main()
