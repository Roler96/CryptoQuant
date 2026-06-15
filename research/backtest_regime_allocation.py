"""
BB Breakout + Spring Reversal — Regime-Based Capital Allocation
===============================================================

The combined BB+Spring strategy (Sharpe 1.36, 6/7 WF) uses equal 50/50 weights.
But regime analysis shows:
- BB Breakout works 5× better when ADX > 25 (trending)
- Spring Reversal works best when ADX ≤ 20 (ranging)

Hypothesis: Dynamic capital allocation based on ADX regime will:
1. Improve risk-adjusted returns (Sharpe, Sortino)
2. Reduce drawdown by limiting BB exposure during choppy/ranging markets
3. Improve walk-forward robustness, particularly Split 7 (2024-2025)

Allocation schemes tested:
- Equal: 50/50 always (baseline)
- Binary: 100/0 — all to BB when ADX>25, all to Spring when ADX≤20
- 80/20: 80% to dominant strategy in each regime
- 60/40: 60% to dominant strategy in each regime
- ADX-scaled: weight = ADX/50 for BB, continuous
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.engine.types import Trade
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    sma, bollinger_bands, adx as adx_func,
)


# ============================================================================
# Strategy Classes
# ============================================================================

class BBUpperBreakoutNoSMA(Strategy):
    """BB Upper Breakout without SMA200 filter."""
    timeframe = "1h"
    min_bars = 250
    version = "2.0.0"
    DEFAULT_PARAMS = {"bb_period": 50, "bb_std": 2.5}

    @property
    def name(self) -> str:
        return "BB_Upper_Breakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        bb = bollinger_bands(df, period=50, std=2.5)
        signal = df["close"] > bb["upper"]
        return signal.astype(int)


class SpringFiltered(Strategy):
    """Spring Reversal with SMA200 + BB %B 0.2-0.6 filters."""
    timeframe = "1h"
    min_bars = 250
    version = "2.0.0"
    DEFAULT_PARAMS = {"lookback": 20, "vol_mult": 1.5, "close_pct": 0.5}

    @property
    def name(self) -> str:
        return "Spring_Filtered"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        # Spring pattern
        opens, highs, lows, closes, volumes = df["open"], df["high"], df["low"], df["close"], df["volume"]
        rolling_low = lows.rolling(20).min().shift(1)
        new_low = lows < rolling_low
        bullish_close = closes > opens
        bar_range = highs - lows
        close_position = (closes - lows) / bar_range.replace(0, np.nan)
        close_near_high = close_position > 0.5
        avg_vol = volumes.rolling(20).mean().shift(1)
        high_volume = volumes > (1.5 * avg_vol)
        base = new_low & bullish_close & close_near_high & high_volume

        # Filters
        sma200 = sma(closes, 200)
        bb = bollinger_bands(df, 20, 2.0)
        bb_filter = (bb["pct_b"] >= 0.2) & (bb["pct_b"] < 0.6)
        sma_filter = closes > sma200
        filtered = base & bb_filter & sma_filter
        return filtered.astype(int)


# ============================================================================
# ADX Regime Classification
# ============================================================================

def classify_regime_adx(df: pd.DataFrame) -> pd.Series:
    """Classify each bar into trending/ranging/neutral based on ADX.
    
    Returns: Series with values: 'trending', 'neutral', 'ranging'
    """
    adx_series = adx_func(df, period=14)  # returns DataFrame with 'adx' column
    adx_vals = adx_series["adx"]

    def _classify(adx_val):
        if pd.isna(adx_val):
            return "neutral"
        if adx_val > 25:
            return "trending"
        elif adx_val <= 20:
            return "ranging"
        else:
            return "neutral"

    return adx_vals.apply(_classify)


# ============================================================================
# Regime-Based Combined Metrics
# ============================================================================

def compute_regime_combined_metrics(
    bb_trades: list[Trade],
    spring_trades: list[Trade],
    df: pd.DataFrame,
    allocation_scheme: str,
    initial_capital: float = 10_000.0,
):
    """Compute combined equity curve with regime-based capital allocation.
    
    allocation_scheme:
        - "equal": 50/50 always
        - "binary": 100% to BB when trending, 100% to Spring when ranging
        - "80_20": 80% dominant, 20% other
        - "60_40": 60% dominant, 40% other
        - "adx_scaled": BB weight = min(max(ADX/50, 0.1), 0.9)
    """
    # Classify regime for each bar
    regime = classify_regime_adx(df)

    # Get weights for each trade based on regime at entry bar
    def get_weight(trade: Trade, strategy_type: str, scheme: str) -> float:
        """Get capital allocation weight for a trade."""
        # Find the entry bar's regime
        entry_ts = pd.Timestamp(trade.entry_time, unit="ms")
        # Find closest bar index
        idx = df.index.get_indexer([entry_ts], method="ffill")[0]
        if idx < 0 or idx >= len(df):
            return 0.5  # fallback

        reg = regime.iloc[idx]

        if scheme == "equal":
            return 0.5

        elif scheme == "binary":
            if reg == "trending":
                return 1.0 if strategy_type == "bb" else 0.0
            elif reg == "ranging":
                return 0.0 if strategy_type == "bb" else 1.0
            else:  # neutral
                return 0.5

        elif scheme == "80_20":
            if reg == "trending":
                return 0.8 if strategy_type == "bb" else 0.2
            elif reg == "ranging":
                return 0.2 if strategy_type == "bb" else 0.8
            else:
                return 0.5

        elif scheme == "60_40":
            if reg == "trending":
                return 0.6 if strategy_type == "bb" else 0.4
            elif reg == "ranging":
                return 0.4 if strategy_type == "bb" else 0.6
            else:
                return 0.5

        elif scheme == "adx_scaled":
            adx_val = adx_func(df, period=14)["adx"].iloc[idx]
            if pd.isna(adx_val):
                return 0.5
            bb_weight = max(0.1, min(0.9, adx_val / 50.0))
            return bb_weight if strategy_type == "bb" else (1.0 - bb_weight)

        return 0.5  # fallback

    # Combine trades with weights
    # We don't create new Trade objects (dataclass has many required fields).
    # Instead, we create lightweight weighted-trade tuples.
    all_trades = []
    for t in bb_trades:
        w = get_weight(t, "bb", allocation_scheme)
        all_trades.append({
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "pnl_pct": t.pnl_pct * w,
            "exit_reason": t.exit_reason,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "mfe_pct": t.mfe_pct,
            "mae_pct": t.mae_pct,
        })

    for t in spring_trades:
        w = get_weight(t, "spring", allocation_scheme)
        all_trades.append({
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "pnl_pct": t.pnl_pct * w,
            "exit_reason": t.exit_reason,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "mfe_pct": t.mfe_pct,
            "mae_pct": t.mae_pct,
        })

    # Sort by exit time
    sorted_trades = sorted(all_trades, key=lambda t: t["exit_time"])

    # Compound equity curve
    exit_times = []
    factors = []
    for t in sorted_trades:
        exit_times.append(pd.Timestamp(t["exit_time"], unit="ms"))
        factors.append(1.0 + t["pnl_pct"] / 100.0)

    equity_jumps = pd.Series(factors, index=exit_times, dtype=float)
    equity_jumps.sort_index(inplace=True)
    cumulative = equity_jumps.cumprod()

    curve = pd.Series(initial_capital, index=df.index, dtype=float)
    for ts, factor in cumulative.items():
        mask = df.index >= ts
        if mask.any():
            curve[mask] = initial_capital * factor

    dd_curve = (curve / curve.cummax() - 1) * 100

    # Sharpe/Sortino
    daily_returns = curve.resample("1D").last().pct_change().dropna()
    if len(daily_returns) > 0 and daily_returns.std() > 0:
        sharpe = float(daily_returns.mean() / daily_returns.std() * np.sqrt(365))
    else:
        sharpe = 0.0

    downside = daily_returns[daily_returns < 0]
    if len(downside) > 0 and downside.std() > 0:
        sortino = float(daily_returns.mean() / downside.std() * np.sqrt(365))
    else:
        sortino = 0.0

    # Trade-level metrics — exclude zero-weight trades (no capital deployed)
    nonzero_trades = [t for t in sorted_trades if abs(t["pnl_pct"]) > 1e-10]
    pnl_pcts = [t["pnl_pct"] for t in nonzero_trades]
    wins = [t for t in nonzero_trades if t["pnl_pct"] > 0]
    losses = [t for t in nonzero_trades if t["pnl_pct"] < 0]
    win_rate = len(wins) / len(nonzero_trades) * 100 if nonzero_trades else 0
    avg_win = np.mean([t["pnl_pct"] for t in wins]) if wins else 0
    avg_loss = np.mean([t["pnl_pct"] for t in losses]) if losses else 0

    gross_profit = sum(t["pnl_pct"] for t in wins)
    gross_loss = abs(sum(t["pnl_pct"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    max_consec = 0
    consec = 0
    for t in nonzero_trades:
        if t["pnl_pct"] < 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    final_equity = curve.iloc[-1]
    compound_return = (final_equity / initial_capital - 1) * 100
    linear_sum = sum(pnl_pcts)

    total_days = (df.index[-1] - df.index[0]).total_seconds() / 86400
    total_years = total_days / 365.25
    annualized = (final_equity / initial_capital) ** (1 / max(total_years, 1)) - 1

    max_dd = dd_curve.min()

    exit_counts = Counter(t["exit_reason"] for t in nonzero_trades)
    exit_detail = {}
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        subset = [t for t in nonzero_trades if t["exit_reason"] == reason]
        count = len(subset)
        pct = count / len(nonzero_trades) * 100 if nonzero_trades else 0
        avg = np.mean([t["pnl_pct"] for t in subset]) if subset else 0
        total = sum(t["pnl_pct"] for t in subset)
        exit_detail[reason] = (count, pct, avg, total)

    # Regime breakdown
    regime_stats = {"trending": {"n": 0, "sum": 0.0}, "neutral": {"n": 0, "sum": 0.0}, "ranging": {"n": 0, "sum": 0.0}}
    for t in sorted_trades:
        entry_ts = pd.Timestamp(t["entry_time"], unit="ms")
        idx = df.index.get_indexer([entry_ts], method="ffill")[0]
        if 0 <= idx < len(df):
            reg = regime.iloc[idx]
            regime_stats[reg]["n"] += 1
            regime_stats[reg]["sum"] += t["pnl_pct"]

    return {
        "total_trades": len(nonzero_trades),
        "total_signals": len(sorted_trades),
        "compound_return": compound_return,
        "linear_sum": linear_sum,
        "annualized_return": annualized * 100,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "max_consec_losses": max_consec,
        "exit_detail": exit_detail,
        "final_equity": final_equity,
        "regime_stats": regime_stats,
    }, curve, dd_curve


# ============================================================================
# Walk-Forward with Regime Allocation
# ============================================================================

def walk_forward_regime(
    df: pd.DataFrame,
    bb_strategy: Strategy,
    spring_strategy: Strategy,
    bb_exit: dict,
    spring_exit: dict,
    allocation_schemes: list[str],
    n_splits: int = 7,
):
    """Walk-forward validation for all allocation schemes."""
    n = len(df)
    slot = n // (n_splits + 2)

    # Store results per scheme per split
    all_results = {scheme: [] for scheme in allocation_schemes}

    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        oos_df = df.iloc[start:end]

        # Run BB Backtest
        engine_bb = BacktestEngine(commission=0.0005, slippage=0.0005)
        result_bb = engine_bb.run(
            oos_df, bb_strategy, symbol="BTC/USDT",
            stop_loss_pct=bb_exit["stop_pct"],
            take_profit_pct=bb_exit["target_pct"],
            max_hold_bars=bb_exit["hold_hours"],
        )

        # Run Spring Backtest
        engine_sp = BacktestEngine(commission=0.0005, slippage=0.0005)
        result_sp = engine_sp.run(
            oos_df, spring_strategy, symbol="BTC/USDT",
            stop_loss_pct=spring_exit["stop_pct"],
            take_profit_pct=spring_exit["target_pct"],
            max_hold_bars=spring_exit["hold_hours"],
        )

        for scheme in allocation_schemes:
            metrics, _, _ = compute_regime_combined_metrics(
                result_bb.trades, result_sp.trades, oos_df,
                allocation_scheme=scheme,
            )
            all_results[scheme].append({
                "split": s + 1,
                "period": f"{oos_df.index[0].strftime('%Y-%m')}→{oos_df.index[-1].strftime('%Y-%m')}",
                "sum": metrics["linear_sum"],
                "sharpe": metrics["sharpe"],
                "trades": metrics["total_trades"],
            })

    return all_results


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("BB BREAKOUT + SPRING — REGIME-BASED CAPITAL ALLOCATION")
    print("=" * 70)

    # Load data
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")

    print(f"\nOKX: {len(df_okx):,} bars, {df_okx.index[0]} to {df_okx.index[-1]}")
    print(f"Binance: {len(df_binance):,} bars, {df_binance.index[0]} to {df_binance.index[-1]}")

    # ========================================================================
    # STRATEGY CONFIGURATIONS
    # ========================================================================
    bb_strategy = BBUpperBreakoutNoSMA()
    spring_strategy = SpringFiltered()

    bb_exit = {"stop_pct": 1.2, "target_pct": 4.0, "hold_hours": 10}
    spring_exit = {"stop_pct": 3.0, "target_pct": 3.0, "hold_hours": 16}

    # ========================================================================
    # INDIVIDUAL BACKTESTS
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  INDIVIDUAL BACKTESTS — OKX BTC/USDT 1h")
    print(f"{'='*70}")

    engine_bb = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_bb = engine_bb.run(
        df_okx, bb_strategy, symbol="BTC/USDT",
        stop_loss_pct=bb_exit["stop_pct"],
        take_profit_pct=bb_exit["target_pct"],
        max_hold_bars=bb_exit["hold_hours"],
    )
    print(f"\n  BB Breakout: {result_bb.metrics.total_trades} trades, "
          f"Sharpe {result_bb.metrics.sharpe_ratio:+.2f}, "
          f"Return {result_bb.metrics.total_return_pct:+.1f}%, "
          f"MaxDD {result_bb.metrics.max_drawdown_pct:.1f}%")

    engine_sp = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_sp = engine_sp.run(
        df_okx, spring_strategy, symbol="BTC/USDT",
        stop_loss_pct=spring_exit["stop_pct"],
        take_profit_pct=spring_exit["target_pct"],
        max_hold_bars=spring_exit["hold_hours"],
    )
    print(f"  Spring:     {result_sp.metrics.total_trades} trades, "
          f"Sharpe {result_sp.metrics.sharpe_ratio:+.2f}, "
          f"Return {result_sp.metrics.total_return_pct:+.1f}%, "
          f"MaxDD {result_sp.metrics.max_drawdown_pct:.1f}%")

    # ========================================================================
    # REGIME DISTRIBUTION
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  REGIME DISTRIBUTION")
    print(f"{'='*70}")

    regime = classify_regime_adx(df_okx)
    regime_counts = regime.value_counts()
    for reg in ["trending", "neutral", "ranging"]:
        count = regime_counts.get(reg, 0)
        pct = count / len(regime) * 100
        print(f"  {reg:12s}: {count:>6,d} bars ({pct:>5.1f}%)")

    # ========================================================================
    # ALLOCATION SCHEME COMPARISON — FULL BACKTEST
    # ========================================================================
    schemes = ["equal", "binary", "80_20", "60_40", "adx_scaled"]
    scheme_labels = {
        "equal": "Equal 50/50 (baseline)",
        "binary": "Binary 100/0 switch",
        "80_20": "80/20 regime-biased",
        "60_40": "60/40 regime-biased",
        "adx_scaled": "ADX-scaled continuous",
    }

    print(f"\n{'='*70}")
    print(f"  FULL BACKTEST — ALLOCATION SCHEME COMPARISON (OKX BTC/USDT 1h)")
    print(f"{'='*70}")

    scheme_metrics = {}
    for scheme in schemes:
        metrics, curve, dd = compute_regime_combined_metrics(
            result_bb.trades, result_sp.trades, df_okx,
            allocation_scheme=scheme,
        )
        scheme_metrics[scheme] = metrics

        print(f"\n  {scheme_labels[scheme]}:")
        print(f"    Compound Return:  {metrics['compound_return']:>+8.1f}%")
        print(f"    Linear Sum:       {metrics['linear_sum']:>+8.1f}%")
        print(f"    Annualized:       {metrics['annualized_return']:>+8.1f}%")
        print(f"    Sharpe Ratio:     {metrics['sharpe']:>+8.2f}")
        print(f"    Sortino Ratio:    {metrics['sortino']:>+8.2f}")
        print(f"    Max Drawdown:     {metrics['max_drawdown']:>8.1f}%")
        print(f"    Win Rate:         {metrics['win_rate']:>8.1f}%")
        print(f"    Avg Win:          {metrics['avg_win']:>+8.2f}%")
        print(f"    Avg Loss:         {metrics['avg_loss']:>+8.2f}%")
        print(f"    Profit Factor:    {metrics['profit_factor']:>8.2f}")
        print(f"    Max Consec Loss:  {metrics['max_consec_losses']:>8d}")

        # Regime breakdown
        rs = metrics["regime_stats"]
        print(f"    Regime Breakdown:")
        for reg in ["trending", "neutral", "ranging"]:
            n = rs[reg]["n"]
            s = rs[reg]["sum"]
            if n > 0:
                print(f"      {reg:12s}: {n:>4d} trades, sum={s:>+8.1f}%")
            else:
                print(f"      {reg:12s}: {n:>4d} trades")

    # ========================================================================
    # COMPARISON TABLE
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  COMPARISON TABLE")
    print(f"{'='*70}")

    header = f"  {'Metric':22s}"
    for scheme in schemes:
        header += f" {'equal':>9s}" if scheme == "equal" else ""
        header += f" {'binary':>9s}" if scheme == "binary" else ""
        header += f" {'80_20':>9s}" if scheme == "80_20" else ""
        header += f" {'60_40':>9s}" if scheme == "60_40" else ""
        header += f" {'adx_sc':>9s}" if scheme == "adx_scaled" else ""
    # Simpler approach: print row by row
    print(f"\n  {'Metric':22s}  {'equal':>8s}  {'binary':>8s}  {'80_20':>8s}  {'60_40':>8s}  {'adx_sc':>8s}")
    print(f"  {'-'*22}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}")

    metric_keys = [
        ("Sharpe", "sharpe", "+.2f"),
        ("Sortino", "sortino", "+.2f"),
        ("Compound Return %", "compound_return", "+.1f"),
        ("Linear Sum %", "linear_sum", "+.1f"),
        ("Annualized %", "annualized_return", "+.1f"),
        ("Max DD %", "max_drawdown", ".1f"),
        ("Win Rate %", "win_rate", ".1f"),
        ("Avg Win %", "avg_win", "+.2f"),
        ("Avg Loss %", "avg_loss", "+.2f"),
        ("Profit Factor", "profit_factor", ".2f"),
        ("Max Consec Losses", "max_consec_losses", "d"),
    ]

    for label, key, fmt in metric_keys:
        row = f"  {label:22s}"
        for scheme in schemes:
            val = scheme_metrics[scheme][key]
            if fmt == "d":
                row += f"  {int(val):>8d}"
            elif fmt == ".2f":
                row += f"  {val:>8.2f}"
            elif fmt == ".1f":
                row += f"  {val:>8.1f}"
            elif fmt == "+.2f":
                row += f"  {val:>+8.2f}"
            elif fmt == "+.1f":
                row += f"  {val:>+8.1f}"
        print(row)

    # ========================================================================
    # WALK-FORWARD VALIDATION (ALL SCHEMES)
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD VALIDATION (7 splits)")
    print(f"{'='*70}")

    wf_results = walk_forward_regime(
        df_okx, bb_strategy, spring_strategy, bb_exit, spring_exit,
        allocation_schemes=schemes, n_splits=7,
    )

    for scheme in schemes:
        results = wf_results[scheme]
        profitable = sum(1 for r in results if r["sum"] > 0)
        mean_sharpe = np.mean([r["sharpe"] for r in results])
        total_sum = sum(r["sum"] for r in results)

        print(f"\n  {scheme_labels[scheme]}:")
        print(f"  {'Split':6s} {'Period':20s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>8s} {'Status':>6s}")
        print(f"  {'-'*6} {'-'*20} {'-'*7} {'-'*8} {'-'*8} {'-'*6}")
        for r in results:
            status = "✅" if r["sum"] > 0 else "❌"
            print(f"  {r['split']:>6d} {r['period']:20s} {r['trades']:>7d} {r['sum']:>+7.1f}% {r['sharpe']:>+7.2f}  {status:>6s}")
        print(f"  → {profitable}/{len(results)} OOS profitable | Mean Sharpe: {mean_sharpe:+.2f} | Total Sum: {total_sum:+.1f}%")

    # ========================================================================
    # BINANCE CROSS-VALIDATION
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  BINANCE CROSS-VALIDATION")
    print(f"{'='*70}")

    engine_bb_bn = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_bb_bn = engine_bb_bn.run(
        df_binance, bb_strategy, symbol="BTC/USDT",
        stop_loss_pct=bb_exit["stop_pct"],
        take_profit_pct=bb_exit["target_pct"],
        max_hold_bars=bb_exit["hold_hours"],
    )

    engine_sp_bn = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_sp_bn = engine_sp_bn.run(
        df_binance, spring_strategy, symbol="BTC/USDT",
        stop_loss_pct=spring_exit["stop_pct"],
        take_profit_pct=spring_exit["target_pct"],
        max_hold_bars=spring_exit["hold_hours"],
    )

    print(f"\n  {'Scheme':22s} {'OKX Sharpe':>11s} {'BNC Sharpe':>11s} {'OKX DD':>10s} {'BNC DD':>10s}")
    print(f"  {'-'*22} {'-'*11} {'-'*11} {'-'*10} {'-'*10}")

    for scheme in ["equal", "80_20"]:
        metrics_okx, _, _ = compute_regime_combined_metrics(
            result_bb.trades, result_sp.trades, df_okx, allocation_scheme=scheme
        )
        metrics_bnc, _, _ = compute_regime_combined_metrics(
            result_bb_bn.trades, result_sp_bn.trades, df_binance, allocation_scheme=scheme
        )
        print(f"  {scheme_labels[scheme]:22s} {metrics_okx['sharpe']:>+10.2f}  {metrics_bnc['sharpe']:>+10.2f}  "
              f"{metrics_okx['max_drawdown']:>9.1f}% {metrics_bnc['max_drawdown']:>9.1f}%")

    # ========================================================================
    # REGIME-BASED WEIGHT ANALYSIS
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  WEIGHT DISTRIBUTION ANALYSIS (80_20 scheme)")
    print(f"{'='*70}")

    regime = classify_regime_adx(df_okx)
    bb_weights = []
    sp_weights = []
    reg_labels = []
    for t in result_bb.trades:
        entry_ts = pd.Timestamp(t.entry_time, unit="ms")
        idx = df_okx.index.get_indexer([entry_ts], method="ffill")[0]
        if 0 <= idx < len(df_okx):
            reg = regime.iloc[idx]
            reg_labels.append(reg)
            if reg == "trending":
                bb_weights.append(80); sp_weights.append(20)
            elif reg == "ranging":
                bb_weights.append(20); sp_weights.append(80)
            else:
                bb_weights.append(50); sp_weights.append(50)

    spring_regs = []
    for t in result_sp.trades:
        entry_ts = pd.Timestamp(t.entry_time, unit="ms")
        idx = df_okx.index.get_indexer([entry_ts], method="ffill")[0]
        if 0 <= idx < len(df_okx):
            spring_regs.append(regime.iloc[idx])

    if reg_labels:
        reg_dist = Counter(reg_labels)
        print(f"  BB Breakout trades by entry regime:")
        for reg in ["trending", "neutral", "ranging"]:
            count = reg_dist.get(reg, 0)
            pct = count / len(reg_labels) * 100
            if reg == "trending": w = "80% BB / 20% Spring"
            elif reg == "ranging": w = "20% BB / 80% Spring"
            else: w = "50% BB / 50% Spring"
            print(f"    {reg:12s}: {count:>5d} ({pct:>5.1f}%)  → {w}")

    if spring_regs:
        sp_reg_dist = Counter(spring_regs)
        print(f"\n  Spring trades by entry regime:")
        for reg in ["trending", "neutral", "ranging"]:
            count = sp_reg_dist.get(reg, 0)
            pct = count / len(spring_regs) * 100
            if reg == "trending": w = "20% BB / 80% Spring"
            elif reg == "ranging": w = "80% BB / 20% Spring"
            else: w = "50% BB / 50% Spring"
            print(f"    {reg:12s}: {count:>5d} ({pct:>5.1f}%)  → {w}")

    # ========================================================================
    # STREAMLINED METRICS FOR TELEGRAM REPORT
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  FINAL SUMMARY — ALL METRICS")
    print(f"{'='*70}")

    for scheme in schemes:
        m = scheme_metrics[scheme]
        print(f"\n  {scheme_labels[scheme]}:")
        print(f"    Trades: {m['total_trades']}")
        print(f"    Return: {m['compound_return']:+.1f}% (linear: {m['linear_sum']:+.1f}%)")
        print(f"    Sharpe: {m['sharpe']:+.2f}, Sortino: {m['sortino']:+.2f}")
        print(f"    MaxDD: {m['max_drawdown']:.1f}%, WR: {m['win_rate']:.1f}%, PF: {m['profit_factor']:.2f}")

        # Exit breakdown
        print(f"    Exit breakdown:")
        for reason in ["take_profit", "stop_loss", "time_exit"]:
            count, pct, avg, total = m["exit_detail"][reason]
            if count > 0:
                print(f"      {reason:15s}: {count:>4d} ({pct:>5.1f}%) avg={avg:>+6.2f}% total={total:>+8.1f}%")

    # WF summary for all
    print(f"\n  Walk-Forward Summary:")
    for scheme in schemes:
        results = wf_results[scheme]
        profitable = sum(1 for r in results if r["sum"] > 0)
        mean_sharpe = np.mean([r["sharpe"] for r in results])
        print(f"    {scheme_labels[scheme]}: {profitable}/7 OOS profitable, Mean OOS Sharpe {mean_sharpe:+.2f}")

    print(f"\n{'='*70}")
    print(f"  RESEARCH COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
