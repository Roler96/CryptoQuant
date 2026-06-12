"""
BB Upper Breakout — Volatility-Adaptive Dynamic Exits
======================================================

Research direction: The BB Breakout + SMA200 strategy (Sharpe +1.47, 7/7 WF)
has very different trade characteristics in different volatility regimes:

  High vol (ATR ratio > 1.5): 50.4% stop rate, +0.362% avg, WR 41.6%
  Low vol (ATR ratio ≤ 1.5):  35.4% stop rate, +0.256% avg, WR 47.2%

Hypothesis: Fixed exits (stop=1.0%, target=5.0%, hold=10h) are suboptimal
because they don't adapt to the volatility regime at entry.

In high vol:
  - 1.0% stop is too tight → random wicks trigger 50% stop-outs
  - 5.0% target is appropriate → breakouts produce big moves
  - Solution: widen stop to 1.5-2.0%, keep target wide

In low vol:
  - 1.0% stop is fine → fewer noise wicks
  - 5.0% target is too far → rarely hit in calm markets
  - Solution: tighten target to 2.5-3.5%, keep stop tight

Methodology:
1. Compute ATR(14) and its 200-bar median → vol_ratio
2. Tag each trade with vol regime at entry
3. Simulate with regime-dependent exits
4. Grid search over regime thresholds and exit params
5. Walk-forward validate the best configuration
6. Cross-validate on Binance

CRITICAL: Always use lows for stop checking.
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
from cryptoquant.strategy.signals import sma, bollinger_bands, atr as atr_func


# ============================================================================
# Custom backtest with per-trade dynamic exits
# ============================================================================

def custom_backtest(df, signals, vol_ratios, exit_map, commission=0.0005, slippage=0.0005):
    """
    Run backtest with regime-dependent exits.
    
    Args:
        df: OHLCV DataFrame
        signals: pd.Series of 0/1 signals
        vol_ratios: pd.Series of ATR/median_ATR ratios
        exit_map: dict mapping vol_regime -> (stop_pct, target_pct, hold_bars)
            vol_regime is one of: 'low', 'normal', 'high'
        commission: round-trip commission rate
        slippage: slippage per trade
    
    Returns:
        list of trade dicts
    """
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)
    
    trades = []
    position = None
    pending_signal = False
    
    for i in range(n):
        # Enter position
        if position is None and pending_signal:
            entry_price = opens[i]
            vr = vol_ratios.iloc[i] if i < len(vol_ratios) else 1.0
            
            # Determine vol regime
            if vr < 0.7:
                regime = 'low'
            elif vr > 1.5:
                regime = 'high'
            else:
                regime = 'normal'
            
            stop_pct, target_pct, hold_bars = exit_map[regime]
            
            position = {
                'entry_price': entry_price,
                'entry_idx': i,
                'stop_price': entry_price * (1 - stop_pct / 100),
                'target_price': entry_price * (1 + target_pct / 100),
                'hold_bars': hold_bars,
                'regime': regime,
                'vol_ratio': vr,
                'stop_pct': stop_pct,
                'target_pct': target_pct,
            }
            pending_signal = False
        
        # Check exits
        if position is not None:
            exit_reason = None
            exit_price = None
            hold = i - position['entry_idx']
            
            # Stop loss (lows-based!)
            if lows[i] <= position['stop_price']:
                exit_reason = 'stop_loss'
                exit_price = position['stop_price'] * (1 - slippage)
            # Take profit (highs-based)
            elif highs[i] >= position['target_price']:
                exit_reason = 'take_profit'
                exit_price = position['target_price'] * (1 - slippage)
            # Time exit
            elif hold >= position['hold_bars']:
                exit_reason = 'time_exit'
                exit_price = opens[i] * (1 - slippage)
            
            if exit_reason:
                pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                
                # MFE/MAE
                entry_idx = position['entry_idx']
                mfe = (max(highs[entry_idx:i+1]) / position['entry_price'] - 1) * 100
                mae = (min(lows[entry_idx:i+1]) / position['entry_price'] - 1) * 100
                
                trades.append({
                    'pnl_pct': pnl_pct,
                    'exit_reason': exit_reason,
                    'regime': position['regime'],
                    'vol_ratio': position['vol_ratio'],
                    'hold_bars': hold,
                    'mfe': mfe,
                    'mae': mae,
                    'entry_idx': entry_idx,
                    'exit_idx': i,
                    'stop_pct': position['stop_pct'],
                    'target_pct': position['target_pct'],
                })
                position = None
        
        # Pick up new signal
        if position is None and not pending_signal:
            if i < len(signals) and signals.iloc[i] == 1:
                pending_signal = True
    
    return trades


def compute_metrics(trades, label=""):
    """Compute and print metrics for a trade list."""
    if not trades:
        print(f"  {label}: NO TRADES")
        return {}
    
    pnls = [t['pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    exits = Counter(t['exit_reason'] for t in trades)
    
    total_wins = sum(wins) if wins else 0
    total_losses = abs(sum(losses)) if losses else 0
    pf = total_wins / total_losses if total_losses > 0 else float('inf')
    
    lin_sum = sum(pnls)
    wr = len(wins) / len(pnls) * 100
    
    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls))
    else:
        sharpe = 0
    
    # Compound return
    compound = 1.0
    for p in pnls:
        compound *= (1 + p / 100)
    compound_ret = (compound - 1) * 100
    
    metrics = {
        'trades': len(trades),
        'sum': lin_sum,
        'compound': compound_ret,
        'sharpe': sharpe,
        'wr': wr,
        'pf': pf,
        'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': np.mean(losses) if losses else 0,
        'exits': exits,
    }
    
    print(f"\n  {label}")
    print(f"    Trades: {len(trades):>5}  Sum: {lin_sum:>+8.1f}%  Compound: {compound_ret:>+8.1f}%")
    print(f"    Sharpe≈{sharpe:>+6.2f}  WR: {wr:>5.1f}%  PF: {pf:>5.2f}")
    print(f"    Avg win: {metrics['avg_win']:>+.3f}%  Avg loss: {metrics['avg_loss']:>+.3f}%")
    for reason in ['take_profit', 'stop_loss', 'time_exit']:
        if reason in exits:
            subset = [t for t in trades if t['exit_reason'] == reason]
            avg_pnl = np.mean([t['pnl_pct'] for t in subset])
            total_pnl = sum(t['pnl_pct'] for t in subset)
            pct = len(subset) / len(trades) * 100
            print(f"    {reason:<16} {len(subset):>5} ({pct:>4.1f}%)  avg={avg_pnl:>+6.2f}%  total={total_pnl:>+8.1f}%")
    
    return metrics


def walk_forward_custom(df, signals, vol_ratios, exit_map, n_splits=7, label=""):
    """Walk-forward with custom dynamic exits."""
    n = len(df)
    slot = n // (n_splits + 2)
    results = []
    
    for s in range(n_splits):
        start_idx = n - (n_splits - s + 1) * slot
        end_idx = min(n, start_idx + slot)
        
        split_df = df.iloc[start_idx:end_idx].copy()
        split_signals = signals.iloc[start_idx:end_idx].copy()
        split_vr = vol_ratios.iloc[start_idx:end_idx].copy()
        
        # Reset indices
        split_df = split_df.reset_index(drop=True)
        split_signals = split_signals.reset_index(drop=True)
        split_vr = split_vr.reset_index(drop=True)
        
        if len(split_df) < 300:
            continue
        
        trades = custom_backtest(split_df, split_signals, split_vr, exit_map)
        lin_sum = sum(t['pnl_pct'] for t in trades) if trades else 0
        
        pnls = [t['pnl_pct'] for t in trades] if trades else [0]
        if len(pnls) > 1 and np.std(pnls) > 0:
            sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls))
        else:
            sharpe = 0
        
        start_date = pd.Timestamp(df.index[start_idx]).strftime("%Y-%m")
        end_date = pd.Timestamp(df.index[min(end_idx-1, n-1)]).strftime("%Y-%m")
        star = "✅" if lin_sum > 0 else "❌"
        
        print(f"  {star} {start_date}→{end_date}  trades={len(trades):>4}  sum={lin_sum:>+7.1f}%  sharpe={sharpe:>+6.2f}")
        results.append({
            'split': s+1, 'period': f"{start_date}→{end_date}",
            'sum': lin_sum, 'sharpe': sharpe, 'trades': len(trades),
        })
    
    profitable = sum(1 for r in results if r['sum'] > 0)
    total = len(results)
    mean_sharpe = np.mean([r['sharpe'] for r in results]) if results else 0
    total_sum = sum(r['sum'] for r in results)
    print(f"  → {profitable}/{total} OOS profitable | Mean Sharpe: {mean_sharpe:+.2f} | Total: {total_sum:+.1f}%")
    return results


# ============================================================================
# Signal generation
# ============================================================================

def generate_signals_and_vol(df):
    """Generate BB breakout + SMA200 signals and vol ratios."""
    close = df["close"]
    bb = bollinger_bands(df, period=50, std=2.5)
    sma200 = sma(close, 200)
    
    signals = pd.Series(0, index=df.index, dtype=int)
    signals[(close > bb["upper"]) & (close > sma200)] = 1
    
    # Vol ratio: ATR(14) / median(ATR(14), 200)
    atr14 = atr_func(df, 14)
    median_atr = atr14.rolling(200, min_periods=50).median()
    vol_ratios = atr14 / median_atr.replace(0, np.nan)
    vol_ratios = vol_ratios.fillna(1.0)
    
    return signals, vol_ratios


# ============================================================================
# MAIN RESEARCH
# ============================================================================

def main():
    print("=" * 70)
    print("  BB UPPER BREAKOUT — VOLATILITY-ADAPTIVE DYNAMIC EXITS")
    print("  Data: OKX BTC/USDT 1h (2019-2026)")
    print("=" * 70)
    
    store = OHLCVStore(db_path="data/cryptoquant.db")
    df = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    
    signals, vol_ratios = generate_signals_and_vol(df)
    signals_bn, vol_ratios_bn = generate_signals_and_vol(df_binance)
    
    # ====================================================================
    # STEP 1: Baseline — fixed exits (SMA200, stop=1.0, target=5.0, hold=10)
    # ====================================================================
    print("\n" + "=" * 70)
    print("  STEP 1: BASELINE — Fixed Exits (SMA200 + s1.0/t5.0/h10)")
    print("=" * 70)
    
    fixed_exits = {
        'low': (1.0, 5.0, 10),
        'normal': (1.0, 5.0, 10),
        'high': (1.0, 5.0, 10),
    }
    
    trades_okx = custom_backtest(df, signals, vol_ratios, fixed_exits)
    baseline_metrics = compute_metrics(trades_okx, "OKX Baseline (fixed exits)")
    
    trades_bn = custom_backtest(df_binance, signals_bn, vol_ratios_bn, fixed_exits)
    compute_metrics(trades_bn, "Binance Baseline (fixed exits)")
    
    # ====================================================================
    # STEP 2: Regime distribution analysis
    # ====================================================================
    print("\n" + "=" * 70)
    print("  STEP 2: VOL REGIME DISTRIBUTION AT ENTRY")
    print("=" * 70)
    
    regime_stats = defaultdict(list)
    for t in trades_okx:
        regime_stats[t['regime']].append(t)
    
    for regime in ['low', 'normal', 'high']:
        subset = regime_stats[regime]
        if not subset:
            print(f"\n  {regime}: NO TRADES")
            continue
        pnls = [t['pnl_pct'] for t in subset]
        wins = [p for p in pnls if p > 0]
        exits = Counter(t['exit_reason'] for t in subset)
        avg_vr = np.mean([t['vol_ratio'] for t in subset])
        
        print(f"\n  {regime.upper()} VOL (avg vol_ratio={avg_vr:.2f}):")
        print(f"    Trades: {len(subset):>5}  Sum: {sum(pnls):>+8.1f}%  WR: {len(wins)/len(subset)*100:>5.1f}%")
        print(f"    Avg PnL: {np.mean(pnls):>+.3f}%  Avg MFE: {np.mean([t['mfe'] for t in subset]):>+.3f}%")
        for reason in ['take_profit', 'stop_loss', 'time_exit']:
            if reason in exits:
                sub = [t for t in subset if t['exit_reason'] == reason]
                print(f"    {reason:<16} {len(sub):>5} ({len(sub)/len(subset)*100:>4.1f}%)  avg={np.mean([t['pnl_pct'] for t in sub]):>+.2f}%")
    
    # ====================================================================
    # STEP 3: Vol regime threshold sweep
    # ====================================================================
    print("\n" + "=" * 70)
    print("  STEP 3: THRESHOLD SWEEP — Find optimal vol regime boundaries")
    print("=" * 70)
    
    # Test different threshold combinations
    # low_threshold: below this → low vol regime
    # high_threshold: above this → high vol regime
    thresholds = [
        (0.5, 1.3), (0.5, 1.5), (0.5, 1.8), (0.5, 2.0),
        (0.6, 1.3), (0.6, 1.5), (0.6, 1.8), (0.6, 2.0),
        (0.7, 1.3), (0.7, 1.5), (0.7, 1.8), (0.7, 2.0),
        (0.8, 1.3), (0.8, 1.5), (0.8, 1.8), (0.8, 2.0),
        (0.9, 1.3), (0.9, 1.5), (0.9, 1.8), (0.9, 2.0),
    ]
    
    # For each threshold, test a few exit configs
    exit_configs = {
        'A': {'low': (0.8, 3.0, 8), 'normal': (1.0, 5.0, 10), 'high': (1.5, 6.0, 12)},
        'B': {'low': (0.8, 3.0, 8), 'normal': (1.0, 4.0, 10), 'high': (1.5, 7.0, 12)},
        'C': {'low': (1.0, 3.5, 8), 'normal': (1.0, 5.0, 10), 'high': (1.8, 6.0, 14)},
        'D': {'low': (0.8, 2.5, 6), 'normal': (1.0, 4.5, 10), 'high': (1.5, 6.0, 12)},
        'E': {'low': (1.0, 3.0, 8), 'normal': (1.0, 5.0, 10), 'high': (2.0, 7.0, 14)},
        'F': {'low': (0.8, 3.5, 10), 'normal': (1.0, 5.0, 10), 'high': (1.5, 5.0, 10)},
    }
    
    best_overall = {'sharpe': -999, 'sum': -999}
    
    print(f"\n  {'Thresholds':<14} {'Config':<8} {'Trades':>6} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*14} {'-'*8} {'-'*6} {'-'*8} {'-'*7} {'-'*6} {'-'*6}")
    
    for low_t, high_t in thresholds:
        # Recompute regimes with new thresholds
        def get_regime(vr):
            if vr < low_t:
                return 'low'
            elif vr > high_t:
                return 'high'
            else:
                return 'normal'
        
        for cfg_name, exit_map_raw in exit_configs.items():
            # Remap exits based on new regime boundaries
            exit_map = {
                'low': exit_map_raw['low'],
                'normal': exit_map_raw['normal'],
                'high': exit_map_raw['high'],
            }
            
            # Custom regime assignment
            trades = []
            opens = df["open"].values
            highs_arr = df["high"].values
            lows_arr = df["low"].values
            n = len(df)
            position = None
            pending_signal = False
            
            for i in range(n):
                if position is None and pending_signal:
                    entry_price = opens[i]
                    vr = vol_ratios.iloc[i]
                    
                    if vr < low_t:
                        regime = 'low'
                    elif vr > high_t:
                        regime = 'high'
                    else:
                        regime = 'normal'
                    
                    stop_pct, target_pct, hold_bars = exit_map[regime]
                    
                    position = {
                        'entry_price': entry_price,
                        'entry_idx': i,
                        'stop_price': entry_price * (1 - stop_pct / 100),
                        'target_price': entry_price * (1 + target_pct / 100),
                        'hold_bars': hold_bars,
                        'regime': regime,
                        'vol_ratio': vr,
                    }
                    pending_signal = False
                
                if position is not None:
                    exit_reason = None
                    exit_price = None
                    hold = i - position['entry_idx']
                    
                    if lows_arr[i] <= position['stop_price']:
                        exit_reason = 'stop_loss'
                        exit_price = position['stop_price'] * 0.9995
                    elif highs_arr[i] >= position['target_price']:
                        exit_reason = 'take_profit'
                        exit_price = position['target_price'] * 0.9995
                    elif hold >= position['hold_bars']:
                        exit_reason = 'time_exit'
                        exit_price = opens[i] * 0.9995
                    
                    if exit_reason:
                        pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                        trades.append({
                            'pnl_pct': pnl_pct,
                            'exit_reason': exit_reason,
                            'regime': position['regime'],
                        })
                        position = None
                
                if position is None and not pending_signal:
                    if i < len(signals) and signals.iloc[i] == 1:
                        pending_signal = True
            
            if not trades:
                continue
            
            pnls = [t['pnl_pct'] for t in trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            total_w = sum(wins) if wins else 0
            total_l = abs(sum(losses)) if losses else 0
            pf = total_w / total_l if total_l > 0 else 0
            lin_sum = sum(pnls)
            wr = len(wins) / len(pnls) * 100
            if len(pnls) > 1 and np.std(pnls) > 0:
                sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls))
            else:
                sharpe = 0
            
            marker = ""
            if sharpe > best_overall['sharpe']:
                best_overall = {'sharpe': sharpe, 'sum': lin_sum, 'low_t': low_t, 'high_t': high_t, 'cfg': cfg_name}
                marker = " ← BEST"
            
            print(f"  {low_t:.1f}/{high_t:.1f}       {cfg_name:<8} {len(trades):>6} {lin_sum:>+8.1f}% {sharpe:>+7.2f} {wr:>5.1f}% {pf:>5.2f}{marker}")
    
    print(f"\n  Best: thresholds={best_overall.get('low_t', 0):.1f}/{best_overall.get('high_t', 0):.1f}, config={best_overall.get('cfg', '?')}, Sharpe={best_overall['sharpe']:+.2f}, Sum={best_overall['sum']:+.1f}%")
    
    # ====================================================================
    # STEP 4: Focused test of most promising configurations
    # ====================================================================
    print("\n" + "=" * 70)
    print("  STEP 4: FOCUSED CONFIGURATIONS — Detailed Analysis")
    print("=" * 70)
    
    # Based on the sweep, test the most promising configs in detail
    # We'll test several specific hypotheses:
    
    configs_to_test = {
        'FIXED (baseline)': {
            'low': (1.0, 5.0, 10), 'normal': (1.0, 5.0, 10), 'high': (1.0, 5.0, 10),
            'thresholds': (0.7, 1.5),
        },
        'V1: Wide stop high-vol': {
            'low': (0.8, 3.0, 8), 'normal': (1.0, 5.0, 10), 'high': (1.8, 6.0, 12),
            'thresholds': (0.7, 1.5),
        },
        'V2: Tight target low-vol': {
            'low': (0.8, 2.5, 6), 'normal': (1.0, 5.0, 10), 'high': (1.0, 5.0, 10),
            'thresholds': (0.7, 1.5),
        },
        'V3: Both adaptations': {
            'low': (0.8, 3.0, 8), 'normal': (1.0, 5.0, 10), 'high': (1.8, 7.0, 14),
            'thresholds': (0.7, 1.5),
        },
        'V4: 3-tier aggressive': {
            'low': (0.8, 2.5, 6), 'normal': (1.0, 4.5, 10), 'high': (2.0, 8.0, 16),
            'thresholds': (0.7, 1.5),
        },
        'V5: Only high-vol adj': {
            'low': (1.0, 5.0, 10), 'normal': (1.0, 5.0, 10), 'high': (1.8, 7.0, 14),
            'thresholds': (0.7, 1.5),
        },
        'V6: Only low-vol adj': {
            'low': (0.8, 3.0, 8), 'normal': (1.0, 5.0, 10), 'high': (1.0, 5.0, 10),
            'thresholds': (0.7, 1.5),
        },
        'V7: Wider thresholds': {
            'low': (0.8, 3.0, 8), 'normal': (1.0, 5.0, 10), 'high': (1.8, 7.0, 14),
            'thresholds': (0.6, 1.8),
        },
        'V8: Narrow thresholds': {
            'low': (0.8, 3.0, 8), 'normal': (1.0, 5.0, 10), 'high': (1.8, 7.0, 14),
            'thresholds': (0.8, 1.3),
        },
    }
    
    for cfg_name, cfg in configs_to_test.items():
        low_t, high_t = cfg['thresholds']
        exit_map = {'low': cfg['low'], 'normal': cfg['normal'], 'high': cfg['high']}
        
        # Run custom backtest with these thresholds
        trades = []
        opens = df["open"].values
        highs_arr = df["high"].values
        lows_arr = df["low"].values
        n = len(df)
        position = None
        pending_signal = False
        
        for i in range(n):
            if position is None and pending_signal:
                entry_price = opens[i]
                vr = vol_ratios.iloc[i]
                
                if vr < low_t:
                    regime = 'low'
                elif vr > high_t:
                    regime = 'high'
                else:
                    regime = 'normal'
                
                stop_pct, target_pct, hold_bars = exit_map[regime]
                
                position = {
                    'entry_price': entry_price,
                    'entry_idx': i,
                    'stop_price': entry_price * (1 - stop_pct / 100),
                    'target_price': entry_price * (1 + target_pct / 100),
                    'hold_bars': hold_bars,
                    'regime': regime,
                    'vol_ratio': vr,
                    'stop_pct': stop_pct,
                    'target_pct': target_pct,
                }
                pending_signal = False
            
            if position is not None:
                exit_reason = None
                exit_price = None
                hold = i - position['entry_idx']
                
                if lows_arr[i] <= position['stop_price']:
                    exit_reason = 'stop_loss'
                    exit_price = position['stop_price'] * 0.9995
                elif highs_arr[i] >= position['target_price']:
                    exit_reason = 'take_profit'
                    exit_price = position['target_price'] * 0.9995
                elif hold >= position['hold_bars']:
                    exit_reason = 'time_exit'
                    exit_price = opens[i] * 0.9995
                
                if exit_reason:
                    pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                    entry_idx = position['entry_idx']
                    mfe = (max(highs_arr[entry_idx:i+1]) / position['entry_price'] - 1) * 100
                    mae = (min(lows_arr[entry_idx:i+1]) / position['entry_price'] - 1) * 100
                    trades.append({
                        'pnl_pct': pnl_pct,
                        'exit_reason': exit_reason,
                        'regime': position['regime'],
                        'vol_ratio': position['vol_ratio'],
                        'hold_bars': hold,
                        'mfe': mfe,
                        'mae': mae,
                        'entry_idx': entry_idx,
                        'exit_idx': i,
                        'stop_pct': position['stop_pct'],
                        'target_pct': position['target_pct'],
                    })
                    position = None
            
            if position is None and not pending_signal:
                if i < len(signals) and signals.iloc[i] == 1:
                    pending_signal = True
        
        compute_metrics(trades, f"OKX {cfg_name}")
    
    # ====================================================================
    # STEP 5: Walk-forward of top configurations
    # ====================================================================
    print("\n" + "=" * 70)
    print("  STEP 5: WALK-FORWARD VALIDATION — Top Configs")
    print("=" * 70)
    
    # Pick the top 3 configs for walk-forward
    wf_configs = {
        'FIXED (baseline)': {
            'low': (1.0, 5.0, 10), 'normal': (1.0, 5.0, 10), 'high': (1.0, 5.0, 10),
            'thresholds': (0.7, 1.5),
        },
        'V3: Both adaptations': {
            'low': (0.8, 3.0, 8), 'normal': (1.0, 5.0, 10), 'high': (1.8, 7.0, 14),
            'thresholds': (0.7, 1.5),
        },
        'V5: Only high-vol adj': {
            'low': (1.0, 5.0, 10), 'normal': (1.0, 5.0, 10), 'high': (1.8, 7.0, 14),
            'thresholds': (0.7, 1.5),
        },
    }
    
    wf_results = {}
    for cfg_name, cfg in wf_configs.items():
        low_t, high_t = cfg['thresholds']
        exit_map = {'low': cfg['low'], 'normal': cfg['normal'], 'high': cfg['high']}
        
        print(f"\n  --- {cfg_name} ---")
        results = walk_forward_custom(df, signals, vol_ratios, exit_map, n_splits=7, label=f"OKX {cfg_name}")
        wf_results[cfg_name] = results
    
    # ====================================================================
    # STEP 6: Binance cross-validation of best config
    # ====================================================================
    print("\n" + "=" * 70)
    print("  STEP 6: BINANCE CROSS-VALIDATION")
    print("=" * 70)
    
    # Test the best config on Binance
    for cfg_name, cfg in wf_configs.items():
        low_t, high_t = cfg['thresholds']
        exit_map = {'low': cfg['low'], 'normal': cfg['normal'], 'high': cfg['high']}
        
        print(f"\n  --- {cfg_name} (Binance) ---")
        walk_forward_custom(df_binance, signals_bn, vol_ratios_bn, exit_map, n_splits=7, label=f"Binance {cfg_name}")
    
    # ====================================================================
    # STEP 7: Fine-grained parameter sweep for best config
    # ====================================================================
    print("\n" + "=" * 70)
    print("  STEP 7: FINE-GRAINED SWEEP — High-vol stop/target optimization")
    print("=" * 70)
    
    # Fix low/normal exits, sweep high-vol exits
    # The key question: what's the optimal stop/target for high-vol regime?
    
    print(f"\n  {'HiStop':>6} {'HiTgt':>6} {'HiHold':>6} {'Trades':>6} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*7} {'-'*6} {'-'*6}")
    
    best_hv = {'sharpe': -999}
    
    for hi_stop in [1.2, 1.5, 1.8, 2.0, 2.5]:
        for hi_target in [5.0, 6.0, 7.0, 8.0, 9.0, 10.0]:
            for hi_hold in [10, 12, 14, 16]:
                exit_map = {
                    'low': (1.0, 5.0, 10),
                    'normal': (1.0, 5.0, 10),
                    'high': (hi_stop, hi_target, hi_hold),
                }
                low_t, high_t = 0.7, 1.5
                
                trades = []
                opens = df["open"].values
                highs_arr = df["high"].values
                lows_arr = df["low"].values
                n = len(df)
                position = None
                pending_signal = False
                
                for i in range(n):
                    if position is None and pending_signal:
                        entry_price = opens[i]
                        vr = vol_ratios.iloc[i]
                        
                        if vr < low_t:
                            regime = 'low'
                        elif vr > high_t:
                            regime = 'high'
                        else:
                            regime = 'normal'
                        
                        stop_pct, target_pct, hold_bars = exit_map[regime]
                        
                        position = {
                            'entry_price': entry_price,
                            'entry_idx': i,
                            'stop_price': entry_price * (1 - stop_pct / 100),
                            'target_price': entry_price * (1 + target_pct / 100),
                            'hold_bars': hold_bars,
                            'regime': regime,
                        }
                        pending_signal = False
                    
                    if position is not None:
                        exit_reason = None
                        exit_price = None
                        hold = i - position['entry_idx']
                        
                        if lows_arr[i] <= position['stop_price']:
                            exit_reason = 'stop_loss'
                            exit_price = position['stop_price'] * 0.9995
                        elif highs_arr[i] >= position['target_price']:
                            exit_reason = 'take_profit'
                            exit_price = position['target_price'] * 0.9995
                        elif hold >= position['hold_bars']:
                            exit_reason = 'time_exit'
                            exit_price = opens[i] * 0.9995
                        
                        if exit_reason:
                            pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                            trades.append({'pnl_pct': pnl_pct, 'exit_reason': exit_reason})
                            position = None
                    
                    if position is None and not pending_signal:
                        if i < len(signals) and signals.iloc[i] == 1:
                            pending_signal = True
                
                if not trades:
                    continue
                
                pnls = [t['pnl_pct'] for t in trades]
                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p <= 0]
                total_w = sum(wins) if wins else 0
                total_l = abs(sum(losses)) if losses else 0
                pf = total_w / total_l if total_l > 0 else 0
                lin_sum = sum(pnls)
                wr = len(wins) / len(pnls) * 100
                if len(pnls) > 1 and np.std(pnls) > 0:
                    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls))
                else:
                    sharpe = 0
                
                marker = ""
                if sharpe > best_hv['sharpe']:
                    best_hv = {'sharpe': sharpe, 'sum': lin_sum, 'stop': hi_stop, 'target': hi_target, 'hold': hi_hold}
                    marker = " ← BEST"
                
                print(f"  {hi_stop:>6.1f} {hi_target:>6.1f} {hi_hold:>6} {len(trades):>6} {lin_sum:>+8.1f}% {sharpe:>+7.2f} {wr:>5.1f}% {pf:>5.2f}{marker}")
    
    print(f"\n  Best high-vol config: stop={best_hv.get('stop', '?')}, target={best_hv.get('target', '?')}, hold={best_hv.get('hold', '?')}")
    print(f"  Sharpe={best_hv['sharpe']:+.2f}, Sum={best_hv['sum']:+.1f}%")
    
    # ====================================================================
    # STEP 8: Low-vol optimization
    # ====================================================================
    print("\n" + "=" * 70)
    print("  STEP 8: FINE-GRAINED SWEEP — Low-vol stop/target optimization")
    print("=" * 70)
    
    print(f"\n  {'LoStop':>6} {'LoTgt':>6} {'LoHold':>6} {'Trades':>6} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*7} {'-'*6} {'-'*6}")
    
    best_lv = {'sharpe': -999}
    
    # Use best high-vol config from step 7
    best_hi_stop = best_hv.get('stop', 1.0)
    best_hi_target = best_hv.get('target', 5.0)
    best_hi_hold = best_hv.get('hold', 10)
    
    for lo_stop in [0.6, 0.8, 1.0, 1.2]:
        for lo_target in [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
            for lo_hold in [6, 8, 10, 12]:
                exit_map = {
                    'low': (lo_stop, lo_target, lo_hold),
                    'normal': (1.0, 5.0, 10),
                    'high': (best_hi_stop, best_hi_target, best_hi_hold),
                }
                low_t, high_t = 0.7, 1.5
                
                trades = []
                opens = df["open"].values
                highs_arr = df["high"].values
                lows_arr = df["low"].values
                n = len(df)
                position = None
                pending_signal = False
                
                for i in range(n):
                    if position is None and pending_signal:
                        entry_price = opens[i]
                        vr = vol_ratios.iloc[i]
                        
                        if vr < low_t:
                            regime = 'low'
                        elif vr > high_t:
                            regime = 'high'
                        else:
                            regime = 'normal'
                        
                        stop_pct, target_pct, hold_bars = exit_map[regime]
                        
                        position = {
                            'entry_price': entry_price,
                            'entry_idx': i,
                            'stop_price': entry_price * (1 - stop_pct / 100),
                            'target_price': entry_price * (1 + target_pct / 100),
                            'hold_bars': hold_bars,
                            'regime': regime,
                        }
                        pending_signal = False
                    
                    if position is not None:
                        exit_reason = None
                        exit_price = None
                        hold = i - position['entry_idx']
                        
                        if lows_arr[i] <= position['stop_price']:
                            exit_reason = 'stop_loss'
                            exit_price = position['stop_price'] * 0.9995
                        elif highs_arr[i] >= position['target_price']:
                            exit_reason = 'take_profit'
                            exit_price = position['target_price'] * 0.9995
                        elif hold >= position['hold_bars']:
                            exit_reason = 'time_exit'
                            exit_price = opens[i] * 0.9995
                        
                        if exit_reason:
                            pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                            trades.append({'pnl_pct': pnl_pct, 'exit_reason': exit_reason})
                            position = None
                    
                    if position is None and not pending_signal:
                        if i < len(signals) and signals.iloc[i] == 1:
                            pending_signal = True
                
                if not trades:
                    continue
                
                pnls = [t['pnl_pct'] for t in trades]
                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p <= 0]
                total_w = sum(wins) if wins else 0
                total_l = abs(sum(losses)) if losses else 0
                pf = total_w / total_l if total_l > 0 else 0
                lin_sum = sum(pnls)
                wr = len(wins) / len(pnls) * 100
                if len(pnls) > 1 and np.std(pnls) > 0:
                    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls))
                else:
                    sharpe = 0
                
                marker = ""
                if sharpe > best_lv['sharpe']:
                    best_lv = {'sharpe': sharpe, 'sum': lin_sum, 'stop': lo_stop, 'target': lo_target, 'hold': lo_hold}
                    marker = " ← BEST"
                
                print(f"  {lo_stop:>6.1f} {lo_target:>6.1f} {lo_hold:>6} {len(trades):>6} {lin_sum:>+8.1f}% {sharpe:>+7.2f} {wr:>5.1f}% {pf:>5.2f}{marker}")
    
    print(f"\n  Best low-vol config: stop={best_lv.get('stop', '?')}, target={best_lv.get('target', '?')}, hold={best_lv.get('hold', '?')}")
    print(f"  Sharpe={best_lv['sharpe']:+.2f}, Sum={best_lv['sum']:+.1f}%")
    
    # ====================================================================
    # STEP 9: Final combined config — walk-forward + cross-validation
    # ====================================================================
    print("\n" + "=" * 70)
    print("  STEP 9: FINAL COMBINED CONFIG — Walk-Forward + Cross-Validation")
    print("=" * 70)
    
    final_configs = {
        'FIXED baseline': {
            'low': (1.0, 5.0, 10), 'normal': (1.0, 5.0, 10), 'high': (1.0, 5.0, 10),
            'thresholds': (0.7, 1.5),
        },
        'Best HV only': {
            'low': (1.0, 5.0, 10), 'normal': (1.0, 5.0, 10),
            'high': (best_hi_stop, best_hi_target, best_hi_hold),
            'thresholds': (0.7, 1.5),
        },
        'Best HV + Best LV': {
            'low': (best_lv.get('stop', 1.0), best_lv.get('target', 5.0), best_lv.get('hold', 10)),
            'normal': (1.0, 5.0, 10),
            'high': (best_hi_stop, best_hi_target, best_hi_hold),
            'thresholds': (0.7, 1.5),
        },
    }
    
    for cfg_name, cfg in final_configs.items():
        low_t, high_t = cfg['thresholds']
        exit_map = {'low': cfg['low'], 'normal': cfg['normal'], 'high': cfg['high']}
        
        # Full-period OKX
        trades = []
        opens = df["open"].values
        highs_arr = df["high"].values
        lows_arr = df["low"].values
        n = len(df)
        position = None
        pending_signal = False
        
        for i in range(n):
            if position is None and pending_signal:
                entry_price = opens[i]
                vr = vol_ratios.iloc[i]
                
                if vr < low_t:
                    regime = 'low'
                elif vr > high_t:
                    regime = 'high'
                else:
                    regime = 'normal'
                
                stop_pct, target_pct, hold_bars = exit_map[regime]
                
                position = {
                    'entry_price': entry_price,
                    'entry_idx': i,
                    'stop_price': entry_price * (1 - stop_pct / 100),
                    'target_price': entry_price * (1 + target_pct / 100),
                    'hold_bars': hold_bars,
                    'regime': regime,
                    'vol_ratio': vr,
                    'stop_pct': stop_pct,
                    'target_pct': target_pct,
                }
                pending_signal = False
            
            if position is not None:
                exit_reason = None
                exit_price = None
                hold = i - position['entry_idx']
                
                if lows_arr[i] <= position['stop_price']:
                    exit_reason = 'stop_loss'
                    exit_price = position['stop_price'] * 0.9995
                elif highs_arr[i] >= position['target_price']:
                    exit_reason = 'take_profit'
                    exit_price = position['target_price'] * 0.9995
                elif hold >= position['hold_bars']:
                    exit_reason = 'time_exit'
                    exit_price = opens[i] * 0.9995
                
                if exit_reason:
                    pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                    entry_idx = position['entry_idx']
                    mfe = (max(highs_arr[entry_idx:i+1]) / position['entry_price'] - 1) * 100
                    mae = (min(lows_arr[entry_idx:i+1]) / position['entry_price'] - 1) * 100
                    trades.append({
                        'pnl_pct': pnl_pct,
                        'exit_reason': exit_reason,
                        'regime': position['regime'],
                        'vol_ratio': position['vol_ratio'],
                        'hold_bars': hold,
                        'mfe': mfe,
                        'mae': mae,
                        'entry_idx': entry_idx,
                        'exit_idx': i,
                        'stop_pct': position['stop_pct'],
                        'target_pct': position['target_pct'],
                    })
                    position = None
            
            if position is None and not pending_signal:
                if i < len(signals) and signals.iloc[i] == 1:
                    pending_signal = True
        
        compute_metrics(trades, f"OKX {cfg_name}")
        
        # Walk-forward OKX
        print(f"\n  Walk-Forward OKX — {cfg_name}:")
        walk_forward_custom(df, signals, vol_ratios, exit_map, n_splits=7)
        
        # Walk-forward Binance
        print(f"\n  Walk-Forward Binance — {cfg_name}:")
        walk_forward_custom(df_binance, signals_bn, vol_ratios_bn, exit_map, n_splits=7)
    
    # ====================================================================
    # STEP 10: Regime-specific analysis of final config
    # ====================================================================
    print("\n" + "=" * 70)
    print("  STEP 10: REGIME ANALYSIS — Final Config Per-Regime Breakdown")
    print("=" * 70)
    
    # Use the best combined config
    best_combined = final_configs['Best HV + Best LV']
    low_t, high_t = best_combined['thresholds']
    exit_map = {'low': best_combined['low'], 'normal': best_combined['normal'], 'high': best_combined['high']}
    
    trades = []
    opens = df["open"].values
    highs_arr = df["high"].values
    lows_arr = df["low"].values
    n = len(df)
    position = None
    pending_signal = False
    
    for i in range(n):
        if position is None and pending_signal:
            entry_price = opens[i]
            vr = vol_ratios.iloc[i]
            
            if vr < low_t:
                regime = 'low'
            elif vr > high_t:
                regime = 'high'
            else:
                regime = 'normal'
            
            stop_pct, target_pct, hold_bars = exit_map[regime]
            
            position = {
                'entry_price': entry_price,
                'entry_idx': i,
                'stop_price': entry_price * (1 - stop_pct / 100),
                'target_price': entry_price * (1 + target_pct / 100),
                'hold_bars': hold_bars,
                'regime': regime,
                'vol_ratio': vr,
                'stop_pct': stop_pct,
                'target_pct': target_pct,
            }
            pending_signal = False
        
        if position is not None:
            exit_reason = None
            exit_price = None
            hold = i - position['entry_idx']
            
            if lows_arr[i] <= position['stop_price']:
                exit_reason = 'stop_loss'
                exit_price = position['stop_price'] * 0.9995
            elif highs_arr[i] >= position['target_price']:
                exit_reason = 'take_profit'
                exit_price = position['target_price'] * 0.9995
            elif hold >= position['hold_bars']:
                exit_reason = 'time_exit'
                exit_price = opens[i] * 0.9995
            
            if exit_reason:
                pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                entry_idx = position['entry_idx']
                mfe = (max(highs_arr[entry_idx:i+1]) / position['entry_price'] - 1) * 100
                mae = (min(lows_arr[entry_idx:i+1]) / position['entry_price'] - 1) * 100
                trades.append({
                    'pnl_pct': pnl_pct,
                    'exit_reason': exit_reason,
                    'regime': position['regime'],
                    'vol_ratio': position['vol_ratio'],
                    'hold_bars': hold,
                    'mfe': mfe,
                    'mae': mae,
                    'entry_idx': entry_idx,
                    'exit_idx': i,
                    'stop_pct': position['stop_pct'],
                    'target_pct': position['target_pct'],
                })
                position = None
        
        if position is None and not pending_signal:
            if i < len(signals) and signals.iloc[i] == 1:
                pending_signal = True
    
    print(f"\n  Final config: low={exit_map['low']}, normal={exit_map['normal']}, high={exit_map['high']}")
    print(f"  Thresholds: low<{low_t}, high>{high_t}")
    
    regime_stats = defaultdict(list)
    for t in trades:
        regime_stats[t['regime']].append(t)
    
    for regime in ['low', 'normal', 'high']:
        subset = regime_stats[regime]
        if not subset:
            print(f"\n  {regime}: NO TRADES")
            continue
        pnls = [t['pnl_pct'] for t in subset]
        wins = [p for p in pnls if p > 0]
        exits = Counter(t['exit_reason'] for t in subset)
        avg_vr = np.mean([t['vol_ratio'] for t in subset])
        
        print(f"\n  {regime.upper()} VOL (avg vol_ratio={avg_vr:.2f}, exits: s={exit_map[regime][0]}/t={exit_map[regime][1]}/h={exit_map[regime][2]}):")
        print(f"    Trades: {len(subset):>5}  Sum: {sum(pnls):>+8.1f}%  WR: {len(wins)/len(subset)*100:>5.1f}%")
        print(f"    Avg PnL: {np.mean(pnls):>+.3f}%  Avg MFE: {np.mean([t['mfe'] for t in subset]):>+.3f}%  Avg MAE: {np.mean([t['mae'] for t in subset]):>+.3f}%")
        for reason in ['take_profit', 'stop_loss', 'time_exit']:
            if reason in exits:
                sub = [t for t in subset if t['exit_reason'] == reason]
                print(f"    {reason:<16} {len(sub):>5} ({len(sub)/len(subset)*100:>4.1f}%)  avg={np.mean([t['pnl_pct'] for t in sub]):>+.2f}%  total={sum(t['pnl_pct'] for t in sub):>+8.1f}%")
    
    print("\n" + "=" * 70)
    print("  RESEARCH COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
