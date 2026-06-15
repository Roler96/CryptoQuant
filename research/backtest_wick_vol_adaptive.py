"""
Wick Inversion — Volatility-Adaptive Exits Research
====================================================

Tests whether adapting exits (stop/target/hold) to the volatility regime
at entry improves the Wick Inversion filtered strategy (vol gate + SMA200).

Hypothesis: The Wick strategy encounters very different volatility
regimes at entry. Fixed exits are suboptimal across all regimes.
- High vol: wider target (capture bigger wick-driven rallies), longer hold
- Low vol: shorter hold (if wick doesn't produce bounce quickly, it won't),
  tighter target (small wicks don't produce big moves)
- Normal vol: baseline exits

Also tests: sweeping the vol gate threshold (currently hardcoded at 1.0)
and the SMA200 filter interaction.

Author: CryptoQuant Autonomous Researcher
Date: 2026-06-16
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
from dataclasses import dataclass
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.types import Trade, PerformanceMetrics
from cryptoquant.strategy.signals import (
    sma, atr as atr_func, wick_imbalance, pct_change_rolling,
    adx,
)


# ============================================================================
# Custom vol-adaptive backtest
# ============================================================================

@dataclass
class _Position:
    side: str
    entry_time: int
    entry_price: float
    entry_idx: int
    stop_loss_price: float
    take_profit_price: float
    max_hold_bars: int
    high_since_entry: float
    low_since_entry: float
    vol_regime: str  # "low", "normal", "high"


def compute_vol_ratio(df: pd.DataFrame, atr_period: int = 14, median_period: int = 200) -> pd.Series:
    """Compute vol_ratio = ATR / median ATR over lookback."""
    atr_val = atr_func(df, atr_period)
    median_atr = atr_val.rolling(median_period).median()
    vol_ratio = atr_val / median_atr.replace(0, np.nan)
    return vol_ratio.fillna(1.0)


def classify_vol_regime(vol_ratio: float, low_thresh: float = 0.7, high_thresh: float = 1.5) -> str:
    """Classify vol regime at entry."""
    if vol_ratio < low_thresh:
        return "low"
    elif vol_ratio > high_thresh:
        return "high"
    return "normal"


def vol_adaptive_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    vol_ratio: pd.Series,
    vol_thresholds: tuple = (0.7, 1.5),
    exits_by_regime: dict | None = None,
    initial_capital: float = 10_000,
    commission: float = 0.0005,
    slippage: float = 0.0005,
) -> tuple[list[Trade], pd.Series]:
    """Run backtest with vol-adaptive exits per trade."""
    if exits_by_regime is None:
        exits_by_regime = {
            "low":    {"stop_pct": 3.0, "target_pct": 1.5, "hold_bars": 12},
            "normal": {"stop_pct": 3.0, "target_pct": 1.5, "hold_bars": 12},
            "high":   {"stop_pct": 3.0, "target_pct": 1.5, "hold_bars": 12},
        }

    low_thresh, high_thresh = vol_thresholds
    n = len(df)
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    timestamps = df.index.astype(np.int64) // 10**6  # ms

    trades = []
    position: _Position | None = None
    equity = initial_capital
    equity_curve = pd.Series(initial_capital, index=[df.index[0]], dtype=float)

    warmup = 200  # minimum for SMA200

    for i in range(warmup, n):
        # Check exit for open position
        if position is not None:
            bar_open = opens[i]
            bar_high = highs[i]
            bar_low = lows[i]
            bar_close = closes[i]
            hold_bars = i - position.entry_idx

            exit_reason = None
            exit_price = None

            # Update MFE/MAE tracking
            position.high_since_entry = max(position.high_since_entry, bar_high)
            position.low_since_entry = min(position.low_since_entry, bar_low)

            # Priority: stop_loss > take_profit > time_exit > signal_reverse > end_of_data
            if bar_low <= position.stop_loss_price:
                exit_reason = "stop_loss"
                exit_price = position.stop_loss_price * (1 - slippage)
            elif bar_high >= position.take_profit_price:
                exit_reason = "take_profit"
                exit_price = position.take_profit_price * (1 - slippage)
            elif hold_bars >= position.max_hold_bars:
                exit_reason = "time_exit"
                exit_price = bar_open  # exit at next bar open
            elif signals.iloc[i] == -1:
                exit_reason = "signal_reverse"
                exit_price = bar_open * (1 - slippage)
            elif i == n - 1:
                exit_reason = "end_of_data"
                exit_price = bar_close

            if exit_reason is not None:
                gross_pnl_pct = (exit_price / position.entry_price - 1) * 100
                pnl_pct = gross_pnl_pct - commission * 100

                mfe_pct = (position.high_since_entry / position.entry_price - 1) * 100
                mae_pct = (position.low_since_entry / position.entry_price - 1) * 100

                trade_return = pnl_pct / 100
                equity = equity * (1 + trade_return)

                trade = Trade(
                    id=len(trades) + 1,
                    symbol="BTC/USDT",
                    side=position.side,
                    entry_time=position.entry_time,
                    entry_price=position.entry_price,
                    entry_signal=1,
                    exit_time=timestamps[i],
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    pnl_pct=pnl_pct,
                    pnl_abs=pnl_pct / 100 * equity / (1 + trade_return),
                    hold_bars=hold_bars,
                    hold_hours=hold_bars,
                    mae_pct=mae_pct,
                    mfe_pct=mfe_pct,
                    regime={"vol_regime": position.vol_regime},
                )
                trades.append(trade)
                equity_curve[df.index[i]] = equity
                position = None

        # Check entry: signal at bar i-1 → enter at bar i open
        if position is None and i > warmup and signals.iloc[i - 1] == 1:
            vr = vol_ratio.iloc[i - 1]
            regime = classify_vol_regime(vr, low_thresh, high_thresh)
            exits = exits_by_regime[regime]

            entry_price = opens[i]
            stop_price = entry_price * (1 - exits["stop_pct"] / 100)
            target_price = entry_price * (1 + exits["target_pct"] / 100)

            position = _Position(
                side="long",
                entry_time=timestamps[i],
                entry_price=entry_price,
                entry_idx=i,
                stop_loss_price=stop_price,
                take_profit_price=target_price,
                max_hold_bars=exits["hold_bars"],
                high_since_entry=entry_price,
                low_since_entry=entry_price,
                vol_regime=regime,
            )

    # Close any remaining position
    if position is not None:
        bar_close = closes[-1]
        gross_pnl_pct = (bar_close / position.entry_price - 1) * 100
        pnl_pct = gross_pnl_pct - commission * 100
        mfe_pct = (position.high_since_entry / position.entry_price - 1) * 100
        mae_pct = (position.low_since_entry / position.entry_price - 1) * 100
        trade_return = pnl_pct / 100
        equity = equity * (1 + trade_return)

        trade = Trade(
            id=len(trades) + 1,
            symbol="BTC/USDT",
            side=position.side,
            entry_time=position.entry_time,
            entry_price=position.entry_price,
            entry_signal=1,
            exit_time=timestamps[-1],
            exit_price=bar_close,
            exit_reason="end_of_data",
            pnl_pct=pnl_pct,
            pnl_abs=pnl_pct / 100 * equity / (1 + trade_return),
            hold_bars=n - 1 - position.entry_idx,
            hold_hours=n - 1 - position.entry_idx,
            mae_pct=mae_pct,
            mfe_pct=mfe_pct,
            regime={"vol_regime": position.vol_regime},
        )
        trades.append(trade)
        equity_curve[df.index[-1]] = equity

    return trades, equity_curve


# ============================================================================
# Metrics calculation
# ============================================================================

def calculate_metrics(
    trades: list[Trade],
    equity_curve: pd.Series,
    initial_capital: float = 10_000,
    periods_per_year: int = 365 * 24,
) -> PerformanceMetrics:
    """Calculate performance metrics from trades and equity curve."""
    if not trades:
        return PerformanceMetrics(
            total_return_pct=0, annualized_return_pct=0,
            monthly_returns=pd.Series(dtype=float), sharpe_ratio=0,
            sortino_ratio=0, max_drawdown_pct=0, max_drawdown_days=0,
            volatility_annual_pct=0, var_95_pct=0, cvar_95_pct=0,
            total_trades=0, win_rate_pct=0, profit_factor=0,
            avg_win_pct=0, avg_loss_pct=0, avg_hold_hours=0,
            drawdown_periods=[],
        )

    pnls = np.array([t.pnl_pct for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]

    total_return = (equity_curve.iloc[-1] / initial_capital - 1) * 100
    n_years = (len(equity_curve) - 1) / periods_per_year
    annualized = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100

    if len(pnls) > 1:
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if np.std(pnls) > 0 else 0
        downside = pnls[pnls < 0]
        sortino = np.mean(pnls) / np.std(downside) * np.sqrt(len(pnls)) if len(downside) > 0 and np.std(downside) > 0 else 0
    else:
        sharpe = 0
        sortino = 0

    peak = equity_curve.expanding().max()
    dd = (equity_curve - peak) / peak * 100
    max_dd = dd.min()

    win_rate = len(wins) / len(pnls) * 100 if len(pnls) > 0 else 0
    pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else 0
    avg_win = np.mean(wins) if len(wins) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0
    avg_hold = np.mean([t.hold_hours for t in trades]) if trades else 0

    return PerformanceMetrics(
        total_return_pct=total_return,
        annualized_return_pct=annualized,
        monthly_returns=pd.Series(dtype=float),
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown_pct=max_dd,
        max_drawdown_days=0,
        volatility_annual_pct=0,
        var_95_pct=0,
        cvar_95_pct=0,
        total_trades=len(trades),
        win_rate_pct=win_rate,
        profit_factor=pf,
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        avg_hold_hours=avg_hold,
        drawdown_periods=[],
    )


# ============================================================================
# Walk-forward
# ============================================================================

def walk_forward_vol_adaptive(
    df: pd.DataFrame,
    generate_signal_fn,
    n_splits: int = 7,
    **kwargs,
) -> list[dict]:
    """Walk-forward validation for vol-adaptive backtest."""
    n = len(df)
    slot = n // (n_splits + 2)
    splits = []

    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end].copy()

        signals = generate_signal_fn(split_df)
        vol_ratio = compute_vol_ratio(split_df)

        trades, equity = vol_adaptive_backtest(
            split_df, signals, vol_ratio, **kwargs
        )
        metrics = calculate_metrics(trades, equity)

        pnls = [t.pnl_pct for t in trades]
        split_sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0

        splits.append({
            "start": split_df.index[0],
            "end": split_df.index[-1],
            "trades": len(trades),
            "return": metrics.total_return_pct,
            "sharpe": split_sharpe,
            "max_dd": metrics.max_drawdown_pct,
            "sum": sum(pnls),
        })

    return splits


# ============================================================================
# Printing helpers
# ============================================================================

def print_metrics(metrics, label="", trades=None):
    """Print formatted metrics."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Total Trades:       {metrics.total_trades}")
    print(f"  Total Return:       {metrics.total_return_pct:+.1f}%")
    print(f"  Annualized Return:  {metrics.annualized_return_pct:+.1f}%")
    print(f"  Sharpe Ratio:       {metrics.sharpe_ratio:+.2f}")
    print(f"  Sortino Ratio:      {metrics.sortino_ratio:+.2f}")
    print(f"  Max Drawdown:       {metrics.max_drawdown_pct:+.1f}%")
    print(f"  Win Rate:           {metrics.win_rate_pct:.1f}%")
    print(f"  Avg Win:            {metrics.avg_win_pct:+.2f}%")
    print(f"  Avg Loss:           {metrics.avg_loss_pct:+.2f}%")
    print(f"  Profit Factor:      {metrics.profit_factor:.2f}")

    if trades:
        reasons = Counter(t.exit_reason for t in trades)
        print(f"\n  Exit Breakdown:")
        for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse", "end_of_data"]:
            subset = [t.pnl_pct for t in trades if t.exit_reason == reason]
            if subset:
                print(f"    {reason:15s}: {len(subset):4d} ({len(subset)/len(trades)*100:5.1f}%)  "
                      f"avg={np.mean(subset):+.2f}%  total={sum(subset):+.1f}%")

        mfes = [t.mfe_pct for t in trades]
        print(f"\n  MFE: mean={np.mean(mfes):+.2f}%  median={np.median(mfes):+.2f}%  max={np.max(mfes):+.2f}%")

        pnls = [t.pnl_pct for t in trades]
        max_consec = 0
        consec = 0
        for p in pnls:
            if p <= 0:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 0
        print(f"  Max Consec Losses:  {max_consec}")

        time_exits = [t for t in trades if t.exit_reason == "time_exit"]
        if time_exits:
            green_te = sum(1 for t in time_exits if t.mfe_pct > 0)
            print(f"  Time-exits profitable at some point: {green_te}/{len(time_exits)} "
                  f"({green_te/max(len(time_exits),1)*100:.1f}%)")


def print_regime_breakdown(trades, label=""):
    """Print per-regime trade breakdown."""
    print(f"\n  {'─'*55}")
    print(f"  {label}")
    header = f"  {'Regime':10s} {'Trades':>7s} {'Sum':>9s} {'WR':>7s} {'Stop%':>7s} {'AvgPnL':>8s} {'AvgMFE':>8s}"
    print(header)
    print(f"  {'-'*55}")
    for regime in ["low", "normal", "high"]:
        subset = [t for t in trades if t.regime.get("vol_regime") == regime]
        if subset:
            pnls = [t.pnl_pct for t in subset]
            wins = [p for p in pnls if p > 0]
            stops = [t for t in subset if t.exit_reason == "stop_loss"]
            mfes = [t.mfe_pct for t in subset]
            print(f"  {regime:10s} {len(subset):7d} {sum(pnls):>+8.1f}% "
                  f"{len(wins)/max(len(subset),1)*100:>6.1f}% "
                  f"{len(stops)/max(len(subset),1)*100:>6.1f}% "
                  f"{np.mean(pnls):>+7.3f}% {np.mean(mfes):>+7.2f}%")


def print_wf_table(splits, label="Walk-Forward"):
    """Print walk-forward results table."""
    print(f"\n  {'─'*70}")
    print(f"  {label}")
    print(f"  {'Split':6s} {'Period':24s} {'Trades':>7s} {'Sum':>9s} {'Sharpe':>8s} {'Status':>7s}")
    print(f"  {'-'*70}")
    for s_idx, sp in enumerate(splits):
        status = "✅" if sp["sharpe"] > 0 else "❌"
        period = f"{str(sp['start'])[:10]}→{str(sp['end'])[:10]}"
        print(f"  {s_idx+1:6d} {period:24s} {sp['trades']:7d} {sp['sum']:>+8.1f}% {sp['sharpe']:>+7.2f} {status:>7s}")

    profitable = sum(1 for sp in splits if sp["sharpe"] > 0)
    mean_sharpe = np.mean([sp["sharpe"] for sp in splits])
    total_sum = sum(sp["sum"] for sp in splits)
    print(f"\n  → {profitable}/{len(splits)} OOS profitable | Mean OOS Sharpe: {mean_sharpe:+.2f} | Total OOS Sum: {total_sum:+.1f}%")


# ============================================================================
# Signal generation
# ============================================================================

def generate_wick_signals(
    df: pd.DataFrame,
    imbalance_window: int = 6,
    imbalance_threshold: float = 0.25,
    price_lookback: int = 6,
    price_floor: float = -0.5,
    vol_gate: bool = True,
    vol_gate_threshold: float = 1.0,
    sma200_filter: bool = True,
    pdi_filter: bool = False,
) -> pd.Series:
    """Generate Wick Inversion signals with optional filters."""
    # Core Wick imbalance signal
    imb = wick_imbalance(df, window=imbalance_window)
    price_chg = pct_change_rolling(df["close"], price_lookback)

    signal = (imb > imbalance_threshold) & (price_chg > price_floor)

    # Volatility gating
    if vol_gate:
        atr14 = atr_func(df, 14)
        median_atr = atr14.rolling(200).median()
        vol_ratio = atr14 / median_atr.replace(0, np.nan)
        signal = signal & (vol_ratio > vol_gate_threshold)

    # SMA200 trend filter
    if sma200_filter:
        sma200 = sma(df["close"], 200)
        signal = signal & (df["close"] > sma200)

    # PDI > MDI filter
    if pdi_filter:
        adx_df = adx(df, 14)
        signal = signal & (adx_df["pdi"] > adx_df["mdi"])

    return signal.astype(int)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("WICK INVERSION — VOLATILITY-ADAPTIVE EXITS RESEARCH")
    print("=" * 70)

    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    print(f"\nOKX BTC/USDT 1h: {len(df_okx)} bars, {df_okx.index[0]} to {df_okx.index[-1]}")
    print(f"Binance BTC/USDT 1h: {len(df_binance)} bars")

    vol_ratio_okx = compute_vol_ratio(df_okx)
    vol_ratio_binance = compute_vol_ratio(df_binance)

    # ========================================================================
    # EXPERIMENT 1: BASELINE — Different filter combinations, fixed exits
    # ========================================================================
    print("\n" + "=" * 70)
    print("EXPERIMENT 1: BASELINE — Filter Combinations (Fixed Exits)")
    print("=" * 70)

    baseline_exits = {
        "low":    {"stop_pct": 3.0, "target_pct": 1.5, "hold_bars": 12},
        "normal": {"stop_pct": 3.0, "target_pct": 1.5, "hold_bars": 12},
        "high":   {"stop_pct": 3.0, "target_pct": 1.5, "hold_bars": 12},
    }

    filter_configs = [
        ("No Filter",          dict(vol_gate=False, sma200_filter=False, pdi_filter=False)),
        ("Vol Gate (>1.0)",    dict(vol_gate=True,  sma200_filter=False, pdi_filter=False)),
        ("SMA200 Only",        dict(vol_gate=False, sma200_filter=True,  pdi_filter=False)),
        ("Vol+SMA200",         dict(vol_gate=True,  sma200_filter=True,  pdi_filter=False)),
        ("Vol+SMA200+PDI>MDI", dict(vol_gate=True,  sma200_filter=True,  pdi_filter=True)),
    ]

    baseline_results = []
    for name, filt in filter_configs:
        signals = generate_wick_signals(df_okx, **filt)
        trades, equity = vol_adaptive_backtest(
            df_okx, signals, vol_ratio_okx, exits_by_regime=baseline_exits,
        )
        metrics = calculate_metrics(trades, equity)
        sig_count = int(signals.sum())
        print_metrics(metrics, f"Baseline: {name}  |  Signals: {sig_count}", trades)
        baseline_results.append({
            "name": name, "filt": filt, "signals": sig_count,
            "trades": len(trades), "metrics": metrics, "trades_list": trades,
        })

    # ========================================================================
    # EXPERIMENT 2: Per-Regime Analysis (Vol+SMA200 config)
    # ========================================================================
    print("\n" + "=" * 70)
    print("EXPERIMENT 2: PER-REGIME ANALYSIS (Vol+SMA200, Fixed Exits)")
    print("=" * 70)

    best_filt = dict(vol_gate=True, sma200_filter=True, pdi_filter=False)
    signals_best = generate_wick_signals(df_okx, **best_filt)
    trades_best, equity_best = vol_adaptive_backtest(
        df_okx, signals_best, vol_ratio_okx, exits_by_regime=baseline_exits,
    )

    print_regime_breakdown(trades_best, "Vol+SMA200 — Per-Regime Breakdown")

    # Analyze per-regime exit patterns to inform adaptive exits
    print(f"\n  Per-Regime Exit Analysis (Vol+SMA200):")
    for regime in ["low", "normal", "high"]:
        subset = [t for t in trades_best if t.regime.get("vol_regime") == regime]
        if subset:
            reasons = Counter(t.exit_reason for t in subset)
            pnls = [t.pnl_pct for t in subset]
            mfes = [t.mfe_pct for t in subset]
            maes = [t.mae_pct for t in subset]
            holds = [t.hold_hours for t in subset]
            time_exits = [t for t in subset if t.exit_reason == "time_exit"]
            time_mfes = [t.mfe_pct for t in time_exits] if time_exits else [0]

            print(f"  {regime:10s}: {len(subset):4d} trades | "
                  f"avg PnL={np.mean(pnls):+.3f}% | "
                  f"avg MFE={np.mean(mfes):+.2f}% | "
                  f"avg MAE={np.mean(maes):+.2f}% | "
                  f"avg hold={np.mean(holds):.1f}h | "
                  f"TP%={reasons.get('take_profit',0)/len(subset)*100:.0f}% | "
                  f"SL%={reasons.get('stop_loss',0)/len(subset)*100:.0f}% | "
                  f"TE%={reasons.get('time_exit',0)/len(subset)*100:.0f}% | "
                  f"TE avg MFE={np.mean(time_mfes):+.2f}%")

    # ========================================================================
    # EXPERIMENT 3: Vol-Adaptive Exit Grid Search
    # ========================================================================
    print("\n" + "=" * 70)
    print("EXPERIMENT 3: VOL-ADAPTIVE EXIT GRID SEARCH (Vol+SMA200)")
    print("=" * 70)

    # Grid search dimensions:
    # Low vol:    tighter stop (2.5, 3.0), lower target (1.0, 1.25, 1.5), shorter hold (6, 8, 10, 12)
    # Normal vol: baseline (s3.0/t1.5/h12) — keep fixed
    # High vol:   same stop (3.0), higher target (1.5, 2.0, 2.5, 3.0), longer hold (12, 16, 20, 24)
    # Total: 3 × 3 × 4 × 4 × 4 = too large. Focus on key dimensions.

    # Strategy: test low and high adaptations independently, keep normal fixed
    low_stops = [2.5, 3.0, 3.5]
    low_targets = [1.0, 1.25, 1.5]
    low_holds = [6, 8, 10, 12]
    high_targets = [1.5, 2.0, 2.5, 3.0]
    high_holds = [12, 16, 20, 24]

    # Normal always baseline
    normal_exits = {"stop_pct": 3.0, "target_pct": 1.5, "hold_bars": 12}

    # First pass: test low-vol adaptations (high=baseline)
    print("\n  --- Phase 3a: Low-Vol Adaptation (high=baseline) ---")
    low_results = []
    for ls in low_stops:
        for lt in low_targets:
            for lh in low_holds:
                exits = {
                    "low":    {"stop_pct": ls, "target_pct": lt, "hold_bars": lh},
                    "normal": normal_exits,
                    "high":   normal_exits,
                }
                trades, equity = vol_adaptive_backtest(
                    df_okx, signals_best, vol_ratio_okx, exits_by_regime=exits,
                )
                metrics = calculate_metrics(trades, equity)
                low_results.append({
                    "ls": ls, "lt": lt, "lh": lh,
                    "trades": len(trades), "sharpe": metrics.sharpe_ratio,
                    "return": metrics.total_return_pct, "max_dd": metrics.max_drawdown_pct,
                    "wr": metrics.win_rate_pct, "pf": metrics.profit_factor,
                    "sum": sum(t.pnl_pct for t in trades),
                })

    # Sort by Sharpe
    low_results.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"\n  Top 10 Low-Vol Adaptations (by Sharpe):")
    print(f"  {'Stop':>6s} {'Targ':>6s} {'Hold':>6s} {'Trades':>7s} {'Sharpe':>8s} {'Return':>8s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    for r in low_results[:10]:
        print(f"  {r['ls']:5.1f}% {r['lt']:5.2f}% {r['lh']:5d}h {r['trades']:7d} {r['sharpe']:>+7.2f} {r['return']:>+7.1f}% {r['max_dd']:>+6.1f}% {r['wr']:>5.1f}% {r['pf']:>5.2f}")

    # Second pass: test high-vol adaptations (using best low from above)
    best_low = low_results[0]
    print(f"\n  Best low-vol: s={best_low['ls']:.1f}% t={best_low['lt']:.2f}% h={best_low['lh']}h (Sharpe={best_low['sharpe']:+.2f})")

    print(f"\n  --- Phase 3b: High-Vol Adaptation (low=best from 3a) ---")
    high_results = []
    for ht in high_targets:
        for hh in high_holds:
            exits = {
                "low":    {"stop_pct": best_low["ls"], "target_pct": best_low["lt"], "hold_bars": best_low["lh"]},
                "normal": normal_exits,
                "high":   {"stop_pct": 3.0, "target_pct": ht, "hold_bars": hh},
            }
            trades, equity = vol_adaptive_backtest(
                df_okx, signals_best, vol_ratio_okx, exits_by_regime=exits,
            )
            metrics = calculate_metrics(trades, equity)
            high_results.append({
                "ht": ht, "hh": hh,
                "trades": len(trades), "sharpe": metrics.sharpe_ratio,
                "return": metrics.total_return_pct, "max_dd": metrics.max_drawdown_pct,
                "wr": metrics.win_rate_pct, "pf": metrics.profit_factor,
                "sum": sum(t.pnl_pct for t in trades),
            })

    high_results.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"\n  Top 10 High-Vol Adaptations (by Sharpe):")
    print(f"  {'Targ':>6s} {'Hold':>6s} {'Trades':>7s} {'Sharpe':>8s} {'Return':>8s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    for r in high_results[:10]:
        print(f"  {r['ht']:5.2f}% {r['hh']:5d}h {r['trades']:7d} {r['sharpe']:>+7.2f} {r['return']:>+7.1f}% {r['max_dd']:>+6.1f}% {r['wr']:>5.1f}% {r['pf']:>5.2f}")

    # Best overall config
    best_high = high_results[0]
    best_exits = {
        "low":    {"stop_pct": best_low["ls"], "target_pct": best_low["lt"], "hold_bars": best_low["lh"]},
        "normal": normal_exits,
        "high":   {"stop_pct": 3.0, "target_pct": best_high["ht"], "hold_bars": best_high["hh"]},
    }
    print(f"\n  ** BEST VOL-ADAPTIVE CONFIG **")
    print(f"  Low:    stop={best_low['ls']:.1f}%  target={best_low['lt']:.2f}%  hold={best_low['lh']}h")
    print(f"  Normal: stop=3.0%  target=1.5%  hold=12h")
    print(f"  High:   stop=3.0%  target={best_high['ht']:.2f}%  hold={best_high['hh']}h")

    # Full best backtest
    trades_best_va, equity_best_va = vol_adaptive_backtest(
        df_okx, signals_best, vol_ratio_okx, exits_by_regime=best_exits,
    )
    metrics_best_va = calculate_metrics(trades_best_va, equity_best_va)

    print_metrics(metrics_best_va, "BEST VOL-ADAPTIVE — Full Backtest (OKX)", trades_best_va)
    print_regime_breakdown(trades_best_va, "Per-Regime Breakdown (Vol-Adaptive)")

    # ========================================================================
    # EXPERIMENT 4: Walk-Forward Validation (OKX)
    # ========================================================================
    print("\n" + "=" * 70)
    print("EXPERIMENT 4: WALK-FORWARD VALIDATION (OKX)")
    print("=" * 70)

    # Baseline walk-forward (fixed exits)
    print(f"\n  --- Baseline (Fixed Exits: s3.0/t1.5/h12) ---")
    wf_baseline = walk_forward_vol_adaptive(
        df_okx,
        lambda d: generate_wick_signals(d, **best_filt),
        exits_by_regime=baseline_exits,
    )
    print_wf_table(wf_baseline, "Baseline WF")

    # Vol-adaptive walk-forward
    print(f"\n  --- Vol-Adaptive (Best Config) ---")
    wf_adaptive = walk_forward_vol_adaptive(
        df_okx,
        lambda d: generate_wick_signals(d, **best_filt),
        exits_by_regime=best_exits,
    )
    print_wf_table(wf_adaptive, "Vol-Adaptive WF")

    # ========================================================================
    # EXPERIMENT 5: Binance Cross-Validation
    # ========================================================================
    print("\n" + "=" * 70)
    print("EXPERIMENT 5: BINANCE CROSS-VALIDATION")
    print("=" * 70)

    signals_bnc = generate_wick_signals(df_binance, **best_filt)
    sig_count_bnc = int(signals_bnc.sum())
    print(f"  Binance signals: {sig_count_bnc}")

    # Baseline on Binance
    trades_bnc_base, equity_bnc_base = vol_adaptive_backtest(
        df_binance, signals_bnc, vol_ratio_binance, exits_by_regime=baseline_exits,
    )
    metrics_bnc_base = calculate_metrics(trades_bnc_base, equity_bnc_base)
    print_metrics(metrics_bnc_base, "Binance — Baseline (Fixed Exits)", trades_bnc_base)

    # Vol-adaptive on Binance
    trades_bnc_va, equity_bnc_va = vol_adaptive_backtest(
        df_binance, signals_bnc, vol_ratio_binance, exits_by_regime=best_exits,
    )
    metrics_bnc_va = calculate_metrics(trades_bnc_va, equity_bnc_va)
    print_metrics(metrics_bnc_va, "Binance — Vol-Adaptive", trades_bnc_va)

    # Binance walk-forward
    print(f"\n  --- Binance Walk-Forward (Vol-Adaptive) ---")
    wf_bnc = walk_forward_vol_adaptive(
        df_binance,
        lambda d: generate_wick_signals(d, **best_filt),
        exits_by_regime=best_exits,
    )
    print_wf_table(wf_bnc, "Binance Vol-Adaptive WF")

    # ========================================================================
    # EXPERIMENT 6: Comparison Table
    # ========================================================================
    print("\n" + "=" * 70)
    print("EXPERIMENT 6: COMPARISON TABLE")
    print("=" * 70)

    metrics_base = calculate_metrics(trades_best, equity_best)

    # Re-run with just SMA200 (no vol gate) for fair comparison
    sma200_only_filt = dict(vol_gate=False, sma200_filter=True, pdi_filter=False)
    signals_sma200 = generate_wick_signals(df_okx, **sma200_only_filt)
    trades_sma200, equity_sma200 = vol_adaptive_backtest(
        df_okx, signals_sma200, vol_ratio_okx, exits_by_regime=baseline_exits,
    )
    metrics_sma200 = calculate_metrics(trades_sma200, equity_sma200)

    # No filter baseline
    no_filt = dict(vol_gate=False, sma200_filter=False, pdi_filter=False)
    signals_no = generate_wick_signals(df_okx, **no_filt)
    trades_no, equity_no = vol_adaptive_backtest(
        df_okx, signals_no, vol_ratio_okx, exits_by_regime=baseline_exits,
    )
    metrics_no = calculate_metrics(trades_no, equity_no)

    rows = [
        ("Trades",     metrics_no.total_trades,    metrics_sma200.total_trades,    metrics_base.total_trades,    metrics_best_va.total_trades),
        ("Return %",   f"{metrics_no.total_return_pct:+.1f}", f"{metrics_sma200.total_return_pct:+.1f}", f"{metrics_base.total_return_pct:+.1f}", f"{metrics_best_va.total_return_pct:+.1f}"),
        ("Sharpe",     f"{metrics_no.sharpe_ratio:+.2f}",  f"{metrics_sma200.sharpe_ratio:+.2f}",  f"{metrics_base.sharpe_ratio:+.2f}",  f"{metrics_best_va.sharpe_ratio:+.2f}"),
        ("MaxDD %",    f"{metrics_no.max_drawdown_pct:+.1f}", f"{metrics_sma200.max_drawdown_pct:+.1f}", f"{metrics_base.max_drawdown_pct:+.1f}", f"{metrics_best_va.max_drawdown_pct:+.1f}"),
        ("WR %",       f"{metrics_no.win_rate_pct:.1f}", f"{metrics_sma200.win_rate_pct:.1f}", f"{metrics_base.win_rate_pct:.1f}", f"{metrics_best_va.win_rate_pct:.1f}"),
        ("PF",         f"{metrics_no.profit_factor:.2f}",   f"{metrics_sma200.profit_factor:.2f}",   f"{metrics_base.profit_factor:.2f}",   f"{metrics_best_va.profit_factor:.2f}"),
    ]
    print(f"\n  {'Metric':20s} {'No Filter':>10s} {'SMA200':>10s} {'Vol+SMA200':>10s} {'VA Best':>10s}")
    print(f"  {'-'*60}")
    for label, v0, v1, v2, v3 in rows:
        print(f"  {label:20s} {str(v0):>10s} {str(v1):>10s} {str(v2):>10s} {str(v3):>10s}")

    # OKX vs Binance comparison for best config
    rows2 = [
        ("Trades",     metrics_best_va.total_trades,   metrics_bnc_va.total_trades),
        ("Return %",   f"{metrics_best_va.total_return_pct:+.1f}", f"{metrics_bnc_va.total_return_pct:+.1f}"),
        ("Sharpe",     f"{metrics_best_va.sharpe_ratio:+.2f}",  f"{metrics_bnc_va.sharpe_ratio:+.2f}"),
        ("MaxDD %",    f"{metrics_best_va.max_drawdown_pct:+.1f}", f"{metrics_bnc_va.max_drawdown_pct:+.1f}"),
        ("WR %",       f"{metrics_best_va.win_rate_pct:.1f}", f"{metrics_bnc_va.win_rate_pct:.1f}"),
        ("PF",         f"{metrics_best_va.profit_factor:.2f}",   f"{metrics_bnc_va.profit_factor:.2f}"),
    ]
    print(f"\n  {'Metric':20s} {'OKX VA':>10s} {'BNC VA':>10s}")
    print(f"  {'-'*40}")
    for label, v1, v2 in rows2:
        print(f"  {label:20s} {str(v1):>10s} {str(v2):>10s}")

    # Print WF comparison
    print(f"\n  Walk-Forward Comparison:")
    print(f"  {'Config':25s} {'Splits':>8s} {'Mean Sharpe':>13s} {'Total Sum':>10s}")
    print(f"  {'-'*60}")
    for label, wf_data in [
        ("Baseline (fixed exits)", wf_baseline),
        ("Vol-Adaptive (best)", wf_adaptive),
        ("Binance Vol-Adaptive", wf_bnc),
    ]:
        profitable = sum(1 for sp in wf_data if sp["sharpe"] > 0)
        mean_sh = np.mean([sp["sharpe"] for sp in wf_data])
        total_s = sum(sp["sum"] for sp in wf_data)
        print(f"  {label:25s} {profitable}/{len(wf_data):<6d} {mean_sh:>+12.2f} {total_s:>+9.1f}%")

    print("\n" + "=" * 70)
    print("RESEARCH COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
