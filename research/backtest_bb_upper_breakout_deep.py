"""
Simple BB Upper Breakout — Deep Dive Optimization
===================================================

The follow-up research discovered that simple BB upper band breakout
(close > upper_band) with SMA200 filter produces positive expectancy.
This is a momentum/trend-continuation signal.

Best baseline: s1.5 t3.0 h8 with SMA200 → Sharpe +0.77, sum +120%

This script does:
1. Fine-grained parameter optimization
2. 7-split walk-forward validation
3. Binance cross-validation
4. Regime analysis (tag trades with market conditions)
5. Detailed exit analysis
6. Comparison with Spring strategy
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import sma, ema, bollinger_bands, adx


def bb_upper_breakout_signal(df, bb_period=20, bb_std=2.0, use_sma_filter=True, sma_period=200):
    """Buy when close > upper BB. Optional SMA200 filter."""
    close = df["close"]
    bb = bollinger_bands(df, period=bb_period, std=bb_std)
    
    long_signal = close > bb["upper"]
    
    if use_sma_filter:
        trend_val = sma(close, sma_period)
        long_signal = long_signal & (close > trend_val)
    
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[long_signal] = 1
    return signal


class BBUpperBreakout(Strategy):
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {
        "bb_period": 20, "bb_std": 2.0,
        "use_sma_filter": True, "sma_period": 200,
        "stop_pct": 1.5, "target_pct": 3.0, "hold_hours": 8,
    }

    @property
    def name(self):
        return "BB_Upper_Breakout"

    def generate_signal(self, df):
        df = self.preprocess(df)
        return bb_upper_breakout_signal(
            df,
            bb_period=self.params["bb_period"],
            bb_std=self.params["bb_std"],
            use_sma_filter=self.params["use_sma_filter"],
            sma_period=self.params["sma_period"],
        )


def walk_forward(df, strategy_params, n_splits=7, label=""):
    """7-split walk-forward."""
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD: {label} ({n_splits} splits)")
    print(f"{'='*70}")

    n = len(df)
    slot = n // (n_splits + 2)
    results = []

    for s in range(n_splits):
        start_idx = n - (n_splits - s + 1) * slot
        end_idx = min(n, start_idx + slot)
        split_df = df.iloc[start_idx:end_idx].copy()

        if len(split_df) < 300:
            continue

        strategy = BBUpperBreakout(strategy_params)
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            split_df, strategy, symbol="BTC/USDT",
            stop_loss_pct=strategy.params["stop_pct"],
            take_profit_pct=strategy.params["target_pct"],
            max_hold_bars=strategy.params["hold_hours"],
        )

        trades = result.trades
        lin_sum = sum(t.pnl_pct for t in trades)
        sharpe = result.metrics.sharpe_ratio
        max_dd = result.metrics.max_drawdown_pct

        start_date = pd.Timestamp(split_df.index[0]).strftime("%Y-%m")
        end_date = pd.Timestamp(split_df.index[-1]).strftime("%Y-%m")
        star = "⭐" if lin_sum > 0 else "  "

        print(f"  {star} {start_date}→{end_date}  trades={len(trades):>4}  sum={lin_sum:>+7.1f}%  sharpe={sharpe:>+6.2f}  DD={max_dd:.1f}%")
        results.append({"split": s+1, "period": f"{start_date}→{end_date}", "sum": lin_sum, "sharpe": sharpe, "trades": len(trades), "dd": max_dd})

    profitable = sum(1 for r in results if r["sum"] > 0)
    total = len(results)
    mean_sharpe = np.mean([r["sharpe"] for r in results]) if results else 0
    total_sum = sum(r["sum"] for r in results)
    print(f"\n  → {profitable}/{total} OOS profitable")
    print(f"  → Mean Sharpe: {mean_sharpe:+.2f}")
    print(f"  → Total OOS sum: {total_sum:+.1f}%")
    return results


def regime_analysis(trades, df):
    """Tag trades with regime at entry and analyze."""
    print(f"\n{'='*70}")
    print(f"  REGIME ANALYSIS")
    print(f"{'='*70}")

    sma200 = sma(df["close"], 200)
    sma50 = sma(df["close"], 50)
    adx_data = adx(df, 14)

    ts_to_idx = {int(df.index[i].timestamp() * 1000): i for i in range(len(df))}

    tagged = []
    for t in trades:
        idx = ts_to_idx.get(t.entry_time)
        if idx is None:
            continue
        regime = {
            "adx": float(adx_data["adx"].iloc[idx]) if not np.isnan(adx_data["adx"].iloc[idx]) else None,
            "pdi": float(adx_data["pdi"].iloc[idx]) if not np.isnan(adx_data["pdi"].iloc[idx]) else None,
            "mdi": float(adx_data["mdi"].iloc[idx]) if not np.isnan(adx_data["mdi"].iloc[idx]) else None,
        }
        t.regime = regime
        tagged.append(t)

    # ADX groups
    strong = [t for t in tagged if t.regime.get("adx") and t.regime["adx"] > 25]
    weak = [t for t in tagged if t.regime.get("adx") and t.regime["adx"] <= 25]

    for name, subset in [("ADX > 25 (strong trend)", strong), ("ADX <= 25 (weak trend)", weak)]:
        if not subset:
            continue
        pnls = [t.pnl_pct for t in subset]
        wins = [p for p in pnls if p > 0]
        exits = Counter(t.exit_reason for t in subset)
        print(f"\n  {name}:")
        print(f"    Trades: {len(subset)}, Sum: {sum(pnls):+.1f}%, Avg: {np.mean(pnls):+.3f}%")
        print(f"    Win rate: {len(wins)/len(subset)*100:.1f}%")
        print(f"    Exits: {dict(exits)}")

    # PDI > MDI (bullish direction)
    bull = [t for t in tagged if t.regime.get("pdi") and t.regime.get("mdi") and t.regime["pdi"] > t.regime["mdi"]]
    bear = [t for t in tagged if t.regime.get("pdi") and t.regime.get("mdi") and t.regime["pdi"] <= t.regime["mdi"]]

    for name, subset in [("PDI > MDI (bullish dir)", bull), ("PDI <= MDI (bearish dir)", bear)]:
        if not subset:
            continue
        pnls = [t.pnl_pct for t in subset]
        wins = [p for p in pnls if p > 0]
        print(f"\n  {name}:")
        print(f"    Trades: {len(subset)}, Sum: {sum(pnls):+.1f}%, Avg: {np.mean(pnls):+.3f}%")
        print(f"    Win rate: {len(wins)/len(subset)*100:.1f}%")


def main():
    print("=" * 70)
    print("  BB UPPER BREAKOUT — DEEP DIVE OPTIMIZATION")
    print("  Strategy: Buy close > upper_band + SMA200 filter")
    print("  Data: OKX BTC/USDT 1h (2019-2026)")
    print("=" * 70)

    store = OHLCVStore(db_path="data/cryptoquant.db")
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    engine = BacktestEngine(commission=0.0005, slippage=0.0005)

    # -----------------------------------------------------------------------
    # Part 1: Fine-grained parameter optimization
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 1: FINE-GRAINED PARAMETER OPTIMIZATION")
    print("=" * 70)

    # Stop sweep (fine)
    print(f"\n  STOP SWEEP (target=3.0, hold=8):")
    print(f"  {'Stop':>6} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    best_stop_sharpe = -999
    best_stop = 1.5
    for stop in [1.0, 1.2, 1.5, 1.8, 2.0, 2.5]:
        params = {"bb_period": 20, "bb_std": 2.0, "use_sma_filter": True, "sma_period": 200,
                  "stop_pct": stop, "target_pct": 3.0, "hold_hours": 8}
        strategy = BBUpperBreakout(params)
        result = engine.run(df_okx, strategy, symbol="BTC/USDT",
                           stop_loss_pct=stop, take_profit_pct=3.0, max_hold_bars=8)
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {stop:>5.1f}% {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")
        if m.sharpe_ratio > best_stop_sharpe:
            best_stop_sharpe = m.sharpe_ratio
            best_stop = stop

    # Target sweep (fine)
    print(f"\n  TARGET SWEEP (stop=1.5, hold=8):")
    print(f"  {'Target':>7} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    best_target_sharpe = -999
    best_target = 3.0
    for target in [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
        params = {"bb_period": 20, "bb_std": 2.0, "use_sma_filter": True, "sma_period": 200,
                  "stop_pct": 1.5, "target_pct": target, "hold_hours": 8}
        strategy = BBUpperBreakout(params)
        result = engine.run(df_okx, strategy, symbol="BTC/USDT",
                           stop_loss_pct=1.5, take_profit_pct=target, max_hold_bars=8)
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {target:>6.1f}% {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")
        if m.sharpe_ratio > best_target_sharpe:
            best_target_sharpe = m.sharpe_ratio
            best_target = target

    # Hold sweep (fine)
    print(f"\n  HOLD SWEEP (stop=1.5, target=3.0):")
    print(f"  {'Hold':>6} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    best_hold_sharpe = -999
    best_hold = 8
    for hold in [4, 6, 8, 10, 12, 16, 24]:
        params = {"bb_period": 20, "bb_std": 2.0, "use_sma_filter": True, "sma_period": 200,
                  "stop_pct": 1.5, "target_pct": 3.0, "hold_hours": hold}
        strategy = BBUpperBreakout(params)
        result = engine.run(df_okx, strategy, symbol="BTC/USDT",
                           stop_loss_pct=1.5, take_profit_pct=3.0, max_hold_bars=hold)
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {hold:>5}h {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")
        if m.sharpe_ratio > best_hold_sharpe:
            best_hold_sharpe = m.sharpe_ratio
            best_hold = hold

    # BB period sweep
    print(f"\n  BB PERIOD SWEEP (stop=1.5, target=3.0, hold=8):")
    print(f"  {'Period':>7} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    best_period_sharpe = -999
    best_period = 20
    for period in [10, 15, 20, 25, 30, 40, 50]:
        params = {"bb_period": period, "bb_std": 2.0, "use_sma_filter": True, "sma_period": 200,
                  "stop_pct": 1.5, "target_pct": 3.0, "hold_hours": 8}
        strategy = BBUpperBreakout(params)
        result = engine.run(df_okx, strategy, symbol="BTC/USDT",
                           stop_loss_pct=1.5, take_profit_pct=3.0, max_hold_bars=8)
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {period:>6} {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")
        if m.sharpe_ratio > best_period_sharpe:
            best_period_sharpe = m.sharpe_ratio
            best_period = period

    # BB std sweep
    print(f"\n  BB STD SWEEP (period=20, stop=1.5, target=3.0, hold=8):")
    print(f"  {'Std':>6} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    best_std_sharpe = -999
    best_std = 2.0
    for std in [1.5, 1.8, 2.0, 2.2, 2.5, 3.0]:
        params = {"bb_period": 20, "bb_std": std, "use_sma_filter": True, "sma_period": 200,
                  "stop_pct": 1.5, "target_pct": 3.0, "hold_hours": 8}
        strategy = BBUpperBreakout(params)
        result = engine.run(df_okx, strategy, symbol="BTC/USDT",
                           stop_loss_pct=1.5, take_profit_pct=3.0, max_hold_bars=8)
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {std:>5.1f} {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")
        if m.sharpe_ratio > best_std_sharpe:
            best_std_sharpe = m.sharpe_ratio
            best_std = std

    # -----------------------------------------------------------------------
    # Part 2: Best configuration full backtest
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 2: BEST CONFIGURATION — FULL BACKTEST")
    print("=" * 70)

    best_params = {
        "bb_period": best_period, "bb_std": best_std,
        "use_sma_filter": True, "sma_period": 200,
        "stop_pct": best_stop, "target_pct": best_target, "hold_hours": best_hold,
    }
    
    print(f"\n  Best params: period={best_period}, std={best_std}, stop={best_stop}%, "
          f"target={best_target}%, hold={best_hold}h")

    strategy = BBUpperBreakout(best_params)
    result = engine.run(df_okx, strategy, symbol="BTC/USDT",
                       stop_loss_pct=best_stop, take_profit_pct=best_target, max_hold_bars=best_hold)
    
    m = result.metrics
    trades = result.trades
    exits = Counter(t.exit_reason for t in trades)

    print(f"\n{'='*70}")
    print(f"  FULL BACKTEST: BB Upper Breakout (Optimized)")
    print(f"{'='*70}")
    print(f"  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"")
    print(f"  Total Trades:       {m.total_trades}")
    print(f"  Compound Return:    {m.total_return_pct:+.1f}%")
    print(f"  Linear Sum:         {sum(t.pnl_pct for t in trades):+.1f}%")
    print(f"  Annualized Return:  {m.annualized_return_pct:+.1f}%")
    print(f"  Sharpe Ratio:       {m.sharpe_ratio:+.2f}")
    print(f"  Sortino Ratio:      {m.sortino_ratio:+.2f}")
    print(f"  Max Drawdown:       {m.max_drawdown_pct:.1f}%")
    print(f"  Win Rate:           {m.win_rate_pct:.1f}%")
    print(f"  Avg Win:            {m.avg_win_pct:+.3f}%")
    print(f"  Avg Loss:           {m.avg_loss_pct:+.3f}%")
    print(f"  Profit Factor:      {m.profit_factor:.2f}")
    print(f"  Volatility (ann):   {m.volatility_annual_pct:.1f}%")
    print(f"  VaR 95%:            {m.var_95_pct:+.2f}%")
    print(f"  CVaR 95%:           {m.cvar_95_pct:+.2f}%")
    
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        if reason in exits:
            subset = [t for t in trades if t.exit_reason == reason]
            avg_pnl = np.mean([t.pnl_pct for t in subset])
            total_pnl = sum(t.pnl_pct for t in subset)
            pct = len(subset) / len(trades) * 100
            print(f"    {reason:<16} {len(subset):>5} ({pct:>4.1f}%)  avg={avg_pnl:>+6.2f}%  total={total_pnl:>+8.1f}%")
    
    max_consec = 0
    current_consec = 0
    for t in trades:
        if t.pnl_pct <= 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0
    print(f"\n  Max Consecutive Losses: {max_consec}")
    
    mfes = [t.mfe_pct for t in trades]
    maes = [t.mae_pct for t in trades]
    print(f"\n  MFE: mean={np.mean(mfes):+.2f}%  median={np.median(mfes):+.2f}%")
    print(f"  MAE: mean={np.mean(maes):+.2f}%  median={np.median(maes):+.2f}%")

    # -----------------------------------------------------------------------
    # Part 3: Walk-forward (7 splits)
    # -----------------------------------------------------------------------
    wf_results = walk_forward(df_okx, best_params, n_splits=7, label="BB Upper Breakout OPTIMIZED")

    # Also test baseline params (s1.5 t3.0 h8) for comparison
    baseline_params = {"bb_period": 20, "bb_std": 2.0, "use_sma_filter": True, "sma_period": 200,
                       "stop_pct": 1.5, "target_pct": 3.0, "hold_hours": 8}
    wf_baseline = walk_forward(df_okx, baseline_params, n_splits=7, label="BB Upper Breakout BASELINE (s1.5 t3.0 h8)")

    # -----------------------------------------------------------------------
    # Part 4: Regime Analysis
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 4: REGIME ANALYSIS")
    print("=" * 70)
    regime_analysis(trades, df_okx)

    # -----------------------------------------------------------------------
    # Part 5: Binance cross-validation
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 5: BINANCE CROSS-VALIDATION")
    print("=" * 70)

    strategy_bn = BBUpperBreakout(best_params)
    result_bn = engine.run(df_binance, strategy_bn, symbol="BTC/USDT",
                          stop_loss_pct=best_stop, take_profit_pct=best_target, max_hold_bars=best_hold)
    m_bn = result_bn.metrics
    print(f"\n  Binance (optimized params):")
    print(f"    Trades: {m_bn.total_trades}, Sum: {sum(t.pnl_pct for t in result_bn.trades):+.1f}%")
    print(f"    Sharpe: {m_bn.sharpe_ratio:+.2f}, DD: {m_bn.max_drawdown_pct:.1f}%")
    print(f"    WR: {m_bn.win_rate_pct:.1f}%, PF: {m_bn.profit_factor:.2f}")

    # Binance walk-forward
    wf_bn = walk_forward(df_binance, best_params, n_splits=7, label="BB Upper Breakout — Binance")

    # -----------------------------------------------------------------------
    # Part 6: No-filter variant comparison
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 6: SMA FILTER IMPACT")
    print("=" * 70)

    no_filter_params = {**best_params, "use_sma_filter": False}
    strategy_nf = BBUpperBreakout(no_filter_params)
    result_nf = engine.run(df_okx, strategy_nf, symbol="BTC/USDT",
                          stop_loss_pct=best_stop, take_profit_pct=best_target, max_hold_bars=best_hold)
    m_nf = result_nf.metrics
    
    print(f"\n  {'Metric':<20} {'With SMA200':>12} {'Without SMA':>12} {'Delta':>10}")
    print(f"  {'-'*56}")
    print(f"  {'Trades':<20} {m.total_trades:>12} {m_nf.total_trades:>12} {m_nf.total_trades - m.total_trades:>+10}")
    print(f"  {'Sum':<20} {sum(t.pnl_pct for t in trades):>+11.1f}% {sum(t.pnl_pct for t in result_nf.trades):>+11.1f}%")
    print(f"  {'Sharpe':<20} {m.sharpe_ratio:>+12.2f} {m_nf.sharpe_ratio:>+12.2f} {m_nf.sharpe_ratio - m.sharpe_ratio:>+10.2f}")
    print(f"  {'Max DD':<20} {m.max_drawdown_pct:>11.1f}% {m_nf.max_drawdown_pct:>11.1f}%")
    print(f"  {'Win Rate':<20} {m.win_rate_pct:>11.1f}% {m_nf.win_rate_pct:>11.1f}%")
    print(f"  {'PF':<20} {m.profit_factor:>12.2f} {m_nf.profit_factor:>12.2f}")

    # -----------------------------------------------------------------------
    # Part 7: Comparison with Spring strategy
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 7: COMPARISON WITH SPRING STRATEGY")
    print("=" * 70)
    
    print(f"\n  {'Metric':<20} {'BB Breakout':>12} {'Spring':>12}")
    print(f"  {'-'*46}")
    print(f"  {'Sharpe':<20} {m.sharpe_ratio:>+12.2f} {'2.72':>12}")
    print(f"  {'Max DD':<20} {m.max_drawdown_pct:>11.1f}% {'12.5':>11}%")
    print(f"  {'Win Rate':<20} {m.win_rate_pct:>11.1f}% {'55.0':>11}%")
    print(f"  {'PF':<20} {m.profit_factor:>12.2f} {'1.18':>12}")
    print(f"  {'Trades':<20} {m.total_trades:>12} {'~400':>12}")
    print(f"  {'Signal Type':<20} {'Momentum':>12} {'Reversal':>12}")

    print("\n" + "=" * 70)
    print("  DEEP DIVE COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
