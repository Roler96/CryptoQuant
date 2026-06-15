"""
Spring Reversal — Volatility-Adaptive Exits Research
=====================================================

Tests whether adapting exits (stop/target/hold) to the volatility regime
at entry improves the Spring Reversal filtered strategy (SMA200 + BB %B).

Hypothesis: The Spring strategy encounters very different volatility
regimes at entry. Fixed exits are suboptimal across all regimes.
- High vol: wider stop (avoid premature stop-outs), wider target (capture
  bigger bounces), longer hold (bounces take longer to develop)
- Low vol: tighter stop (false breakdowns fail fast), shorter hold

Also tests: relaxed BB %B filter [0.15, 0.70] to increase trade count.

Author: CryptoQuant Autonomous Researcher
Date: 2026-06-15
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
from dataclasses import dataclass
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.types import Trade, BacktestResult, PerformanceMetrics
from cryptoquant.strategy.signals import (
    spring_reversal_signal, sma, bollinger_bands, atr,
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
    atr_val = atr(df, atr_period)
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
    """Run backtest with vol-adaptive exits per trade.

    For each signal, determines vol_regime at entry bar and uses
    regime-specific stop/target/hold parameters.

    Args:
        df: OHLCV DataFrame
        signals: int Series, 1=long entry signal (entry at next bar open)
        vol_ratio: ATR ratio at each bar
        vol_thresholds: (low, high) thresholds for regime classification
        exits_by_regime: dict of {regime: {stop_pct, target_pct, hold_bars}}
                         If None, uses defaults.
    """
    if exits_by_regime is None:
        exits_by_regime = {
            "low":    {"stop_pct": 3.0, "target_pct": 2.5, "hold_bars": 24},
            "normal": {"stop_pct": 3.0, "target_pct": 2.5, "hold_bars": 24},
            "high":   {"stop_pct": 3.0, "target_pct": 2.5, "hold_bars": 24},
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

    for i in range(200, n):  # skip warmup
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
            elif signals.iloc[i] == -1:  # opposite signal
                exit_reason = "signal_reverse"
                exit_price = bar_open * (1 - slippage)
            elif i == n - 1:
                exit_reason = "end_of_data"
                exit_price = bar_close

            if exit_reason is not None:
                # Calculate PnL
                gross_pnl_pct = (exit_price / position.entry_price - 1) * 100
                pnl_pct = gross_pnl_pct - commission * 100  # commission as % of notional

                # Track MFE/MAE as percentages
                mfe_pct = (position.high_since_entry / position.entry_price - 1) * 100
                mae_pct = (position.low_since_entry / position.entry_price - 1) * 100

                # Update equity (compound)
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

        # Check entry: signal at bar i-1 fires, enter at bar i open
        # (Standard convention: entry at next bar open after signal)
        if position is None and i > 0 and signals.iloc[i - 1] == 1:
            # Determine vol regime at entry bar (i-1, where the signal fired)
            vr = vol_ratio.iloc[i - 1]
            regime = classify_vol_regime(vr, low_thresh, high_thresh)
            exits = exits_by_regime[regime]

            entry_price = opens[i]  # enter at current bar's open
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

    # Sharpe (per-trade)
    if len(pnls) > 1:
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if np.std(pnls) > 0 else 0
        downside = pnls[pnls < 0]
        sortino = np.mean(pnls) / np.std(downside) * np.sqrt(len(pnls)) if len(downside) > 0 and np.std(downside) > 0 else 0
    else:
        sharpe = 0
        sortino = 0

    # Max drawdown
    peak = equity_curve.expanding().max()
    dd = (equity_curve - peak) / peak * 100
    max_dd = dd.min()
    max_dd_days = 0

    # Win rate
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
        max_drawdown_days=max_dd_days,
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

        # Generate signals
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
    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"{'='*55}")
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
        # Exit breakdown
        reasons = Counter(t.exit_reason for t in trades)
        print(f"\n  Exit Breakdown:")
        for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse", "end_of_data"]:
            subset = [t.pnl_pct for t in trades if t.exit_reason == reason]
            if subset:
                print(f"    {reason:15s}: {len(subset):4d} ({len(subset)/len(trades)*100:5.1f}%)  avg={np.mean(subset):+.2f}%  total={sum(subset):+.1f}%")

        # MFE
        mfes = [t.mfe_pct for t in trades]
        print(f"\n  MFE: mean={np.mean(mfes):+.2f}%  median={np.median(mfes):+.2f}%  max={np.max(mfes):+.2f}%")

        # Consecutive losses
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

        # Time-exits profitability
        time_exits = [t for t in trades if t.exit_reason == "time_exit"]
        if time_exits:
            green_te = sum(1 for t in time_exits if t.mfe_pct > 0)
            print(f"  Time-exits profitable at some point: {green_te}/{len(time_exits)} ({green_te/max(len(time_exits),1)*100:.1f}%)")

    return metrics


def print_regime_breakdown(trades, label=""):
    """Print per-regime trade breakdown."""
    print(f"\n  {'─'*50}")
    print(f"  {label}")
    print(f"  {'Regime':10s} {'Trades':>7s} {'Sum':>9s} {'WR':>7s} {'Stop%':>7s} {'AvgPnL':>8s} {'AvgMFE':>8s}")
    print(f"  {'-'*55}")
    for regime in ["low", "normal", "high"]:
        subset = [t for t in trades if t.regime.get("vol_regime") == regime]
        if subset:
            pnls = [t.pnl_pct for t in subset]
            wins = [p for p in pnls if p > 0]
            stops = [t for t in subset if t.exit_reason == "stop_loss"]
            mfes = [t.mfe_pct for t in subset]
            print(f"  {regime:10s} {len(subset):7d} {sum(pnls):>+8.1f}% {len(wins)/max(len(subset),1)*100:>6.1f}% {len(stops)/max(len(subset),1)*100:>6.1f}% {np.mean(pnls):>+7.3f}% {np.mean(mfes):>+7.2f}%")


# ============================================================================
# Signal generation (mirrors SpringReversal strategy)
# ============================================================================

def generate_spring_signals(
    df: pd.DataFrame,
    lookback: int = 20,
    vol_mult: float = 1.5,
    close_pct: float = 0.5,
    sma200_filter: bool = True,
    bb_filter: bool = True,
    bb_period: int = 20,
    bb_std: float = 2.0,
    bb_low: float = 0.2,
    bb_high: float = 0.6,
) -> pd.Series:
    """Generate Spring Reversal signals with optional regime filters."""
    # Core Spring signal
    signal = spring_reversal_signal(
        df, lookback=lookback, vol_mult=vol_mult, close_pct=close_pct
    )

    # SMA200 trend filter
    if sma200_filter:
        sma200 = sma(df["close"], 200)
        signal = signal & (df["close"] > sma200)

    # BB %B zone filter
    if bb_filter:
        bb = bollinger_bands(df, period=bb_period, std=bb_std)
        pct_b = bb["pct_b"]
        signal = signal & ((pct_b >= bb_low) & (pct_b < bb_high))

    return signal.astype(int)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("SPRING REVERSAL — VOLATILITY-ADAPTIVE EXITS RESEARCH")
    print("=" * 70)

    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    print(f"\nOKX BTC/USDT 1h: {len(df_okx)} bars, {df_okx.index[0]} to {df_okx.index[-1]}")
    print(f"Binance BTC/USDT 1h: {len(df_binance)} bars")

    # ========================================================================
    # EXPERIMENT 1: Baseline — Fixed exits with std BB filter
    # ========================================================================
    print("\n" + "=" * 70)
    print("EXPERIMENT 1: BASELINE — Fixed Exits (s3.0/t2.5/h24, BB 0.2-0.6)")
    print("=" * 70)

    # Baseline exits (same for all regimes = fixed)
    baseline_exits = {
        "low":    {"stop_pct": 3.0, "target_pct": 2.5, "hold_bars": 24},
        "normal": {"stop_pct": 3.0, "target_pct": 2.5, "hold_bars": 24},
        "high":   {"stop_pct": 3.0, "target_pct": 2.5, "hold_bars": 24},
    }

    signals_base = generate_spring_signals(df_okx, sma200_filter=True, bb_filter=True,
                                            bb_low=0.2, bb_high=0.6)
    vol_ratio_okx = compute_vol_ratio(df_okx)
    trades_base, equity_base = vol_adaptive_backtest(
        df_okx, signals_base, vol_ratio_okx,
        exits_by_regime=baseline_exits,
    )
    metrics_base = calculate_metrics(trades_base, equity_base)
    print_metrics(metrics_base, "BASELINE — Fixed Exits, BB 0.2-0.6", trades_base)

    # Per-regime breakdown
    print_regime_breakdown(trades_base, "BASELINE — Per-Regime Breakdown")

    # Walk-forward
    print(f"\n  Walk-Forward (7 splits):")
    wf_base = walk_forward_vol_adaptive(
        df_okx, lambda d: generate_spring_signals(d, sma200_filter=True, bb_filter=True,
                                                    bb_low=0.2, bb_high=0.6),
        n_splits=7,
        exits_by_regime=baseline_exits,
    )
    wf_base_pos = sum(1 for s in wf_base if s["return"] > 0)
    wf_base_sharpes = [s["sharpe"] for s in wf_base]
    for i, s in enumerate(wf_base):
        status = "✅" if s["return"] > 0 else "❌"
        print(f"    Split {i+1}: {s['start'].strftime('%Y-%m')}→{s['end'].strftime('%Y-%m')}  trades={s['trades']:3d}  return={s['return']:+.1f}%  sharpe={s['sharpe']:+.2f}  sum={s['sum']:+.1f}%  {status}")
    print(f"    OOS Profitable: {wf_base_pos}/{len(wf_base)} | Mean OOS Sharpe: {np.mean(wf_base_sharpes):+.2f} | Total OOS Sum: {sum(s['sum'] for s in wf_base):+.1f}%")

    # ========================================================================
    # EXPERIMENT 2: Expanded BB filter to increase trade count
    # ========================================================================
    print("\n" + "=" * 70)
    print("EXPERIMENT 2: EXPANDED BB FILTER — BB 0.15-0.70 (Increased Trade Count)")
    print("=" * 70)

    # Test several expanded ranges
    expanded_ranges = [
        ("BB 0.15-0.65", 0.15, 0.65),
        ("BB 0.15-0.70", 0.15, 0.70),
        ("BB 0.12-0.70", 0.12, 0.70),
        ("BB 0.10-0.75", 0.10, 0.75),
    ]

    best_expanded = None
    best_expanded_metrics = None
    best_expanded_sharpe = -999
    best_expanded_trades = None
    best_expanded_equity = None

    for label, bb_low, bb_high in expanded_ranges:
        signals_exp = generate_spring_signals(df_okx, sma200_filter=True, bb_filter=True,
                                                bb_low=bb_low, bb_high=bb_high)
        trades_exp, equity_exp = vol_adaptive_backtest(
            df_okx, signals_exp, vol_ratio_okx,
            exits_by_regime=baseline_exits,
        )
        met_exp = calculate_metrics(trades_exp, equity_exp)
        print(f"\n  {label}: Trades={met_exp.total_trades}, Return={met_exp.total_return_pct:+.1f}%, Sharpe={met_exp.sharpe_ratio:+.2f}, MaxDD={met_exp.max_drawdown_pct:+.1f}%, WR={met_exp.win_rate_pct:.1f}%, PF={met_exp.profit_factor:.2f}")

        if met_exp.sharpe_ratio > best_expanded_sharpe:
            best_expanded_sharpe = met_exp.sharpe_ratio
            best_expanded = (label, bb_low, bb_high)
            best_expanded_metrics = met_exp
            best_expanded_trades = trades_exp
            best_expanded_equity = equity_exp

    # Full print for best expanded
    print(f"\n{'─'*55}")
    print(f"  BEST EXPANDED: {best_expanded[0]}")
    print_metrics(best_expanded_metrics, f"EXPANDED — {best_expanded[0]}", best_expanded_trades)
    print_regime_breakdown(best_expanded_trades, f"EXPANDED — Per-Regime Breakdown")

    # ========================================================================
    # EXPERIMENT 3: Vol-Adaptive Exits on Expanded BB filter
    # ========================================================================
    print("\n" + "=" * 70)
    print("EXPERIMENT 3: VOL-ADAPTIVE EXITS — Grid Search")
    print("=" * 70)

    # Use the best expanded BB range
    best_bb_low, best_bb_high = best_expanded[1], best_expanded[2]
    print(f"  Using BB filter: [{best_bb_low}, {best_bb_high})")

    signals_for_opt = generate_spring_signals(df_okx, sma200_filter=True, bb_filter=True,
                                                bb_low=best_bb_low, bb_high=best_bb_high)
    signal_count = signals_for_opt.sum()
    print(f"  Total signals: {signal_count}")

    # Grid search for vol-adaptive exits
    # Normal regime keeps baseline. Only vary low/high.
    vol_adaptive_grid = []

    for low_stop in [2.5, 3.0, 3.5]:
        for low_hold in [16, 20, 24]:
            for high_stop in [3.0, 3.5, 4.0]:
                for high_target in [2.5, 3.0, 3.5, 4.0]:
                    for high_hold in [24, 28, 32]:
                        exits = {
                            "low":    {"stop_pct": low_stop, "target_pct": 2.5, "hold_bars": low_hold},
                            "normal": {"stop_pct": 3.0, "target_pct": 2.5, "hold_bars": 24},
                            "high":   {"stop_pct": high_stop, "target_pct": high_target, "hold_bars": high_hold},
                        }
                        trades_va, equity_va = vol_adaptive_backtest(
                            df_okx, signals_for_opt, vol_ratio_okx,
                            exits_by_regime=exits,
                        )
                        met_va = calculate_metrics(trades_va, equity_va)

                        vol_adaptive_grid.append({
                            "low_stop": low_stop, "low_hold": low_hold,
                            "high_stop": high_stop, "high_target": high_target, "high_hold": high_hold,
                            "trades": met_va.total_trades,
                            "return": met_va.total_return_pct,
                            "sharpe": met_va.sharpe_ratio,
                            "max_dd": met_va.max_drawdown_pct,
                            "wr": met_va.win_rate_pct,
                            "pf": met_va.profit_factor,
                            "exits": exits,
                            "trades_list": trades_va,
                            "equity": equity_va,
                        })

    # Sort by Sharpe
    vol_adaptive_grid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n  Top 10 Vol-Adaptive Configs:")
    print(f"  {'LowStp':>7s} {'LowHld':>7s} {'HiStp':>6s} {'HiTgt':>6s} {'HiHld':>6s} {'Trades':>7s} {'Return':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>5s}")
    print(f"  {'-'*75}")
    for cfg in vol_adaptive_grid[:10]:
        print(f"  {cfg['low_stop']:>6.1f}% {cfg['low_hold']:>6d}h {cfg['high_stop']:>5.1f}% {cfg['high_target']:>5.1f}% {cfg['high_hold']:>5d}h {cfg['trades']:>7d} {cfg['return']:>+7.1f}% {cfg['sharpe']:>+6.2f} {cfg['max_dd']:>+6.1f}% {cfg['wr']:>5.1f}% {cfg['pf']:>5.2f}")

    # Best config
    best_va = vol_adaptive_grid[0]
    print(f"\n{'─'*55}")
    print(f"  BEST VOL-ADAPTIVE CONFIG")
    print(f"  Low:  s={best_va['low_stop']:.1f}% t=2.5% h={best_va['low_hold']}h")
    print(f"  Normal: s=3.0% t=2.5% h=24h")
    print(f"  High: s={best_va['high_stop']:.1f}% t={best_va['high_target']:.1f}% h={best_va['high_hold']}h")
    print_metrics(calculate_metrics(best_va["trades_list"], best_va["equity"]),
                  "BEST VOL-ADAPTIVE", best_va["trades_list"])
    print_regime_breakdown(best_va["trades_list"], "VOL-ADAPTIVE — Per-Regime Breakdown")

    # ========================================================================
    # COMPARISON TABLE
    # ========================================================================
    print(f"\n{'='*70}")
    print("COMPARISON: BASELINE vs EXPANDED vs VOL-ADAPTIVE")
    print(f"{'='*70}")

    print(f"\n  {'Metric':20s} {'Baseline':>12s} {'Expanded':>12s} {'Vol-Adaptive':>14s}")
    print(f"  {'-'*62}")
    for metric_name, base_val, exp_val, va_val in [
        ("Trades", metrics_base.total_trades, best_expanded_metrics.total_trades, best_va["trades"]),
        ("Return", metrics_base.total_return_pct, best_expanded_metrics.total_return_pct, best_va["return"]),
        ("Sharpe", metrics_base.sharpe_ratio, best_expanded_metrics.sharpe_ratio, best_va["sharpe"]),
        ("Max Drawdown", metrics_base.max_drawdown_pct, best_expanded_metrics.max_drawdown_pct, best_va["max_dd"]),
        ("Win Rate", metrics_base.win_rate_pct, best_expanded_metrics.win_rate_pct, best_va["wr"]),
        ("Profit Factor", metrics_base.profit_factor, best_expanded_metrics.profit_factor, best_va["pf"]),
        ("Avg Win", metrics_base.avg_win_pct, best_expanded_metrics.avg_win_pct,
         np.mean([t.pnl_pct for t in best_va["trades_list"] if t.pnl_pct > 0]) if any(t.pnl_pct > 0 for t in best_va["trades_list"]) else 0),
        ("Avg Loss", metrics_base.avg_loss_pct, best_expanded_metrics.avg_loss_pct,
         np.mean([t.pnl_pct for t in best_va["trades_list"] if t.pnl_pct <= 0]) if any(t.pnl_pct <= 0 for t in best_va["trades_list"]) else 0),
    ]:
        if metric_name == "Trades":
            print(f"  {metric_name:20s} {base_val:>12.0f} {exp_val:>12.0f} {va_val:>14.0f}")
        elif metric_name in ("Win Rate",):
            print(f"  {metric_name:20s} {base_val:>11.1f}% {exp_val:>11.1f}% {va_val:>13.1f}%")
        else:
            print(f"  {metric_name:20s} {base_val:>+11.2f} {exp_val:>+11.2f} {va_val:>+13.2f}")

    # Exit breakdown comparison
    print(f"\n  Exit Breakdown Comparison:")
    print(f"  {'Exit Type':15s} {'Baseline':>20s} {'Expanded':>20s} {'Vol-Adaptive':>20s}")
    print(f"  {'-'*77}")
    for reason in ["take_profit", "stop_loss", "time_exit", "end_of_data"]:
        base_sub = [t for t in trades_base if t.exit_reason == reason]
        exp_sub = [t for t in best_expanded_trades if t.exit_reason == reason]
        va_sub = [t for t in best_va["trades_list"] if t.exit_reason == reason]

        def fmt(subset, total):
            if not subset:
                return f"{'—':>20s}"
            pct = len(subset) / max(total, 1) * 100
            avg = np.mean([t.pnl_pct for t in subset])
            return f"{len(subset):3d} ({pct:4.1f}%) avg={avg:+.2f}%"

        print(f"  {reason:15s} {fmt(base_sub, len(trades_base)):>20s} {fmt(exp_sub, len(best_expanded_trades)):>20s} {fmt(va_sub, len(best_va['trades_list'])):>20s}")

    # ========================================================================
    # WALK-FORWARD: Best Vol-Adaptive
    # ========================================================================
    print(f"\n{'='*70}")
    print("WALK-FORWARD: BEST VOL-ADAPTIVE CONFIG")
    print(f"{'='*70}")

    wf_va = walk_forward_vol_adaptive(
        df_okx,
        lambda d: generate_spring_signals(d, sma200_filter=True, bb_filter=True,
                                            bb_low=best_bb_low, bb_high=best_bb_high),
        n_splits=7,
        vol_thresholds=(0.7, 1.5),
        exits_by_regime=best_va["exits"],
    )
    wf_va_pos = sum(1 for s in wf_va if s["return"] > 0)
    wf_va_sharpes = [s["sharpe"] for s in wf_va]
    for i, s in enumerate(wf_va):
        status = "✅" if s["return"] > 0 else "❌"
        print(f"  Split {i+1}: {s['start'].strftime('%Y-%m')}→{s['end'].strftime('%Y-%m')}  trades={s['trades']:3d}  return={s['return']:+.1f}%  sharpe={s['sharpe']:+.2f}  sum={s['sum']:+.1f}%  {status}")
    print(f"  OOS Profitable: {wf_va_pos}/{len(wf_va)} | Mean OOS Sharpe: {np.mean(wf_va_sharpes):+.2f} | Total OOS Sum: {sum(s['sum'] for s in wf_va):+.1f}%")

    # ========================================================================
    # BINANCE CROSS-VALIDATION
    # ========================================================================
    print(f"\n{'='*70}")
    print("BINANCE CROSS-VALIDATION")
    print(f"{'='*70}")

    signals_bnc = generate_spring_signals(df_binance, sma200_filter=True, bb_filter=True,
                                            bb_low=best_bb_low, bb_high=best_bb_high)
    vol_ratio_bnc = compute_vol_ratio(df_binance)

    # Baseline on Binance
    trades_bnc_base, equity_bnc_base = vol_adaptive_backtest(
        df_binance, signals_bnc, vol_ratio_bnc,
        exits_by_regime=baseline_exits,
    )
    met_bnc_base = calculate_metrics(trades_bnc_base, equity_bnc_base)
    print_metrics(met_bnc_base, "BINANCE — Baseline (Fixed Exits)", trades_bnc_base)

    # Vol-adaptive on Binance
    trades_bnc_va, equity_bnc_va = vol_adaptive_backtest(
        df_binance, signals_bnc, vol_ratio_bnc,
        exits_by_regime=best_va["exits"],
    )
    met_bnc_va = calculate_metrics(trades_bnc_va, equity_bnc_va)
    print_metrics(met_bnc_va, "BINANCE — Vol-Adaptive Exits", trades_bnc_va)

    # Walk-forward Binance
    print(f"\n  Binance Walk-Forward (Vol-Adaptive, 7 splits):")
    wf_bnc_va = walk_forward_vol_adaptive(
        df_binance,
        lambda d: generate_spring_signals(d, sma200_filter=True, bb_filter=True,
                                            bb_low=best_bb_low, bb_high=best_bb_high),
        n_splits=7,
        exits_by_regime=best_va["exits"],
    )
    wf_bnc_pos = sum(1 for s in wf_bnc_va if s["return"] > 0)
    wf_bnc_sharpes = [s["sharpe"] for s in wf_bnc_va]
    for i, s in enumerate(wf_bnc_va):
        status = "✅" if s["return"] > 0 else "❌"
        print(f"    Split {i+1}: {s['start'].strftime('%Y-%m')}→{s['end'].strftime('%Y-%m')}  trades={s['trades']:3d}  return={s['return']:+.1f}%  sharpe={s['sharpe']:+.2f}  sum={s['sum']:+.1f}%  {status}")
    print(f"    OOS Profitable: {wf_bnc_pos}/{len(wf_bnc_va)} | Mean OOS Sharpe: {np.mean(wf_bnc_sharpes):+.2f} | Total OOS Sum: {sum(s['sum'] for s in wf_bnc_va):+.1f}%")

    # Cross-exchange comparison
    print(f"\n  Cross-Exchange Comparison (Vol-Adaptive):")
    print(f"  {'Metric':20s} {'OKX Baseline':>14s} {'OKX VA':>14s} {'BNC Baseline':>14s} {'BNC VA':>14s}")
    print(f"  {'-'*64}")
    for metric_name, okx_base_val, okx_va_val, bnc_base_val, bnc_va_val in [
        ("Trades", metrics_base.total_trades, best_va["trades"],
         met_bnc_base.total_trades, met_bnc_va.total_trades),
        ("Return", metrics_base.total_return_pct, best_va["return"],
         met_bnc_base.total_return_pct, met_bnc_va.total_return_pct),
        ("Sharpe", metrics_base.sharpe_ratio, best_va["sharpe"],
         met_bnc_base.sharpe_ratio, met_bnc_va.sharpe_ratio),
        ("Max DD", metrics_base.max_drawdown_pct, best_va["max_dd"],
         met_bnc_base.max_drawdown_pct, met_bnc_va.max_drawdown_pct),
        ("Win Rate", metrics_base.win_rate_pct, best_va["wr"],
         met_bnc_base.win_rate_pct, met_bnc_va.win_rate_pct),
        ("PF", metrics_base.profit_factor, best_va["pf"],
         met_bnc_base.profit_factor, met_bnc_va.profit_factor),
    ]:
        if metric_name == "Trades":
            print(f"  {metric_name:20s} {okx_base_val:>14.0f} {okx_va_val:>14.0f} {bnc_base_val:>14.0f} {bnc_va_val:>14.0f}")
        elif metric_name == "Win Rate":
            print(f"  {metric_name:20s} {okx_base_val:>13.1f}% {okx_va_val:>13.1f}% {bnc_base_val:>13.1f}% {bnc_va_val:>13.1f}%")
        else:
            print(f"  {metric_name:20s} {okx_base_val:>+13.2f} {okx_va_val:>+13.2f} {bnc_base_val:>+13.2f} {bnc_va_val:>+13.2f}")

    print("\n" + "=" * 70)
    print("RESEARCH COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
