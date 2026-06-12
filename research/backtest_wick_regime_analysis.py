"""
Wick Inversion — Comprehensive Regime Analysis
================================================

Research direction: The Wick Inversion strategy has Sharpe 0.41 on BTC/USDT 1h
(OKX, 2019-2026). It's positive but marginal — not tradeable as-is.

Key observation: 48% of trades are time-exits with avg loss (-0.36%). This suggests
the signal enters in wrong conditions ~half the time. But 39.7% of trades hit the
+1.5% target, suggesting genuine edge in SOME conditions.

Hypothesis: The signal has edge in specific market regimes but is toxic in others.
If we can identify and filter toxic regimes, we can improve Sharpe significantly.

Methodology (per quant-strategy-development skill):
1. Run full backtest, tag every trade with market conditions at entry
2. Group by regime and compare performance
3. If some regimes are toxic → filter them out
4. If all regimes are profitable → the EXIT is the problem, not the entry
5. Walk-forward validate any promising filter

Regime dimensions to analyze:
- SMA200: price above/below 200-period SMA
- ADX: trend strength (strong > 25, weak < 25)
- PDI/MDI: directional movement (bullish vs bearish)
- Volatility: ATR ratio vs 200-bar median
- Recent drawdown: 48h price change
- Hour of day: UTC hour
- Trend regime: 200-day return (bull/bear/sideways)
- Combined toxic regimes

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
from cryptoquant.strategy.signals import (
    sma, ema, atr as atr_func, adx as adx_func,
    wick_imbalance, pct_change_rolling, rsi
)


# ============================================================================
# Custom backtest that records regime tags per trade
# ============================================================================

def regime_backtest(df, signals, regime_data, stop_pct=3.0, target_pct=1.5,
                    max_hold=12, commission=0.0005, slippage=0.0005):
    """
    Run backtest and tag each trade with regime data at entry time.
    
    Returns list of trade dicts with regime info.
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
            entry_idx = i
            stop_price = entry_price * (1 - stop_pct / 100)
            target_price = entry_price * (1 + target_pct / 100)
            
            # Capture regime data at entry
            entry_regime = {}
            for key, arr in regime_data.items():
                entry_regime[key] = arr[i] if i < len(arr) else None
            
            position = {
                'entry_price': entry_price,
                'entry_idx': entry_idx,
                'stop_price': stop_price,
                'target_price': target_price,
                'regime': entry_regime,
            }
            pending_signal = False
        
        # Check exits
        if position is not None:
            exit_reason = None
            exit_price = None
            exit_idx = i
            
            # Stop loss (lows-based — CRITICAL)
            if lows[i] <= position['stop_price']:
                exit_reason = 'stop_loss'
                exit_price = position['stop_price'] * (1 - slippage)
            # Take profit (highs-based)
            elif highs[i] >= position['target_price']:
                exit_reason = 'take_profit'
                exit_price = position['target_price'] * (1 - slippage)
            # Time exit
            elif (i - position['entry_idx']) >= max_hold:
                exit_reason = 'time_exit'
                exit_price = opens[i] * (1 - slippage)
            
            if exit_reason:
                pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                
                # Compute MFE and MAE
                hold_slice = slice(position['entry_idx'], i + 1)
                mfe = (max(highs[hold_slice]) / position['entry_price'] - 1) * 100
                mae = (min(lows[hold_slice]) / position['entry_price'] - 1) * 100
                
                trades.append({
                    'entry_idx': position['entry_idx'],
                    'exit_idx': i,
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct,
                    'exit_reason': exit_reason,
                    'mfe_pct': mfe,
                    'mae_pct': mae,
                    'hold_bars': i - position['entry_idx'],
                    'regime': position['regime'],
                    'entry_time': df.index[position['entry_idx']],
                    'exit_time': df.index[i],
                })
                position = None
        
        # Check for new signal
        if position is None and not pending_signal:
            if signals.iloc[i] == 1:
                pending_signal = True
    
    return trades


def compute_regime_data(df):
    """Compute all regime indicators for the DataFrame."""
    closes = df["close"]
    
    # SMA200
    sma200 = sma(closes, 200)
    above_sma200 = (closes > sma200).values
    
    # SMA50
    sma50 = sma(closes, 50)
    above_sma50 = (closes > sma50).values
    
    # ADX, PDI, MDI
    adx_data = adx_func(df, period=14)
    adx_vals = adx_data["adx"].values
    pdi_vals = adx_data["pdi"].values
    mdi_vals = adx_data["mdi"].values
    pdi_gt_mdi = (pdi_vals > mdi_vals)
    
    # ATR and vol ratio
    atr14 = atr_func(df, 14)
    median_atr = atr14.rolling(200).median()
    vol_ratio = (atr14 / median_atr).values
    
    # Recent drawdown (48h)
    price_48h = pct_change_rolling(closes, 48).values
    
    # Recent drawdown (168h = 1 week)
    price_168h = pct_change_rolling(closes, 168).values
    
    # Hour of day (UTC)
    hours = df.index.hour.values
    
    # Day of week (0=Monday, 6=Sunday)
    dow = df.index.dayofweek.values
    
    # Trend regime: 200-day (4800 bars) return
    ret_200d = pct_change_rolling(closes, 4800).values
    
    # RSI(14)
    rsi14 = rsi(closes, 14).values
    
    # Bollinger %B
    bb_mid = sma(closes, 20)
    bb_std = closes.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    pct_b = ((closes - bb_lower) / (bb_upper - bb_lower)).values
    
    # EMA50 vs EMA200 (trend confirmation)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    ema_bull = (ema50 > ema200).values
    
    regime_data = {
        'above_sma200': above_sma200,
        'above_sma50': above_sma50,
        'adx': adx_vals,
        'pdi': pdi_vals,
        'mdi': mdi_vals,
        'pdi_gt_mdi': pdi_gt_mdi,
        'vol_ratio': vol_ratio,
        'price_48h': price_48h,
        'price_168h': price_168h,
        'hour_utc': hours,
        'day_of_week': dow,
        'ret_200d': ret_200d,
        'rsi14': rsi14,
        'pct_b': pct_b,
        'ema_bull': ema_bull,
    }
    
    return regime_data


def analyze_regime(trades, regime_key, bins=None, labels=None, discrete=False):
    """Analyze trade performance grouped by a regime dimension."""
    if not trades:
        return {}
    
    if discrete:
        groups = defaultdict(list)
        for t in trades:
            val = t['regime'].get(regime_key)
            if val is not None:
                groups[val].append(t)
    else:
        if bins is None:
            return {}
        groups = defaultdict(list)
        for t in trades:
            val = t['regime'].get(regime_key)
            if val is None or np.isnan(val):
                continue
            bin_idx = np.digitize(val, bins) - 1
            bin_idx = max(0, min(bin_idx, len(labels) - 1))
            groups[labels[bin_idx]].append(t)
    
    results = {}
    for label, group_trades in sorted(groups.items(), key=lambda x: str(x[0])):
        pnls = [t['pnl_pct'] for t in group_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        total_sum = sum(pnls)
        avg_pnl = np.mean(pnls)
        win_rate = len(wins) / len(pnls) * 100 if pnls else 0
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        
        # Simple Sharpe approximation
        if len(pnls) > 1 and np.std(pnls) > 0:
            sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls))
        else:
            sharpe = 0
        
        exit_counts = Counter(t['exit_reason'] for t in group_trades)
        avg_mfe = np.mean([t['mfe_pct'] for t in group_trades])
        avg_mae = np.mean([t['mae_pct'] for t in group_trades])
        
        results[label] = {
            'n_trades': len(pnls),
            'sum_pnl': total_sum,
            'avg_pnl': avg_pnl,
            'sharpe': sharpe,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_mfe': avg_mfe,
            'avg_mae': avg_mae,
            'exits': dict(exit_counts),
        }
    
    return results


def print_regime_table(results, title):
    """Pretty-print regime analysis results."""
    print(f"\n{'='*90}")
    print(f"  {title}")
    print(f"{'='*90}")
    print(f"{'Regime':<25} {'Trades':>6} {'Sum':>8} {'Avg':>7} {'Sharpe':>7} "
          f"{'WR%':>6} {'AvgW':>7} {'AvgL':>7} {'MFE':>7} {'MAE':>7}")
    print(f"{'-'*25} {'-'*6} {'-'*8} {'-'*7} {'-'*7} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")
    
    for label, r in results.items():
        print(f"{str(label):<25} {r['n_trades']:>6} {r['sum_pnl']:>+7.1f}% "
              f"{r['avg_pnl']:>+6.3f}% {r['sharpe']:>+6.2f} "
              f"{r['win_rate']:>5.1f}% {r['avg_win']:>+6.3f}% "
              f"{r['avg_loss']:>+6.3f}% {r['avg_mfe']:>+6.2f}% "
              f"{r['avg_mae']:>+6.2f}%")


def run_backtest_summary(trades):
    """Print summary statistics for a set of trades."""
    if not trades:
        print("  No trades.")
        return
    
    pnls = [t['pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    total_sum = sum(pnls)
    n = len(pnls)
    avg_pnl = np.mean(pnls)
    std_pnl = np.std(pnls)
    sharpe = avg_pnl / std_pnl * np.sqrt(n) if std_pnl > 0 else 0
    win_rate = len(wins) / n * 100
    
    total_wins = sum(wins) if wins else 0
    total_losses = abs(sum(losses)) if losses else 0
    pf = total_wins / total_losses if total_losses > 0 else float('inf')
    
    exit_counts = Counter(t['exit_reason'] for t in trades)
    
    # Compound return
    compound = 1.0
    peak = 1.0
    max_dd = 0.0
    for p in pnls:
        compound *= (1 + p / 100)
        if compound > peak:
            peak = compound
        dd = (peak - compound) / peak
        if dd > max_dd:
            max_dd = dd
    
    compound_ret = (compound - 1) * 100
    max_dd_pct = -max_dd * 100
    
    print(f"\n  Total Trades:       {n}")
    print(f"  Linear Sum:         {total_sum:+.1f}%")
    print(f"  Compound Return:    {compound_ret:+.1f}%")
    print(f"  Sharpe (per-trade): {sharpe:+.2f}")
    print(f"  Win Rate:           {win_rate:.1f}%")
    print(f"  Avg Win:            {np.mean(wins):+.3f}%" if wins else "  Avg Win:            N/A")
    print(f"  Avg Loss:           {np.mean(losses):+.3f}%" if losses else "  Avg Loss:           N/A")
    print(f"  Profit Factor:      {pf:.2f}")
    print(f"  Max Drawdown:       {max_dd_pct:.1f}%")
    print(f"\n  Exit Breakdown:")
    for reason in ['take_profit', 'stop_loss', 'time_exit']:
        count = exit_counts.get(reason, 0)
        pct = count / n * 100
        reason_trades = [t['pnl_pct'] for t in trades if t['exit_reason'] == reason]
        reason_sum = sum(reason_trades) if reason_trades else 0
        reason_avg = np.mean(reason_trades) if reason_trades else 0
        print(f"    {reason:<14} {count:>5} ({pct:>4.1f}%)  avg={reason_avg:>+6.3f}%  total={reason_sum:>+8.1f}%")


def walk_forward(df, signals_fn, regime_data, n_splits=6, **bt_kwargs):
    """Walk-forward validation with regime tagging."""
    n = len(df)
    slot = n // (n_splits + 2)
    
    results = []
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        
        # Slice everything
        df_slice = df.iloc[start:end]
        sig_slice = signals_fn(df_slice)
        regime_slice = {k: v[start:end] for k, v in regime_data.items()}
        
        trades = regime_backtest(df_slice, sig_slice, regime_slice, **bt_kwargs)
        
        if trades:
            pnls = [t['pnl_pct'] for t in trades]
            total_sum = sum(pnls)
            avg_pnl = np.mean(pnls)
            std_pnl = np.std(pnls)
            sharpe = avg_pnl / std_pnl * np.sqrt(len(pnls)) if std_pnl > 0 else 0
        else:
            total_sum = 0
            sharpe = 0
        
        period_start = df.index[start].strftime('%Y-%m')
        period_end = df.index[min(end-1, n-1)].strftime('%Y-%m')
        
        results.append({
            'split': s + 1,
            'period': f"{period_start}→{period_end}",
            'n_trades': len(trades),
            'sum': total_sum,
            'sharpe': sharpe,
        })
    
    return results


def print_walk_forward(wf_results):
    """Print walk-forward results."""
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD VALIDATION")
    print(f"{'='*70}")
    print(f"{'Split':<6} {'Period':<18} {'Trades':>6} {'Sum':>8} {'Sharpe':>8}")
    print(f"{'-'*6} {'-'*18} {'-'*6} {'-'*8} {'-'*8}")
    
    profitable = 0
    sharpes = []
    for r in wf_results:
        mark = "✅" if r['sum'] > 0 else "❌"
        if r['sum'] > 0:
            profitable += 1
        sharpes.append(r['sharpe'])
        print(f"{r['split']:<6} {r['period']:<18} {r['n_trades']:>6} "
              f"{r['sum']:>+7.1f}% {r['sharpe']:>+7.2f} {mark}")
    
    print(f"\n  OOS Profitable: {profitable}/{len(wf_results)} splits")
    print(f"  Mean OOS Sharpe: {np.mean(sharpes):+.2f}")
    print(f"  Total OOS Sum:   {sum(r['sum'] for r in wf_results):+.1f}%")


# ============================================================================
# Main Research
# ============================================================================

def main():
    print("=" * 90)
    print("  WICK INVERSION — COMPREHENSIVE REGIME ANALYSIS")
    print("  BTC/USDT 1h OKX (2019-2026)")
    print("=" * 90)
    
    # Load data
    store = OHLCVStore("data/cryptoquant.db")
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nData: {len(df)} bars, {df.index[0]} → {df.index[-1]}")
    
    # Generate signals
    strategy_cls = type('Wick', (Strategy,), {
        'timeframe': '1h',
        'min_bars': 300,
        'version': '4.3.0',
        'DEFAULT_PARAMS': {
            'imbalance_window': 6,
            'imbalance_threshold': 0.25,
            'price_lookback': 6,
            'price_floor': -0.5,
        },
        'name': property(lambda self: 'WickInversion'),
        'generate_signal': lambda self, df: (
            (wick_imbalance(df, window=self.params['imbalance_window']) > self.params['imbalance_threshold']) &
            (pct_change_rolling(df['close'], self.params['price_lookback']) > self.params['price_floor'])
        ).astype(int),
    })
    
    strategy = strategy_cls()
    signals = strategy.generate_signal(df)
    print(f"Signals: {signals.sum()} signal bars")
    
    # Compute regime data
    regime_data = compute_regime_data(df)
    
    # Run baseline backtest with regime tagging
    trades = regime_backtest(df, signals, regime_data,
                             stop_pct=3.0, target_pct=1.5, max_hold=12)
    
    print(f"\nTotal trades: {len(trades)}")
    print(f"\n--- BASELINE PERFORMANCE ---")
    run_backtest_summary(trades)
    
    # =========================================================================
    # REGIME ANALYSIS — Single dimensions
    # =========================================================================
    
    # 1. SMA200
    results = analyze_regime(trades, 'above_sma200', discrete=True)
    print_regime_table(results, "REGIME: Price vs SMA(200)")
    
    # 2. SMA50
    results = analyze_regime(trades, 'above_sma50', discrete=True)
    print_regime_table(results, "REGIME: Price vs SMA(50)")
    
    # 3. ADX strength
    results = analyze_regime(trades, 'adx',
                             bins=[15, 25, 35],
                             labels=['ADX<15 (very weak)', 'ADX 15-25 (weak)', 'ADX 25-35 (strong)', 'ADX>35 (very strong)'])
    print_regime_table(results, "REGIME: ADX (Trend Strength)")
    
    # 4. PDI vs MDI
    results = analyze_regime(trades, 'pdi_gt_mdi', discrete=True)
    print_regime_table(results, "REGIME: PDI vs MDI (Directional Movement)")
    
    # 5. Volatility ratio
    results = analyze_regime(trades, 'vol_ratio',
                             bins=[0.6, 0.8, 1.2, 1.5],
                             labels=['Very Low (<0.6)', 'Low (0.6-0.8)', 'Normal (0.8-1.2)', 'High (1.2-1.5)', 'Very High (>1.5)'])
    print_regime_table(results, "REGIME: Volatility (ATR ratio vs 200-bar median)")
    
    # 6. Recent 48h price change
    results = analyze_regime(trades, 'price_48h',
                             bins=[-5, -2, 0, 2, 5],
                             labels=['Crash (<-5%)', 'Drop (-5 to -2%)', 'Flat (-2 to 0%)', 'Mild up (0 to 2%)', 'Rally (2 to 5%)', 'Strong rally (>5%)'])
    print_regime_table(results, "REGIME: Recent 48h Price Change")
    
    # 7. Weekly trend (168h return)
    results = analyze_regime(trades, 'price_168h',
                             bins=[-15, -5, 0, 5, 15],
                             labels=['Bear (<-15%)', 'Weak bear (-15 to -5%)', 'Flat (-5 to 0%)', 'Mild bull (0 to 5%)', 'Bull (5 to 15%)', 'Strong bull (>15%)'])
    print_regime_table(results, "REGIME: Weekly Trend (168h Return)")
    
    # 8. Hour of day
    results = analyze_regime(trades, 'hour_utc', discrete=True)
    print_regime_table(results, "REGIME: Hour of Day (UTC)")
    
    # 9. Day of week
    results = analyze_regime(trades, 'day_of_week', discrete=True)
    dow_names = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday',
                 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}
    results_named = {dow_names.get(k, str(k)): v for k, v in results.items()}
    print_regime_table(results_named, "REGIME: Day of Week")
    
    # 10. RSI(14)
    results = analyze_regime(trades, 'rsi14',
                             bins=[30, 40, 50, 60, 70],
                             labels=['RSI<30 (oversold)', 'RSI 30-40', 'RSI 40-50', 'RSI 50-60', 'RSI 60-70', 'RSI>70 (overbought)'])
    print_regime_table(results, "REGIME: RSI(14)")
    
    # 11. Bollinger %B
    results = analyze_regime(trades, 'pct_b',
                             bins=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
                             labels=['%B<0 (below lower)', '%B 0-0.2', '%B 0.2-0.4', '%B 0.4-0.6', '%B 0.6-0.8', '%B 0.8-1.0', '%B>1 (above upper)'])
    print_regime_table(results, "REGIME: Bollinger %B")
    
    # 12. EMA50 vs EMA200
    results = analyze_regime(trades, 'ema_bull', discrete=True)
    print_regime_table(results, "REGIME: EMA(50) vs EMA(200)")
    
    # 13. Long-term trend (200-day return)
    results = analyze_regime(trades, 'ret_200d',
                             bins=[-50, -20, 0, 20, 50, 100],
                             labels=['Deep bear (<-50%)', 'Bear (-50 to -20%)', 'Mild bear (-20 to 0%)', 'Mild bull (0 to 20%)', 'Bull (20 to 50%)', 'Super bull (50 to 100%)', 'Mega bull (>100%)'])
    print_regime_table(results, "REGIME: 200-Day Return (Macro Trend)")
    
    # =========================================================================
    # COMBINED REGIME ANALYSIS — Find toxic combinations
    # =========================================================================
    
    print(f"\n\n{'#'*90}")
    print(f"  COMBINED REGIME ANALYSIS")
    print(f"{'#'*90}")
    
    # Define combined regimes
    combined_regimes = {
        'TOXIC: Below SMA200 + PDI<MDI': lambda t: (
            t['regime'].get('above_sma200') == False and
            t['regime'].get('pdi_gt_mdi') == False
        ),
        'TOXIC: Below SMA200 + ADX>25': lambda t: (
            t['regime'].get('above_sma200') == False and
            t['regime'].get('adx', 0) > 25
        ),
        'TOXIC: Below SMA200 + 48h<-2%': lambda t: (
            t['regime'].get('above_sma200') == False and
            (t['regime'].get('price_48h') or 0) < -2
        ),
        'GOOD: Above SMA200 + PDI>MDI': lambda t: (
            t['regime'].get('above_sma200') == True and
            t['regime'].get('pdi_gt_mdi') == True
        ),
        'GOOD: Above SMA200 + ADX>25': lambda t: (
            t['regime'].get('above_sma200') == True and
            t['regime'].get('adx', 0) > 25
        ),
        'GOOD: Above SMA200 + 48h>0%': lambda t: (
            t['regime'].get('above_sma200') == True and
            (t['regime'].get('price_48h') or 0) > 0
        ),
        'MIXED: Below SMA200 + PDI>MDI': lambda t: (
            t['regime'].get('above_sma200') == False and
            t['regime'].get('pdi_gt_mdi') == True
        ),
        'MIXED: Above SMA200 + PDI<MDI': lambda t: (
            t['regime'].get('above_sma200') == True and
            t['regime'].get('pdi_gt_mdi') == False
        ),
    }
    
    print(f"\n{'='*90}")
    print(f"  COMBINED REGIME PERFORMANCE")
    print(f"{'='*90}")
    print(f"{'Regime':<45} {'Trades':>6} {'Sum':>8} {'Avg':>7} {'Sharpe':>7} "
          f"{'WR%':>6} {'PF':>5} {'StopR':>6}")
    print(f"{'-'*45} {'-'*6} {'-'*8} {'-'*7} {'-'*7} {'-'*6} {'-'*5} {'-'*6}")
    
    for regime_name, condition_fn in combined_regimes.items():
        subset = [t for t in trades if condition_fn(t)]
        if not subset:
            continue
        
        pnls = [t['pnl_pct'] for t in subset]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        total_sum = sum(pnls)
        avg_pnl = np.mean(pnls)
        std_pnl = np.std(pnls)
        sharpe = avg_pnl / std_pnl * np.sqrt(len(pnls)) if std_pnl > 0 else 0
        win_rate = len(wins) / len(pnls) * 100
        
        total_w = sum(wins) if wins else 0
        total_l = abs(sum(losses)) if losses else 0
        pf = total_w / total_l if total_l > 0 else float('inf')
        
        stop_count = sum(1 for t in subset if t['exit_reason'] == 'stop_loss')
        stop_rate = stop_count / len(subset) * 100
        
        print(f"{regime_name:<45} {len(subset):>6} {total_sum:>+7.1f}% "
              f"{avg_pnl:>+6.3f}% {sharpe:>+6.2f} {win_rate:>5.1f}% "
              f"{pf:>5.2f} {stop_rate:>5.1f}%")
    
    # =========================================================================
    # FILTER TESTING — Based on regime findings
    # =========================================================================
    
    print(f"\n\n{'#'*90}")
    print(f"  FILTER TESTING")
    print(f"{'#'*90}")
    
    # Define filter functions
    filters = {
        'Baseline (no filter)': lambda t: True,
        'SMA200 only': lambda t: t['regime'].get('above_sma200') == True,
        'PDI>MDI only': lambda t: t['regime'].get('pdi_gt_mdi') == True,
        'ADX>25 only': lambda t: (t['regime'].get('adx', 0) or 0) > 25,
        'SMA200 + PDI>MDI': lambda t: (
            t['regime'].get('above_sma200') == True and
            t['regime'].get('pdi_gt_mdi') == True
        ),
        'SMA200 + ADX>25': lambda t: (
            t['regime'].get('above_sma200') == True and
            (t['regime'].get('adx', 0) or 0) > 25
        ),
        'NOT (below SMA200 + PDI<MDI)': lambda t: not (
            t['regime'].get('above_sma200') == False and
            t['regime'].get('pdi_gt_mdi') == False
        ),
        'NOT (below SMA200 + ADX>25)': lambda t: not (
            t['regime'].get('above_sma200') == False and
            (t['regime'].get('adx', 0) or 0) > 25
        ),
        '48h > -2%': lambda t: (t['regime'].get('price_48h') or 0) > -2,
        '48h > 0%': lambda t: (t['regime'].get('price_48h') or 0) > 0,
        'SMA200 + 48h>-2%': lambda t: (
            t['regime'].get('above_sma200') == True and
            (t['regime'].get('price_48h') or 0) > -2
        ),
        'EMA bull (EMA50>EMA200)': lambda t: t['regime'].get('ema_bull') == True,
        'Vol ratio 0.8-1.5': lambda t: 0.8 <= (t['regime'].get('vol_ratio') or 1) <= 1.5,
        'RSI 30-70': lambda t: 30 <= (t['regime'].get('rsi14') or 50) <= 70,
        'RSI < 60': lambda t: (t['regime'].get('rsi14') or 50) < 60,
    }
    
    print(f"\n{'='*100}")
    print(f"  FILTER COMPARISON (post-hoc filtering of trades)")
    print(f"{'='*100}")
    print(f"{'Filter':<35} {'Trades':>6} {'Sum':>8} {'Avg':>7} {'Sharpe':>7} "
          f"{'WR%':>6} {'PF':>5} {'MaxDD':>7} {'StopR':>6} {'Cmpd':>8}")
    print(f"{'-'*35} {'-'*6} {'-'*8} {'-'*7} {'-'*7} {'-'*6} {'-'*5} {'-'*7} {'-'*6} {'-'*8}")
    
    for filter_name, filter_fn in filters.items():
        subset = [t for t in trades if filter_fn(t)]
        if not subset:
            continue
        
        pnls = [t['pnl_pct'] for t in subset]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        total_sum = sum(pnls)
        avg_pnl = np.mean(pnls)
        std_pnl = np.std(pnls)
        sharpe = avg_pnl / std_pnl * np.sqrt(len(pnls)) if std_pnl > 0 else 0
        win_rate = len(wins) / len(pnls) * 100
        
        total_w = sum(wins) if wins else 0
        total_l = abs(sum(losses)) if losses else 0
        pf = total_w / total_l if total_l > 0 else float('inf')
        
        stop_count = sum(1 for t in subset if t['exit_reason'] == 'stop_loss')
        stop_rate = stop_count / len(subset) * 100
        
        # Compound return + max DD
        compound = 1.0
        peak = 1.0
        max_dd = 0.0
        for p in pnls:
            compound *= (1 + p / 100)
            if compound > peak:
                peak = compound
            dd = (peak - compound) / peak
            if dd > max_dd:
                max_dd = dd
        
        compound_ret = (compound - 1) * 100
        max_dd_pct = -max_dd * 100
        
        print(f"{filter_name:<35} {len(subset):>6} {total_sum:>+7.1f}% "
              f"{avg_pnl:>+6.3f}% {sharpe:>+6.2f} {win_rate:>5.1f}% "
              f"{pf:>5.2f} {max_dd_pct:>6.1f}% {stop_rate:>5.1f}% "
              f"{compound_ret:>+7.1f}%")
    
    # =========================================================================
    # WALK-FORWARD VALIDATION of most promising filters
    # =========================================================================
    
    print(f"\n\n{'#'*90}")
    print(f"  WALK-FORWARD VALIDATION")
    print(f"{'#'*90}")
    
    # We need a function that generates signals with filter applied
    def make_signals_fn(filter_name):
        """Create a signal generation function with regime filter."""
        def fn(df_slice):
            # Generate raw signals
            imb = wick_imbalance(df_slice, window=6)
            price_chg = pct_change_rolling(df_slice["close"], 6)
            raw_signal = ((imb > 0.25) & (price_chg > -0.5)).astype(int)
            
            if filter_name == 'Baseline (no filter)':
                return raw_signal
            
            # Compute regime data for this slice
            rd = compute_regime_data(df_slice)
            
            # Apply filter
            filtered = raw_signal.copy()
            for idx in range(len(df_slice)):
                if raw_signal.iloc[idx] == 1:
                    # Check if this bar passes the filter
                    regime_at_bar = {k: v[idx] for k, v in rd.items()}
                    
                    if filter_name == 'SMA200 only':
                        if not regime_at_bar.get('above_sma200', False):
                            filtered.iloc[idx] = 0
                    elif filter_name == 'PDI>MDI only':
                        if not regime_at_bar.get('pdi_gt_mdi', False):
                            filtered.iloc[idx] = 0
                    elif filter_name == 'SMA200 + PDI>MDI':
                        if not (regime_at_bar.get('above_sma200', False) and
                                regime_at_bar.get('pdi_gt_mdi', False)):
                            filtered.iloc[idx] = 0
                    elif filter_name == 'NOT (below SMA200 + PDI<MDI)':
                        if (regime_at_bar.get('above_sma200') == False and
                            regime_at_bar.get('pdi_gt_mdi') == False):
                            filtered.iloc[idx] = 0
                    elif filter_name == '48h > -2%':
                        if (regime_at_bar.get('price_48h', 0) or 0) <= -2:
                            filtered.iloc[idx] = 0
                    elif filter_name == 'EMA bull (EMA50>EMA200)':
                        if not regime_at_bar.get('ema_bull', False):
                            filtered.iloc[idx] = 0
            
            return filtered
        return fn
    
    # Test walk-forward for top filters
    top_filters = [
        'Baseline (no filter)',
        'SMA200 only',
        'PDI>MDI only',
        'SMA200 + PDI>MDI',
        'NOT (below SMA200 + PDI<MDI)',
        '48h > -2%',
        'EMA bull (EMA50>EMA200)',
    ]
    
    for filter_name in top_filters:
        print(f"\n--- Walk-Forward: {filter_name} ---")
        signals_fn = make_signals_fn(filter_name)
        
        # For walk-forward, we need to pass the full-df regime data sliced
        # Actually, let's do it differently - compute regime on each slice
        n = len(df)
        n_splits = 6
        slot = n // (n_splits + 2)
        
        wf_results = []
        for s in range(n_splits):
            start = n - (n_splits - s + 1) * slot
            end = min(n, start + slot)
            
            df_slice = df.iloc[start:end].copy()
            
            # Generate signals with filter on this slice
            sig = signals_fn(df_slice)
            
            # Compute regime on this slice
            rd_slice = compute_regime_data(df_slice)
            
            # Run backtest
            slice_trades = regime_backtest(df_slice, sig, rd_slice,
                                           stop_pct=3.0, target_pct=1.5, max_hold=12)
            
            if slice_trades:
                pnls = [t['pnl_pct'] for t in slice_trades]
                total_sum = sum(pnls)
                avg_pnl = np.mean(pnls)
                std_pnl = np.std(pnls)
                sharpe = avg_pnl / std_pnl * np.sqrt(len(pnls)) if std_pnl > 0 else 0
            else:
                total_sum = 0
                sharpe = 0
            
            period_start = df.index[start].strftime('%Y-%m')
            period_end = df.index[min(end-1, n-1)].strftime('%Y-%m')
            
            wf_results.append({
                'split': s + 1,
                'period': f"{period_start}→{period_end}",
                'n_trades': len(slice_trades),
                'sum': total_sum,
                'sharpe': sharpe,
            })
        
        print_walk_forward(wf_results)
    
    # =========================================================================
    # EXIT OPTIMIZATION — For the best filter
    # =========================================================================
    
    print(f"\n\n{'#'*90}")
    print(f"  EXIT OPTIMIZATION (target sweep)")
    print(f"{'#'*90}")
    
    # Test different targets with the best filter
    # First, determine best filter from the analysis above
    # We'll test a few promising ones
    
    for filter_name in ['Baseline (no filter)', 'SMA200 only', 'NOT (below SMA200 + PDI<MDI)']:
        print(f"\n--- Target Sweep: {filter_name} ---")
        print(f"{'Target':>8} {'Hold':>5} {'Stop':>5} {'Trades':>6} {'Sum':>8} "
              f"{'Sharpe':>7} {'WR%':>6} {'PF':>5} {'MaxDD':>7}")
        print(f"{'-'*8} {'-'*5} {'-'*5} {'-'*6} {'-'*8} {'-'*7} {'-'*6} {'-'*5} {'-'*7}")
        
        signals_fn = make_signals_fn(filter_name)
        filtered_signals = signals_fn(df)
        rd = compute_regime_data(df)
        
        for target in [0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0]:
            for hold in [6, 8, 12]:
                for stop in [2.0, 2.5, 3.0]:
                    t_trades = regime_backtest(df, filtered_signals, rd,
                                               stop_pct=stop, target_pct=target, max_hold=hold)
                    if not t_trades:
                        continue
                    
                    pnls = [t['pnl_pct'] for t in t_trades]
                    wins = [p for p in pnls if p > 0]
                    losses = [p for p in pnls if p <= 0]
                    
                    total_sum = sum(pnls)
                    avg_pnl = np.mean(pnls)
                    std_pnl = np.std(pnls)
                    sharpe = avg_pnl / std_pnl * np.sqrt(len(pnls)) if std_pnl > 0 else 0
                    win_rate = len(wins) / len(pnls) * 100
                    
                    total_w = sum(wins) if wins else 0
                    total_l = abs(sum(losses)) if losses else 0
                    pf = total_w / total_l if total_l > 0 else float('inf')
                    
                    compound = 1.0
                    peak = 1.0
                    max_dd = 0.0
                    for p in pnls:
                        compound *= (1 + p / 100)
                        if compound > peak:
                            peak = compound
                        dd = (peak - compound) / peak
                        if dd > max_dd:
                            max_dd = dd
                    max_dd_pct = -max_dd * 100
                    
                    if sharpe > 0.5:  # Only print promising combos
                        print(f"{target:>7.1f}% {hold:>5} {stop:>4.1f}% "
                              f"{len(t_trades):>6} {total_sum:>+7.1f}% "
                              f"{sharpe:>+6.2f} {win_rate:>5.1f}% "
                              f"{pf:>5.2f} {max_dd_pct:>6.1f}%")
    
    # =========================================================================
    # BINANCE CROSS-VALIDATION for best config
    # =========================================================================
    
    print(f"\n\n{'#'*90}")
    print(f"  BINANCE CROSS-VALIDATION")
    print(f"{'#'*90}")
    
    df_bn = store.load("binance", "BTC/USDT", "1h")
    if not df_bn.empty:
        print(f"\nBinance data: {len(df_bn)} bars, {df_bn.index[0]} → {df_bn.index[-1]}")
        
        # Generate signals
        imb_bn = wick_imbalance(df_bn, window=6)
        price_chg_bn = pct_change_rolling(df_bn["close"], 6)
        signals_bn = ((imb_bn > 0.25) & (price_chg_bn > -0.5)).astype(int)
        
        # Compute regime
        rd_bn = compute_regime_data(df_bn)
        
        # Test baseline and best filters
        for filter_name in ['Baseline (no filter)', 'SMA200 only', 'NOT (below SMA200 + PDI<MDI)']:
            signals_fn = make_signals_fn(filter_name)
            filtered_sig = signals_fn(df_bn)
            
            bn_trades = regime_backtest(df_bn, filtered_sig, rd_bn,
                                        stop_pct=3.0, target_pct=1.5, max_hold=12)
            
            print(f"\n--- Binance: {filter_name} ---")
            run_backtest_summary(bn_trades)
    else:
        print("No Binance data available for cross-validation.")
    
    print(f"\n\n{'='*90}")
    print(f"  RESEARCH COMPLETE")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()
