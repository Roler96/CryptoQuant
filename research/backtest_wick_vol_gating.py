"""
Wick Inversion — Volatility Gating & Dynamic Threshold Research
================================================================

Research direction (from literature_review_v1):
1. Volatility gating: Ślepaczuk (2606.09478) shows low-vol gating improves defensive performance
2. Dynamic imbalance threshold: Ślepaczuk (2606.00060) shows cost-aware filters restore profitability
3. Counterfactual rejection tracking: Kamat (2606.08228) — track what filtered signals would have done
4. Cooldown after stop-loss: turnover control from Ślepaczuk papers

Methodology:
1. Run baseline backtest with regime tagging (existing infrastructure)
2. Test volatility gating at multiple threshold levels
3. Walk-forward validate best vol gate configuration
4. Test dynamic imbalance threshold (vol-adjusted)
5. Test cooldown after stop-loss
6. Counterfactual tracking: for each filtered-out signal, check forward return
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
# Reuse existing infrastructure from backtest_wick_regime_analysis.py
# ============================================================================

def regime_backtest(df, signals, regime_data, stop_pct=3.0, target_pct=1.5,
                    max_hold=12, commission=0.0005, slippage=0.0005):
    """Run backtest and tag each trade with regime data at entry time."""
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    trades = []
    position = None
    pending_signal = False

    for i in range(n):
        if position is None and pending_signal:
            entry_price = opens[i]
            entry_idx = i
            stop_price = entry_price * (1 - stop_pct / 100)
            target_price = entry_price * (1 + target_pct / 100)

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

        if position is not None:
            exit_reason = None
            exit_price = None

            if lows[i] <= position['stop_price']:
                exit_reason = 'stop_loss'
                exit_price = position['stop_price'] * (1 - slippage)
            elif highs[i] >= position['target_price']:
                exit_reason = 'take_profit'
                exit_price = position['target_price'] * (1 - slippage)
            elif (i - position['entry_idx']) >= max_hold:
                exit_reason = 'time_exit'
                exit_price = opens[i] * (1 - slippage)

            if exit_reason:
                pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                pnl_pct -= commission * 100  # round-trip commission

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

        if position is None and not pending_signal:
            if signals.iloc[i] == 1:
                pending_signal = True

    return trades


def compute_regime_data(df):
    """Compute all regime indicators for the DataFrame."""
    closes = df["close"]

    sma200 = sma(closes, 200)
    above_sma200 = (closes > sma200).values

    sma50 = sma(closes, 50)
    above_sma50 = (closes > sma50).values

    adx_data = adx_func(df, period=14)
    adx_vals = adx_data["adx"].values
    pdi_vals = adx_data["pdi"].values
    mdi_vals = adx_data["mdi"].values
    pdi_gt_mdi = (pdi_vals > mdi_vals)

    atr14 = atr_func(df, 14)
    median_atr = atr14.rolling(200).median()
    vol_ratio = (atr14 / median_atr).values

    price_48h = pct_change_rolling(closes, 48).values
    price_168h = pct_change_rolling(closes, 168).values

    hours = df.index.hour.values
    dow = df.index.dayofweek.values
    ret_200d = pct_change_rolling(closes, 4800).values
    rsi14 = rsi(closes, 14).values

    bb_mid = sma(closes, 20)
    bb_std = closes.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    pct_b = ((closes - bb_lower) / (bb_upper - bb_lower)).values

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


def run_backtest_summary(trades):
    """Print summary statistics for a set of trades."""
    if not trades:
        print("  No trades.")
        return None

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

    # Consecutive losses
    consec = 0
    max_consec = 0
    for p in pnls:
        if p <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    print(f"\n  Total Trades:       {n}")
    print(f"  Linear Sum:         {total_sum:+.1f}%")
    print(f"  Compound Return:    {compound_ret:+.1f}%")
    print(f"  Sharpe (per-trade): {sharpe:+.2f}")
    print(f"  Win Rate:           {win_rate:.1f}%")
    print(f"  Avg Win:            {np.mean(wins):+.3f}%" if wins else "  Avg Win:            N/A")
    print(f"  Avg Loss:           {np.mean(losses):+.3f}%" if losses else "  Avg Loss:           N/A")
    print(f"  Profit Factor:      {pf:.2f}")
    print(f"  Max Drawdown:       {max_dd_pct:.1f}%")
    print(f"  Max Consec Losses:  {max_consec}")
    print(f"\n  Exit Breakdown:")
    for reason in ['take_profit', 'stop_loss', 'time_exit']:
        count = exit_counts.get(reason, 0)
        pct = count / n * 100
        reason_trades = [t['pnl_pct'] for t in trades if t['exit_reason'] == reason]
        reason_sum = sum(reason_trades) if reason_trades else 0
        reason_avg = np.mean(reason_trades) if reason_trades else 0
        print(f"    {reason:<14} {count:>5} ({pct:>4.1f}%)  avg={reason_avg:>+6.3f}%  total={reason_sum:>+8.1f}%")

    return {
        'n': n, 'sum': total_sum, 'sharpe': sharpe, 'win_rate': win_rate,
        'pf': pf, 'max_dd': max_dd_pct, 'compound': compound_ret,
        'max_consec': max_consec, 'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': np.mean(losses) if losses else 0,
    }


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


def walk_forward_sweep(df, regime_data, make_signals_fn, n_splits=6, **bt_kwargs):
    """Walk-forward validation."""
    n = len(df)
    slot = n // (n_splits + 2)

    results = []
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)

        df_slice = df.iloc[start:end]
        sig_slice = make_signals_fn(df_slice)
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


# ============================================================================
# EXPERIMENT 1: Volatility Gating
# ============================================================================

def experiment_vol_gating(df, regime_data):
    """Test volatility gating at various ATR ratio thresholds."""
    print(f"\n{'#'*90}")
    print(f"  EXPERIMENT 1: VOLATILITY GATING")
    print(f"{'#'*90}")

    closes = df["close"]

    # Generate base signals
    imb = wick_imbalance(df, window=6)
    price_chg = pct_change_rolling(closes, 6)
    base_signal = ((imb > 0.25) & (price_chg > -0.5)).astype(int)

    n_bars = len(df)
    n_base_signals = base_signal.sum()

    # Test vol gate ranges
    vol_ratio = regime_data['vol_ratio']

    configs = []
    for vol_min in [0.0, 0.6, 0.8, 1.0]:
        for vol_max in [1.2, 1.5, 2.0, 10.0]:
            # Generate gated signals
            gated = base_signal.copy()
            vol_ok = (vol_ratio > vol_min) & (vol_ratio < vol_max)
            gated = (gated.astype(bool) & vol_ok).astype(int)

            trades = regime_backtest(df, gated, regime_data,
                                     stop_pct=3.0, target_pct=1.5, max_hold=12)
            if not trades:
                continue

            stats = run_backtest_summary(trades)
            if stats is None:
                continue

            configs.append({
                'vol_min': vol_min, 'vol_max': vol_max,
                'n_signals': gated.sum(), 'pct_kept': gated.sum() / n_base_signals * 100 if n_base_signals else 0,
                **stats,
            })

    # Print results table
    print(f"\n  Volatility Gate Sweep (ATR ratio vs 200-bar median):")
    print(f"  Base signals: {n_base_signals}")
    print(f"  {'Vol Min':>8} {'Vol Max':>8} {'Signals':>7} {'Kept%':>6} "
          f"{'Trades':>6} {'Sum':>8} {'Sharpe':>7} {'WR%':>6} {'PF':>5} {'MaxDD':>7} {'Cmpd':>8} {'MCns':>5}")
    print(f"  {'-'*8} {'-'*8} {'-'*7} {'-'*6} {'-'*6} {'-'*8} {'-'*7} {'-'*6} {'-'*5} {'-'*7} {'-'*8} {'-'*5}")

    # Sort by Sharpe descending
    configs.sort(key=lambda x: x['sharpe'], reverse=True)

    for c in configs:
        vol_range = f"{c['vol_max']:.1f}" if c['vol_max'] < 10 else "∞"
        print(f"  {c['vol_min']:>7.1f}  {vol_range:>8} {c['n_signals']:>7} {c['pct_kept']:>5.1f}% "
              f"{c['n']:>6} {c['sum']:>+7.1f}% {c['sharpe']:>+6.2f} {c['win_rate']:>5.1f}% "
              f"{c['pf']:>5.2f} {c['max_dd']:>6.1f}% {c['compound']:>+7.1f}% {c['max_consec']:>5}")

    return configs


# ============================================================================
# EXPERIMENT 2: Dynamic Imbalance Threshold
# ============================================================================

def experiment_dynamic_threshold(df, regime_data):
    """Test dynamic imbalance threshold: higher threshold in high vol."""
    print(f"\n{'#'*90}")
    print(f"  EXPERIMENT 2: DYNAMIC IMBALANCE THRESHOLD")
    print(f"{'#'*90}")

    closes = df["close"]
    vol_ratio = regime_data['vol_ratio']
    imb = wick_imbalance(df, window=6)
    price_chg = pct_change_rolling(closes, 6)

    # Baseline signal
    base_ok = price_chg > -0.5

    print(f"\n  Dynamic threshold = base_threshold + vol_penalty * (vol_ratio - 1.0)")
    print(f"  {'Base Thr':>9} {'Vol Penalty':>11} {'Signals':>7} "
          f"{'Trades':>6} {'Sum':>8} {'Sharpe':>7} {'WR%':>6} {'PF':>5} {'MaxDD':>7} {'Cmpd':>8}")

    configs = []
    for base_thr in [0.20, 0.25, 0.30]:
        for vol_penalty in [0.00, 0.03, 0.05, 0.08, 0.10]:
            dynamic_threshold = base_thr + vol_penalty * np.maximum(vol_ratio - 1.0, 0)
            # But never go below base_thr
            dynamic_threshold = np.maximum(dynamic_threshold, base_thr)

            signal = (imb.values > dynamic_threshold) & base_ok.values
            sig_series = pd.Series(signal.astype(int), index=df.index)

            trades = regime_backtest(df, sig_series, regime_data,
                                     stop_pct=3.0, target_pct=1.5, max_hold=12)
            if not trades:
                continue

            stats = run_backtest_summary(trades)
            if stats is None:
                continue

            configs.append({
                'base_thr': base_thr, 'vol_penalty': vol_penalty,
                'n_signals': sig_series.sum(), **stats,
            })

    configs.sort(key=lambda x: x['sharpe'], reverse=True)

    for c in configs:
        print(f"  {c['base_thr']:>9.2f} {c['vol_penalty']:>11.2f} {c['n_signals']:>7} "
              f"{c['n']:>6} {c['sum']:>+7.1f}% {c['sharpe']:>+6.2f} {c['win_rate']:>5.1f}% "
              f"{c['pf']:>5.2f} {c['max_dd']:>6.1f}% {c['compound']:>+7.1f}%")

    return configs


# ============================================================================
# EXPERIMENT 3: Cooldown After Stop-Loss
# ============================================================================

def experiment_cooldown(df, regime_data):
    """Test cooldown period after stop-loss exits."""
    print(f"\n{'#'*90}")
    print(f"  EXPERIMENT 3: COOLDOWN AFTER STOP-LOSS")
    print(f"{'#'*90}")

    closes = df["close"]
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    imb = wick_imbalance(df, window=6)
    price_chg = pct_change_rolling(closes, 6)
    base_signal = ((imb > 0.25) & (price_chg > -0.5)).astype(int)

    print(f"\n  Cooldown period after stop-loss (bars):")
    print(f"  {'Cooldown':>9} {'Trades':>6} {'Sum':>8} {'Sharpe':>7} {'WR%':>6} "
          f"{'PF':>5} {'MaxDD':>7} {'Cmpd':>8} {'MCns':>5}")

    configs = []
    for cooldown_bars in [0, 3, 6, 12, 24]:
        signals = base_signal.copy().values
        last_stop_idx = -999

        for i in range(n):
            if signals[i] == 1 and (i - last_stop_idx) < cooldown_bars:
                signals[i] = 0

        sig_series = pd.Series(signals, index=df.index)

        # Run backtest with cooldown tracking
        trades = []
        position = None
        pending_signal = False
        last_stop_idx = -999

        for i in range(n):
            if position is None and pending_signal:
                entry_price = opens[i]
                entry_idx = i
                stop_price = entry_price * (1 - 3.0 / 100)
                target_price = entry_price * (1 + 1.5 / 100)

                entry_regime = {}
                for key, arr in regime_data.items():
                    entry_regime[key] = arr[i] if i < len(arr) else None

                position = {
                    'entry_price': entry_price, 'entry_idx': entry_idx,
                    'stop_price': stop_price, 'target_price': target_price,
                    'regime': entry_regime,
                }
                pending_signal = False

            if position is not None:
                exit_reason = None
                exit_price = None

                if lows[i] <= position['stop_price']:
                    exit_reason = 'stop_loss'
                    exit_price = position['stop_price'] * (1 - 0.0005)
                    last_stop_idx = i
                elif highs[i] >= position['target_price']:
                    exit_reason = 'take_profit'
                    exit_price = position['target_price'] * (1 - 0.0005)
                elif (i - position['entry_idx']) >= 12:
                    exit_reason = 'time_exit'
                    exit_price = opens[i] * (1 - 0.0005)

                if exit_reason:
                    pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                    trades.append({
                        'entry_idx': position['entry_idx'], 'exit_idx': i,
                        'entry_price': position['entry_price'], 'exit_price': exit_price,
                        'pnl_pct': pnl_pct, 'exit_reason': exit_reason,
                        'mfe_pct': 0, 'mae_pct': 0, 'hold_bars': i - position['entry_idx'],
                        'regime': position['regime'],
                        'entry_time': df.index[position['entry_idx']],
                        'exit_time': df.index[i],
                    })
                    position = None

            if position is None and not pending_signal:
                if signals[i] == 1 and (i - last_stop_idx) >= cooldown_bars:
                    pending_signal = True

        if not trades:
            continue

        stats = run_backtest_summary(trades)
        if stats is None:
            continue

        configs.append({'cooldown': cooldown_bars, **stats})

    configs.sort(key=lambda x: x['sharpe'], reverse=True)

    for c in configs:
        print(f"  {c['cooldown']:>9} {c['n']:>6} {c['sum']:>+7.1f}% {c['sharpe']:>+6.2f} "
              f"{c['win_rate']:>5.1f}% {c['pf']:>5.2f} {c['max_dd']:>6.1f}% "
              f"{c['compound']:>+7.1f}% {c['max_consec']:>5}")

    return configs


# ============================================================================
# EXPERIMENT 4: Counterfactual Rejection Tracking
# ============================================================================

def experiment_counterfactual(df, regime_data):
    """Track what happens to signals that are filtered out."""
    print(f"\n{'#'*90}")
    print(f"  EXPERIMENT 4: COUNTERFACTUAL REJECTION TRACKING")
    print(f"{'#'*90}")

    closes = df["close"]
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    imb = wick_imbalance(df, window=6)
    price_chg = pct_change_rolling(closes, 6)

    # Baseline: raw signal
    base_signal = ((imb > 0.25) & (price_chg > -0.5)).astype(int)

    # Get signal bar indices
    raw_signal_idxs = [i for i in range(n) if base_signal.iloc[i] == 1]

    # Filters to test
    filters = {
        'SMA200': lambda rd_i: rd_i.get('above_sma200') == True,
        'PDI>MDI': lambda rd_i: rd_i.get('pdi_gt_mdi') == True,
        'SMA200+PDI>MDI': lambda rd_i: (
            rd_i.get('above_sma200') == True and rd_i.get('pdi_gt_mdi') == True
        ),
        '48h>-2%': lambda rd_i: (rd_i.get('price_48h') or 0) > -2,
        'Vol 0.8-1.5': lambda rd_i: 0.8 <= (rd_i.get('vol_ratio') or 1) <= 1.5,
        'RSI 50-70': lambda rd_i: 50 <= (rd_i.get('rsi14') or 50) <= 70,
    }

    print(f"\n  For each filter: accepted signals → traded, rejected signals → tracked forward 12 bars")
    print(f"  {'Filter':<20} {'Accepted':>8} {'Rejected':>8} "
          f"{'Acc.Sum':>8} {'Rej.Sum':>8} {'Acc.Sharpe':>10} {'Rej.Sharpe':>10} {'Verdict':>12}")
    print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*12}")

    for filter_name, filter_fn in filters.items():
        accepted_idxs = []
        rejected_idxs = []

        for idx in raw_signal_idxs:
            rd_i = {k: v[idx] for k, v in regime_data.items()}
            if filter_fn(rd_i):
                accepted_idxs.append(idx)
            else:
                rejected_idxs.append(idx)

        # Accepted: run actual backtest
        acc_signal = pd.Series(0, index=df.index)
        for idx in accepted_idxs:
            acc_signal.iloc[idx] = 1
        acc_trades = regime_backtest(df, acc_signal, regime_data,
                                     stop_pct=3.0, target_pct=1.5, max_hold=12)

        if acc_trades:
            acc_pnls = [t['pnl_pct'] for t in acc_trades]
            acc_sum = sum(acc_pnls)
            acc_avg = np.mean(acc_pnls)
            acc_std = np.std(acc_pnls)
            acc_sharpe = acc_avg / acc_std * np.sqrt(len(acc_pnls)) if acc_std > 0 else 0
        else:
            acc_sum = 0
            acc_sharpe = 0

        # Rejected: simulate "if we had entered at next open, what would 12h forward return be?"
        rej_returns = []
        for idx in rejected_idxs:
            if idx + 1 >= n:
                continue
            entry = opens[idx + 1]
            exit_idx = min(idx + 1 + 12, n - 1)
            exit_price = closes.iloc[exit_idx]
            ret = (exit_price / entry - 1) * 100
            rej_returns.append(ret)

        if rej_returns:
            rej_sum = sum(rej_returns)
            rej_avg = np.mean(rej_returns)
            rej_std = np.std(rej_returns)
            rej_sharpe = rej_avg / rej_std * np.sqrt(len(rej_returns)) if rej_std > 0 else 0
        else:
            rej_sum = 0
            rej_sharpe = 0

        # Verdict
        if rej_sharpe < 0:
            verdict = "✅ FILTER GOOD"
        elif rej_sharpe < 0.3 and rej_sum < 0:
            verdict = "✅ FILTER GOOD"
        elif acc_sharpe > rej_sharpe * 2:
            verdict = "✅ FILTER GOOD"
        else:
            verdict = "⚠️ CHECK FILTER"

        print(f"  {filter_name:<20} {len(accepted_idxs):>8} {len(rejected_idxs):>8} "
              f"{acc_sum:>+7.1f}% {rej_sum:>+7.1f}% "
              f"{acc_sharpe:>+9.2f} {rej_sharpe:>+9.2f} {verdict:>12}")


# ============================================================================
# EXPERIMENT 5: Combined Best Configuration Walk-Forward
# ============================================================================

def experiment_combined_wf(df, regime_data, best_vol_min, best_vol_max):
    """Walk-forward validate the best combined configuration."""
    print(f"\n{'#'*90}")
    print(f"  EXPERIMENT 5: WALK-FORWARD — COMBINED BEST CONFIG")
    print(f"{'#'*90}")

    closes = df["close"]
    vol_ratio = regime_data['vol_ratio']

    def make_signals_wf(df_slice):
        imb = wick_imbalance(df_slice, window=6)
        price_chg = pct_change_rolling(df_slice["close"], 6)

        # Raw signal
        raw = ((imb > 0.25) & (price_chg > -0.5)).astype(int)

        # Vol gating
        rd_slice = compute_regime_data(df_slice)
        vol_r = rd_slice['vol_ratio']
        vol_ok = (vol_r > best_vol_min) & (vol_r < best_vol_max)

        # SMA200 filter
        sma200_ok = rd_slice['above_sma200']

        gated = raw.copy()
        for idx in range(len(df_slice)):
            if raw.iloc[idx] == 1:
                if not (vol_ok[idx] and sma200_ok[idx]):
                    gated.iloc[idx] = 0

        return gated

    n = len(df)
    n_splits = 6
    slot = n // (n_splits + 2)

    # Also do baseline for comparison
    def make_baseline_wf(df_slice):
        imb = wick_imbalance(df_slice, window=6)
        price_chg = pct_change_rolling(df_slice["close"], 6)
        return ((imb > 0.25) & (price_chg > -0.5)).astype(int)

    print(f"\n  Comparing: Baseline vs Vol Gate [{best_vol_min}-{best_vol_max}] + SMA200")

    for label, signals_fn in [
        ('Baseline (no filter)', make_baseline_wf),
        (f'Vol[{best_vol_min}-{best_vol_max}]+SMA200', make_signals_wf),
    ]:
        print(f"\n--- {label} ---")
        wf = walk_forward_sweep(df, regime_data, signals_fn, n_splits=6,
                                stop_pct=3.0, target_pct=1.5, max_hold=12)
        print_walk_forward(wf)


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 90)
    print("  WICK INVERSION — VOL GATING & DYNAMIC THRESHOLD RESEARCH")
    print("  BTC/USDT 1h OKX (2019-2026)")
    print("=" * 90)

    # Load data
    store = OHLCVStore("data/cryptoquant.db")
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nData: {len(df)} bars, {df.index[0]} → {df.index[-1]}")

    # Compute regime data once
    regime_data = compute_regime_data(df)

    # Run baseline
    imb = wick_imbalance(df, window=6)
    price_chg = pct_change_rolling(df["close"], 6)
    base_signal = ((imb > 0.25) & (price_chg > -0.5)).astype(int)
    base_trades = regime_backtest(df, base_signal, regime_data,
                                  stop_pct=3.0, target_pct=1.5, max_hold=12)

    print(f"\n--- BASELINE ---")
    run_backtest_summary(base_trades)

    # Experiment 1: Volatility Gating
    vol_configs = experiment_vol_gating(df, regime_data)

    # Experiment 2: Dynamic Threshold
    dyn_configs = experiment_dynamic_threshold(df, regime_data)

    # Experiment 3: Cooldown
    cool_configs = experiment_cooldown(df, regime_data)

    # Experiment 4: Counterfactual
    experiment_counterfactual(df, regime_data)

    # Experiment 5: Walk-forward best combined
    if vol_configs:
        best_vol = vol_configs[0]
        experiment_combined_wf(df, regime_data, best_vol['vol_min'], best_vol['vol_max'])

    # Summary
    print(f"\n\n{'='*90}")
    print(f"  RESEARCH COMPLETE")
    print(f"{'='*90}")
    print(f"\n  Best Vol Gate:    min={vol_configs[0]['vol_min']:.1f}, max={vol_configs[0]['vol_max']:.1f}"
          f" → Sharpe {vol_configs[0]['sharpe']:+.2f}, MaxDD {vol_configs[0]['max_dd']:.1f}%")
    if dyn_configs:
        print(f"  Best Dyn Thr:     base={dyn_configs[0]['base_thr']:.2f}, penalty={dyn_configs[0]['vol_penalty']:.2f}"
              f" → Sharpe {dyn_configs[0]['sharpe']:+.2f}")
    if cool_configs:
        print(f"  Best Cooldown:    {cool_configs[0]['cooldown']} bars"
              f" → Sharpe {cool_configs[0]['sharpe']:+.2f}, MaxCns {cool_configs[0]['max_consec']}")


if __name__ == "__main__":
    main()
