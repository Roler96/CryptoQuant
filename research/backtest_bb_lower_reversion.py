"""
BB Lower Band Mean Reversion — New Strategy Research
=====================================================

Research direction: The BB Upper Breakout strategy (momentum/continuation) works well
in trending markets (Sharpe +1.38, 6/7 WF) but struggles in sideways/ranging markets.
This script tests the complementary strategy: buying when price touches the lower
Bollinger Band and bounces — a mean-reversion signal that should work best when
momentum strategies struggle.

Hypothesis: Lower BB touches in non-crash conditions produce small but reliable
bounces (+1-3%) back toward the mean. This is a classic mean-reversion signal.

Methodology (per quant-strategy-development skill):
1. Test simple BB lower band bounce signal
2. Regime analysis — which conditions work best?
3. Add filters to remove toxic regimes
4. Exit optimization — sweep target/hold/stop
5. Walk-forward validation
6. Cross-validate on Binance

CRITICAL: Always use lows for stop checking (engine default).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter, defaultdict
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import sma, ema, bollinger_bands, adx, atr, rsi


# ============================================================================
# Strategy: BB Lower Band Mean Reversion
# ============================================================================

class BBLowerReversion(Strategy):
    """Buy when price bounces off the lower Bollinger Band.

    The signal fires when:
    1. Price was below (or near) the lower BB last bar
    2. Price closes above the lower BB this bar (the "bounce")
    
    This is a pure mean-reversion signal — we're buying weakness in the
    expectation of a snap-back toward the middle band.
    """
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "use_sma_filter": False,
        "sma_period": 200,
        "stop_pct": 2.5,
        "target_pct": 2.5,
        "hold_hours": 12,
    }

    @property
    def name(self):
        return "BB_Lower_Reversion"

    def generate_signal(self, df):
        df = self.preprocess(df)
        close = df["close"]
        
        bb = bollinger_bands(df, period=self.params["bb_period"], 
                             std=self.params["bb_std"])
        
        # Signal: close was below lower BB last bar, now crossed above it
        was_below = close.shift(1) < bb["lower"].shift(1)
        now_above = close > bb["lower"]
        bounced = was_below & now_above
        
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[bounced] = 1
        
        return signal


class BBLowerReversionFiltered(Strategy):
    """BB Lower Reversion with SMA filter (above SMA only — pullbacks in uptrends)."""
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "use_sma_filter": True,
        "sma_period": 200,
        "stop_pct": 2.5,
        "target_pct": 2.5,
        "hold_hours": 12,
    }

    @property
    def name(self):
        return "BB_Lower_Reversion_Filtered"

    def generate_signal(self, df):
        df = self.preprocess(df)
        close = df["close"]
        
        bb = bollinger_bands(df, period=self.params["bb_period"],
                             std=self.params["bb_std"])
        sma200 = sma(close, 200)
        
        was_below = close.shift(1) < bb["lower"].shift(1)
        now_above = close > bb["lower"]
        above_sma = close > sma200
        
        bounced = was_below & now_above & above_sma
        
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[bounced] = 1
        
        return signal


# ============================================================================
# Helpers
# ============================================================================

def run_backtest(df, strategy_cls, params, engine=None):
    """Run backtest with given strategy and params."""
    if engine is None:
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
    strategy = strategy_cls(params)
    result = engine.run(
        df, strategy, symbol="BTC/USDT",
        stop_loss_pct=params.get("stop_pct", 2.5),
        take_profit_pct=params.get("target_pct", 2.5),
        max_hold_bars=params.get("hold_hours", 12),
    )
    return result, result.trades


def print_full_metrics(result, trades, label=""):
    """Print comprehensive backtest metrics."""
    m = result.metrics
    
    # Max consecutive losses
    max_consec = 0
    current = 0
    for t in trades:
        if t.pnl_pct <= 0:
            current += 1
            max_consec = max(max_consec, current)
        else:
            current = 0
    
    # Exit breakdown
    exits = Counter(t.exit_reason for t in trades)
    
    # MFE stats
    mfe_values = [t.mfe_pct for t in trades]
    mae_values = [t.mae_pct for t in trades]
    
    print(f"\n  {'='*50}")
    print(f"  {label}")
    print(f"  {'='*50}")
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
    print(f"  Max Consec Losses:  {max_consec}")
    if mfe_values:
        print(f"  Avg MFE:            {np.mean(mfe_values):+.3f}%")
        print(f"  Avg MAE:            {np.mean(mae_values):+.3f}%")
    print(f"")
    print(f"  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        if reason in exits:
            subset = [t for t in trades if t.exit_reason == reason]
            avg_pnl = np.mean([t.pnl_pct for t in subset])
            total_pnl = sum(t.pnl_pct for t in subset)
            pct = len(subset) / len(trades) * 100
            print(f"    {reason:<16} {len(subset):>5} ({pct:>4.1f}%)  avg={avg_pnl:>+6.2f}%  total={total_pnl:>+8.1f}%")


def walk_forward(df, strategy_cls, params, n_splits=7, label=""):
    """Walk-forward validation."""
    n = len(df)
    slot = n // (n_splits + 2)
    results = []
    
    print(f"\n  --- Walk-Forward ({label}) ---")
    
    for s in range(n_splits):
        start_idx = n - (n_splits - s + 1) * slot
        end_idx = min(n, start_idx + slot)
        split_df = df.iloc[start_idx:end_idx].copy()
        
        if len(split_df) < 300:
            continue
        
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        strategy = strategy_cls(params)
        result = engine.run(split_df, strategy, symbol="BTC/USDT",
                           stop_loss_pct=params.get("stop_pct", 2.5),
                           take_profit_pct=params.get("target_pct", 2.5),
                           max_hold_bars=params.get("hold_hours", 12))
        lin_sum = sum(t.pnl_pct for t in result.trades)
        sharpe = result.metrics.sharpe_ratio
        max_dd = result.metrics.max_drawdown_pct
        
        start_date = pd.Timestamp(split_df.index[0]).strftime("%Y-%m")
        end_date = pd.Timestamp(split_df.index[-1]).strftime("%Y-%m")
        star = "✅" if lin_sum > 0 else "❌"
        
        print(f"  {star} Split {s+1}: {start_date}→{end_date}  trades={len(result.trades):>4}  sum={lin_sum:>+7.1f}%  sharpe={sharpe:>+6.2f}  DD={max_dd:.1f}%")
        
        results.append({
            "split": s+1, "period": f"{start_date}→{end_date}",
            "sum": lin_sum, "sharpe": sharpe, "trades": len(result.trades),
            "dd": max_dd
        })
    
    profitable = sum(1 for r in results if r["sum"] > 0)
    total = len(results)
    mean_sharpe = np.mean([r["sharpe"] for r in results]) if results else 0
    total_sum = sum(r["sum"] for r in results)
    print(f"  → {profitable}/{total} OOS profitable | Mean Sharpe: {mean_sharpe:+.2f} | Total OOS: {total_sum:+.1f}%")
    return results


def regime_analysis(df, trades, engine):
    """Tag every trade with regime conditions at entry."""
    close = df["close"]
    sma200 = sma(close, 200)
    sma50 = sma(close, 50)
    adx_data = adx(df, 14)
    atr_data = atr(df, 14)
    atr_median = atr_data.rolling(200).median()
    rsi_data = rsi(close, 14)
    bb = bollinger_bands(df, 20, 2.0)
    
    # 48h drawdown
    rolling_max = close.rolling(48).max()
    dd48 = (close / rolling_max - 1) * 100
    
    # Volume ratio
    vol_sma20 = df["volume"].rolling(20).mean()
    
    # Build index lookup from timestamp (ms)
    ts_to_idx = {}
    for i in range(len(df)):
        ts_to_idx[int(df.index[i].timestamp() * 1000)] = i
    
    tagged = []
    for t in trades:
        idx = ts_to_idx.get(t.entry_time)
        if idx is None:
            continue
        
        def safe_float(val):
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return None
            return float(val)
        
        tag = {
            "above_sma200": bool(close.iloc[idx] > sma200.iloc[idx]) if not np.isnan(sma200.iloc[idx]) else None,
            "above_sma50": bool(close.iloc[idx] > sma50.iloc[idx]) if not np.isnan(sma50.iloc[idx]) else None,
            "adx": safe_float(adx_data["adx"].iloc[idx]),
            "pdi": safe_float(adx_data["pdi"].iloc[idx]),
            "mdi": safe_float(adx_data["mdi"].iloc[idx]),
            "atr_ratio": safe_float(atr_data.iloc[idx] / atr_median.iloc[idx]) if atr_median.iloc[idx] > 0 else None,
            "rsi": safe_float(rsi_data.iloc[idx]),
            "dd48": safe_float(dd48.iloc[idx]),
            "vol_ratio": safe_float(df["volume"].iloc[idx] / vol_sma20.iloc[idx]) if vol_sma20.iloc[idx] > 0 else None,
            "pct_b": safe_float(bb["pct_b"].iloc[idx]),
            "hour": int(df.index[idx].hour),
            "pnl": t.pnl_pct,
            "exit_reason": t.exit_reason,
            "entry_time": t.entry_time,
            "mfe": t.mfe_pct,
            "mae": t.mae_pct,
        }
        tagged.append(tag)
    
    return tagged


def print_regime(name, subset, label=""):
    """Print regime stats."""
    if len(subset) < 3:
        return
    pnls = [t["pnl"] for t in subset]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = len(wins) / len(pnls) * 100 if pnls else 0
    exits = Counter(t["exit_reason"] for t in subset)
    total_wins = sum(wins) if wins else 0
    total_losses = abs(sum(losses)) if losses else 0
    pf = total_wins / total_losses if total_losses > 0 else float('inf')
    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0
    avg_mfe = np.mean([t["mfe"] for t in subset]) if subset else 0
    
    print(f"\n  {name}:")
    print(f"    Trades: {len(subset):>5}  Sum: {sum(pnls):>+8.1f}%  Sharpe: {sharpe:>+6.2f}  WR: {wr:>5.1f}%  PF: {pf:>5.2f}  AvgMFE: {avg_mfe:>+.2f}%")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        if reason in exits:
            sub2 = [t for t in subset if t["exit_reason"] == reason]
            avg_p = np.mean([t["pnl"] for t in sub2])
            print(f"      {reason:<16} {len(sub2):>4} ({len(sub2)/len(subset)*100:>4.0f}%)  avg={avg_p:>+6.2f}%")


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("  BB LOWER BAND MEAN REVERSION — NEW STRATEGY RESEARCH")
    print("  Data: OKX BTC/USDT 1h (2019-2026)")
    print("=" * 70)
    
    store = OHLCVStore(db_path="data/cryptoquant.db")
    df = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    engine = BacktestEngine(commission=0.0005, slippage=0.0005)
    
    # ========================================================================
    # PART 1: Simple BB Lower Band Bounce (no filters)
    # ========================================================================
    print("\n" + "=" * 70)
    print("  PART 1: SIMPLE BB LOWER BAND BOUNCE (ALL CONDITIONS)")
    print("=" * 70)
    
    simple_params = {
        "bb_period": 20, "bb_std": 2.0,
        "use_sma_filter": False,
        "stop_pct": 2.5, "target_pct": 2.5, "hold_hours": 12,
    }
    
    result, trades = run_backtest(df, BBLowerReversion, simple_params, engine)
    print_full_metrics(result, trades, "Baseline (BB20/2.0, s2.5/t2.5/h12, no filter)")
    
    m = result.metrics
    baseline_total = m.sharpe_ratio
    
    # ========================================================================
    # PART 2: SMA200 FILTER — Above SMA only (pullbacks in uptrend)
    # ========================================================================
    print("\n" + "=" * 70)
    print("  PART 2: SMA200 FILTER")
    print("=" * 70)
    
    sma_params = {**simple_params, "use_sma_filter": True, "sma_period": 200}
    result2, trades2 = run_backtest(df, BBLowerReversionFiltered, sma_params, engine)
    print_full_metrics(result2, trades2, "SMA200 Filter (above SMA only)")
    
    # ========================================================================
    # PART 3: REGIME ANALYSIS (on unfiltered to find toxic regimes)
    # ========================================================================
    print("\n" + "=" * 70)
    print("  PART 3: REGIME ANALYSIS")
    print("=" * 70)
    
    tagged = regime_analysis(df, trades, engine)
    print(f"\n  Total tagged trades: {len(tagged)}")
    
    # 3a: SMA200
    print(f"\n  --- SMA200 REGIME ---")
    above = [t for t in tagged if t["above_sma200"] == True]
    below = [t for t in tagged if t["above_sma200"] == False]
    print_regime("Above SMA200", above)
    print_regime("Below SMA200", below)
    
    # 3b: ADX
    print(f"\n  --- TREND STRENGTH (ADX) ---")
    for thresh in [20, 25, 30]:
        strong = [t for t in tagged if t["adx"] is not None and t["adx"] > thresh]
        weak = [t for t in tagged if t["adx"] is not None and t["adx"] <= thresh]
        print_regime(f"ADX > {thresh}", strong)
        print_regime(f"ADX ≤ {thresh}", weak)
    
    # 3c: Directional movement
    print(f"\n  --- DIRECTIONAL MOVEMENT ---")
    pdi_gt = [t for t in tagged if t["pdi"] is not None and t["mdi"] is not None and t["pdi"] > t["mdi"]]
    pdi_lt = [t for t in tagged if t["pdi"] is not None and t["mdi"] is not None and t["pdi"] <= t["mdi"]]
    print_regime("PDI > MDI (bullish)", pdi_gt)
    print_regime("PDI ≤ MDI (bearish)", pdi_lt)
    
    # 3d: RSI
    print(f"\n  --- RSI(14) ---")
    for lo, hi, label in [(0, 30, "Oversold (<30)"), (30, 40, "Weak (30-40)"), 
                            (40, 50, "Neutral (40-50)"), (50, 100, "Strong (>50)")]:
        subset = [t for t in tagged if t["rsi"] is not None and lo <= t["rsi"] < hi]
        print_regime(f"RSI {label}", subset)
    
    # 3e: Volatility
    print(f"\n  --- VOLATILITY (ATR ratio) ---")
    for threshold in [0.8, 1.2, 1.5]:
        hi = [t for t in tagged if t["atr_ratio"] is not None and t["atr_ratio"] > threshold]
        lo = [t for t in tagged if t["atr_ratio"] is not None and t["atr_ratio"] <= threshold]
        print_regime(f"ATR ratio > {threshold}", hi)
    
    # 3f: Recent drawdown
    print(f"\n  --- 48h DRAWDOWN ---")
    for label, condition in [
        ("Crash (< -5%)", lambda t: t["dd48"] is not None and t["dd48"] < -5),
        ("Drop (-5 to -2%)", lambda t: t["dd48"] is not None and -5 <= t["dd48"] < -2),
        ("Flat (-2 to 0%)", lambda t: t["dd48"] is not None and -2 <= t["dd48"] < 0),
        ("Up (> 0%)", lambda t: t["dd48"] is not None and t["dd48"] >= 0),
    ]:
        subset = [t for t in tagged if condition(t)]
        print_regime(label, subset)
    
    # 3g: Hour of day
    print(f"\n  --- HOUR OF DAY (UTC) ---")
    for label, hours in [("Asian (0-8)", range(0,8)), ("London (8-16)", range(8,16)), ("NY (16-24)", range(16,24))]:
        subset = [t for t in tagged if t["hour"] in hours]
        print_regime(label, subset)
    
    # 3h: Combined toxic regimes
    print(f"\n  --- COMBINED REGIMES ---")
    
    # Below SMA200 + bearish direction
    toxic1 = [t for t in tagged if t["above_sma200"] == False 
              and t["pdi"] is not None and t["mdi"] is not None and t["pdi"] <= t["mdi"]]
    print_regime("TOXIC: Below SMA200 + PDI≤MDI", toxic1)
    
    # Below SMA200 + high ADX (strong downtrend)
    toxic2 = [t for t in tagged if t["above_sma200"] == False 
              and t["adx"] is not None and t["adx"] > 25]
    print_regime("TOXIC: Below SMA200 + ADX>25", toxic2)
    
    # Crash conditions
    toxic3 = [t for t in tagged if t["dd48"] is not None and t["dd48"] < -5]
    print_regime("TOXIC: 48h crash (< -5%)", toxic3)
    
    # GOLDEN: Above SMA200 + low ADX (ranging pullback)
    golden1 = [t for t in tagged if t["above_sma200"] == True 
               and t["adx"] is not None and t["adx"] <= 20]
    print_regime("GOLDEN: Above SMA200 + ADX≤20 (ranging pullback)", golden1)
    
    # GOLDEN: Above SMA200 + RSI 30-45 (oversold in uptrend)
    golden2 = [t for t in tagged if t["above_sma200"] == True 
               and t["rsi"] is not None and 30 <= t["rsi"] < 45]
    print_regime("GOLDEN: Above SMA200 + RSI 30-45", golden2)
    
    # ========================================================================
    # PART 4: EXIT OPTIMIZATION
    # ========================================================================
    print("\n" + "=" * 70)
    print("  PART 4: EXIT OPTIMIZATION (SMA200 filtered only)")
    print("=" * 70)
    
    base_filtered = {**simple_params, "use_sma_filter": True, "sma_period": 200}
    
    # 4a: Target sweep
    print(f"\n  TARGET SWEEP (s2.5, h12):")
    print(f"  {'Target':>7} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    best_target_sharpe = -999
    best_target_params = None
    for target in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
        p = {**base_filtered, "target_pct": target}
        r, ts = run_backtest(df, BBLowerReversionFiltered, p, engine)
        lin_sum = sum(t.pnl_pct for t in ts)
        print(f"  {target:>6.1f}% {r.metrics.total_trades:>7} {lin_sum:>+7.1f}% {r.metrics.sharpe_ratio:>+8.2f} {r.metrics.max_drawdown_pct:>7.1f}% {r.metrics.win_rate_pct:>5.1f}% {r.metrics.profit_factor:>5.2f}")
        if r.metrics.sharpe_ratio > best_target_sharpe:
            best_target_sharpe = r.metrics.sharpe_ratio
            best_target_params = p.copy()
    
    # 4b: Hold sweep with best target
    if best_target_params:
        best_target = best_target_params["target_pct"]
        print(f"\n  HOLD SWEEP (s2.5, target={best_target}%):")
        print(f"  {'Hold':>6} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
        best_hold_sharpe = -999
        best_params = None
        for hold in [4, 6, 8, 10, 12, 16, 20, 24]:
            p = {**best_target_params, "hold_hours": hold}
            r, ts = run_backtest(df, BBLowerReversionFiltered, p, engine)
            lin_sum = sum(t.pnl_pct for t in ts)
            print(f"  {hold:>5}h {r.metrics.total_trades:>7} {lin_sum:>+7.1f}% {r.metrics.sharpe_ratio:>+8.2f} {r.metrics.max_drawdown_pct:>7.1f}% {r.metrics.win_rate_pct:>5.1f}% {r.metrics.profit_factor:>5.2f}")
            if r.metrics.sharpe_ratio > best_hold_sharpe:
                best_hold_sharpe = r.metrics.sharpe_ratio
                best_params = p.copy()
        
        # 4c: Stop sweep with best target+hold
        if best_params:
            best_target = best_params["target_pct"]
            best_hold = best_params["hold_hours"]
            print(f"\n  STOP SWEEP (target={best_target}%, hold={best_hold}h):")
            print(f"  {'Stop':>6} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
            for stop in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
                p = {**best_params, "stop_pct": stop}
                r, ts = run_backtest(df, BBLowerReversionFiltered, p, engine)
                lin_sum = sum(t.pnl_pct for t in ts)
                print(f"  {stop:>5.1f}% {r.metrics.total_trades:>7} {lin_sum:>+7.1f}% {r.metrics.sharpe_ratio:>+8.2f} {r.metrics.max_drawdown_pct:>7.1f}% {r.metrics.win_rate_pct:>5.1f}% {r.metrics.profit_factor:>5.2f}")
        
        # Full backtest of best params
        if best_params:
            print(f"\n  === BEST CONFIGURATION FULL BACKTEST ===")
            result_opt, trades_opt = run_backtest(df, BBLowerReversionFiltered, best_params, engine)
            print_full_metrics(result_opt, trades_opt, f"Optimized (s{best_params['stop_pct']}%/t{best_params['target_pct']}%/h{best_params['hold_hours']}h)")
    
    # ========================================================================
    # PART 5: WALK-FORWARD VALIDATION
    # ========================================================================
    print("\n" + "=" * 70)
    print("  PART 5: WALK-FORWARD VALIDATION")
    print("=" * 70)
    
    print("\n  → Baseline (unfiltered):")
    wf_simple = walk_forward(df, BBLowerReversion, simple_params, 7, "unfiltered")
    
    print("\n  → SMA200 filtered:")
    wf_filtered = walk_forward(df, BBLowerReversionFiltered, sma_params, 7, "SMA200 filtered")
    
    if best_params:
        print(f"\n  → Optimized (s{best_params['stop_pct']}%/t{best_params['target_pct']}%/h{best_params['hold_hours']}h):")
        wf_opt = walk_forward(df, BBLowerReversionFiltered, best_params, 7, "optimized")
    
    # ========================================================================
    # PART 6: BINANCE CROSS-VALIDATION
    # ========================================================================
    print("\n" + "=" * 70)
    print("  PART 6: BINANCE CROSS-VALIDATION")
    print("=" * 70)
    
    result_bin, trades_bin = run_backtest(df_binance, BBLowerReversion, simple_params, engine)
    print_full_metrics(result_bin, trades_bin, "Binance — Baseline (unfiltered)")
    
    result_bin2, trades_bin2 = run_backtest(df_binance, BBLowerReversionFiltered, sma_params, engine)
    print_full_metrics(result_bin2, trades_bin2, "Binance — SMA200 filtered")
    
    print("\n  → Binance Walk-Forward (SMA200 filtered):")
    wf_bin = walk_forward(df_binance, BBLowerReversionFiltered, sma_params, 7, "Binance SMA200")
    
    print("\n" + "=" * 70)
    print("  RESEARCH COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
