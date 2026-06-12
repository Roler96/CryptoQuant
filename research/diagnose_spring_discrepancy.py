"""
Diagnostic: Why does Spring backtest differ from documented results?

Documented (STRATEGY.md, 2026-06-09):
  Trades: 801, Sharpe: 2.72, Sum: +65.7%, Win rate: 58%, PF: 1.18
  Exits: stop=65, target=232, time=504

My reproduction:
  Trades: 725, Sharpe: -0.65, Sum: -67.8%, Win rate: 54.2%, PF: 0.84
  Exits: stop=91, target=202, time=432

Hypotheses to test:
1. Signal generation difference (count, timing)
2. Engine stop checking (lows vs closes)
3. Entry price model (next bar open vs current close)
4. Commission/slippage application
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from collections import Counter

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.signals import new_low_bullish, sma

# Load data
store = OHLCVStore(db_path="data/cryptoquant.db")
df = store.load("okx", "BTC/USDT", "1h")
print(f"Data: {len(df)} bars, {df.index[0]} → {df.index[-1]}")

# 1. Check signal count
signals = new_low_bullish(df, lookback=30)
n_signals = signals.sum()
print(f"\n[1] Signal count: {n_signals} (documented: ~801 trades)")

# 2. Check signal with SMA200 filter
sma200 = sma(df["close"], 200)
above_sma = (df["close"] > sma200).astype(int)
filtered_signals = signals * above_sma
print(f"    Signals with SMA200 filter: {filtered_signals.sum()}")

# 3. Run baseline with engine — check what engine does
engine = BacktestEngine(commission=0.0005, slippage=0.0005)

from strategies.spring import SpringReversal
strategy = SpringReversal()
result = engine.run(df, strategy, symbol="BTC/USDT",
    stop_loss_pct=3.0, take_profit_pct=1.5, max_hold_bars=6)

print(f"\n[2] Engine result:")
print(f"    Trades: {len(result.trades)}")
print(f"    Sum: {sum(t.pnl_pct for t in result.trades):+.1f}%")
print(f"    Sharpe: {result.metrics.sharpe_ratio:.2f}")
print(f"    Exits: {Counter(t.exit_reason for t in result.trades)}")

# 4. Test with use_lows_for_stops=False (to see if original used closes)
print(f"\n[3] Testing use_lows_for_stops=False (closes-based stops):")
engine_closes = BacktestEngine(commission=0.0005, slippage=0.0005, use_lows_for_stops=False)
result_closes = engine_closes.run(df, strategy, symbol="BTC/USDT",
    stop_loss_pct=3.0, take_profit_pct=1.5, max_hold_bars=6)
print(f"    Trades: {len(result_closes.trades)}")
print(f"    Sum: {sum(t.pnl_pct for t in result_closes.trades):+.1f}%")
print(f"    Sharpe: {result_closes.metrics.sharpe_ratio:.2f}")
print(f"    Max DD: {result_closes.metrics.max_drawdown_pct:.1f}%")
print(f"    Exits: {Counter(t.exit_reason for t in result_closes.trades)}")

# 5. Manual simulation to understand entry/exit
print(f"\n[4] Manual simulation (first 20 trades):")
opens = df["open"].values
highs = df["high"].values
lows = df["low"].values
closes = df["close"].values

sig_values = signals.values
n = len(df)

# Simulate manually with next-bar entry
trades_manual = []
pending_signal = False
position = None

for i in range(n):
    if position is None and pending_signal:
        entry_price = opens[i]
        entry_idx = i
        stop_price = entry_price * (1 - 3.0/100)
        target_price = entry_price * (1 + 1.5/100)
        position = {"entry_price": entry_price, "entry_idx": entry_idx,
                    "stop": stop_price, "target": target_price}
        pending_signal = False

    if position is not None:
        for j in range(max(position["entry_idx"]+1, i), i+1):
            if j >= n: break
            # Check stop with lows
            if lows[j] <= position["stop"]:
                exit_price = position["stop"] * (1 - 0.0005)
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_manual.append({"pnl": pnl, "reason": "stop", "idx": j})
                position = None
                break
            # Check target with highs
            if highs[j] >= position["target"]:
                exit_price = position["target"] * (1 - 0.0005)
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_manual.append({"pnl": pnl, "reason": "target", "idx": j})
                position = None
                break
            # Check time
            if (j - position["entry_idx"]) >= 6:
                exit_price = opens[j] * (1 - 0.0005)
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_manual.append({"pnl": pnl, "reason": "time", "idx": j})
                position = None
                break

    if position is None and not pending_signal:
        if i < len(sig_values) and sig_values[i] == 1:
            pending_signal = True

print(f"    Manual trades: {len(trades_manual)}")
if trades_manual:
    pnls = [t["pnl"] for t in trades_manual]
    print(f"    Sum: {sum(pnls):+.1f}%")
    print(f"    Exits: {Counter(t['reason'] for t in trades_manual)}")
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    print(f"    Win rate: {len(wins)/len(pnls)*100:.1f}%")
    if wins: print(f"    Avg win: {np.mean(wins):+.3f}%")
    if losses: print(f"    Avg loss: {np.mean(losses):+.3f}%")

# 6. Now test: what if we DON'T apply slippage to stop/target exits?
print(f"\n[5] Manual WITHOUT slippage on stop/target exits:")
trades_no_slip = []
pending_signal = False
position = None

for i in range(n):
    if position is None and pending_signal:
        entry_price = opens[i]
        entry_idx = i
        stop_price = entry_price * (1 - 3.0/100)
        target_price = entry_price * (1 + 1.5/100)
        position = {"entry_price": entry_price, "entry_idx": entry_idx,
                    "stop": stop_price, "target": target_price}
        pending_signal = False

    if position is not None:
        for j in range(max(position["entry_idx"]+1, i), i+1):
            if j >= n: break
            if lows[j] <= position["stop"]:
                exit_price = position["stop"]  # NO slippage
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_no_slip.append({"pnl": pnl, "reason": "stop", "idx": j})
                position = None
                break
            if highs[j] >= position["target"]:
                exit_price = position["target"]  # NO slippage
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_no_slip.append({"pnl": pnl, "reason": "target", "idx": j})
                position = None
                break
            if (j - position["entry_idx"]) >= 6:
                exit_price = opens[j]  # NO slippage
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_no_slip.append({"pnl": pnl, "reason": "time", "idx": j})
                position = None
                break

    if position is None and not pending_signal:
        if i < len(sig_values) and sig_values[i] == 1:
            pending_signal = True

pnls_ns = [t["pnl"] for t in trades_no_slip]
print(f"    Trades: {len(trades_no_slip)}, Sum: {sum(pnls_ns):+.1f}%")
print(f"    Exits: {Counter(t['reason'] for t in trades_no_slip)}")

# 7. What if entry is at CLOSE[i] instead of OPEN[i+1]?
print(f"\n[6] Manual with entry at SIGNAL BAR CLOSE (not next bar open):")
trades_close_entry = []
position = None

for i in range(n):
    if position is None and i < len(sig_values) and sig_values[i] == 1:
        entry_price = closes[i]  # Enter at signal bar close
        entry_idx = i
        stop_price = entry_price * (1 - 3.0/100)
        target_price = entry_price * (1 + 1.5/100)
        position = {"entry_price": entry_price, "entry_idx": entry_idx,
                    "stop": stop_price, "target": target_price}

    if position is not None:
        for j in range(max(position["entry_idx"]+1, i), i+1):
            if j >= n: break
            if lows[j] <= position["stop"]:
                exit_price = position["stop"] * (1 - 0.0005)
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_close_entry.append({"pnl": pnl, "reason": "stop", "idx": j})
                position = None
                break
            if highs[j] >= position["target"]:
                exit_price = position["target"] * (1 - 0.0005)
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_close_entry.append({"pnl": pnl, "reason": "target", "idx": j})
                position = None
                break
            if (j - position["entry_idx"]) >= 6:
                exit_price = opens[j] * (1 - 0.0005)
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_close_entry.append({"pnl": pnl, "reason": "time", "idx": j})
                position = None
                break

pnls_ce = [t["pnl"] for t in trades_close_entry]
print(f"    Trades: {len(trades_close_entry)}, Sum: {sum(pnls_ce):+.1f}%")
print(f"    Exits: {Counter(t['reason'] for t in trades_close_entry)}")

# 8. What if stop is checked with CLOSES instead of LOWS?
print(f"\n[7] Manual with CLOSES-based stop checking:")
trades_close_stop = []
pending_signal = False
position = None

for i in range(n):
    if position is None and pending_signal:
        entry_price = opens[i]
        entry_idx = i
        stop_price = entry_price * (1 - 3.0/100)
        target_price = entry_price * (1 + 1.5/100)
        position = {"entry_price": entry_price, "entry_idx": entry_idx,
                    "stop": stop_price, "target": target_price}
        pending_signal = False

    if position is not None:
        for j in range(max(position["entry_idx"]+1, i), i+1):
            if j >= n: break
            # STOP CHECKED WITH CLOSES (WRONG)
            if closes[j] <= position["stop"]:
                exit_price = position["stop"] * (1 - 0.0005)
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_close_stop.append({"pnl": pnl, "reason": "stop", "idx": j})
                position = None
                break
            if highs[j] >= position["target"]:
                exit_price = position["target"] * (1 - 0.0005)
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_close_stop.append({"pnl": pnl, "reason": "target", "idx": j})
                position = None
                break
            if (j - position["entry_idx"]) >= 6:
                exit_price = opens[j] * (1 - 0.0005)
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_close_stop.append({"pnl": pnl, "reason": "time", "idx": j})
                position = None
                break

    if position is None and not pending_signal:
        if i < len(sig_values) and sig_values[i] == 1:
            pending_signal = True

pnls_cs = [t["pnl"] for t in trades_close_stop]
print(f"    Trades: {len(trades_close_stop)}, Sum: {sum(pnls_cs):+.1f}%")
print(f"    Sharpe approximation: ", end="")
print(f"    Exits: {Counter(t['reason'] for t in trades_close_stop)}")
wins_cs = [p for p in pnls_cs if p > 0]
losses_cs = [p for p in pnls_cs if p <= 0]
print(f"    Win rate: {len(wins_cs)/len(pnls_cs)*100:.1f}%")
if wins_cs: print(f"    Avg win: {np.mean(wins_cs):+.3f}%")
if losses_cs: print(f"    Avg loss: {np.mean(losses_cs):+.3f}%")

# 9. What if we use closes for stops AND no slippage?
print(f"\n[8] Closes-based stops + NO slippage:")
trades_no_slip_cs = []
pending_signal = False
position = None

for i in range(n):
    if position is None and pending_signal:
        entry_price = opens[i]
        entry_idx = i
        stop_price = entry_price * (1 - 3.0/100)
        target_price = entry_price * (1 + 1.5/100)
        position = {"entry_price": entry_price, "entry_idx": entry_idx,
                    "stop": stop_price, "target": target_price}
        pending_signal = False

    if position is not None:
        for j in range(max(position["entry_idx"]+1, i), i+1):
            if j >= n: break
            if closes[j] <= position["stop"]:
                exit_price = position["stop"]  # no slippage
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_no_slip_cs.append({"pnl": pnl, "reason": "stop", "idx": j})
                position = None
                break
            if highs[j] >= position["target"]:
                exit_price = position["target"]  # no slippage
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_no_slip_cs.append({"pnl": pnl, "reason": "target", "idx": j})
                position = None
                break
            if (j - position["entry_idx"]) >= 6:
                exit_price = opens[j]  # no slippage
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades_no_slip_cs.append({"pnl": pnl, "reason": "time", "idx": j})
                position = None
                break

    if position is None and not pending_signal:
        if i < len(sig_values) and sig_values[i] == 1:
            pending_signal = True

pnls_nscs = [t["pnl"] for t in trades_no_slip_cs]
print(f"    Trades: {len(trades_no_slip_cs)}, Sum: {sum(pnls_nscs):+.1f}%")
print(f"    Exits: {Counter(t['reason'] for t in trades_no_slip_cs)}")
wins_nscs = [p for p in pnls_nscs if p > 0]
if wins_nscs: print(f"    Win rate: {len(wins_nscs)/len(pnls_nscs)*100:.1f}%, Avg win: {np.mean(wins_nscs):+.3f}%")

# 10. Check if the issue is in the engine's loop logic
# The engine checks exits at bar i for position entered at bar i-1
# But my manual sim checks from entry_idx+1 to i
# Let me check: does the engine enter at bar i and also check exits at bar i?
print(f"\n[9] Engine entry/exit timing check:")
print(f"    Engine enters at opens[i] when signal was at bar i-1")
print(f"    Engine checks exits starting at bar i (same bar as entry)")
print(f"    This means: if entry bar's low triggers stop, it stops immediately")
print(f"    My manual sim starts checking from entry_idx+1")
print(f"    Difference: engine can stop on entry bar, manual cannot")

# 11. What if the signal uses rolling(lookback).min() WITHOUT shift(1)?
print(f"\n[10] Testing signal WITHOUT shift(1) (potential look-ahead):")
low = df["low"]
# Without shift — includes current bar in rolling min
prev_low_no_shift = low.rolling(30).min()  # includes current bar
new_low_no_shift = low < prev_low_no_shift  # this is almost never true (current is part of min)
# Actually this would be: low[i] < min(low[i-29:i+1]) which means low[i] < low[i] = False
# So this would generate ZERO signals. Not the issue.

# What about shift(-1)? (looking into the future)
prev_low_future = low.rolling(30).min().shift(-1)
new_low_future = low < prev_low_future
bullish = df["close"] > df["open"]
vol_mean = df["volume"].rolling(20).mean()
high_vol = df["volume"] > vol_mean
sig_future = (new_low_future & bullish & high_vol).astype(int)
print(f"    Signals with shift(-1) (look-ahead): {sig_future.sum()}")

# 12. What if the original used a different lookback or volume window?
print(f"\n[11] Signal sensitivity:")
for lb in [15, 20, 30, 50]:
    sig = new_low_bullish(df, lookback=lb)
    print(f"    lookback={lb}: {sig.sum()} signals")

# 13. Let me check: what if the original didn't require bullish close?
print(f"\n[12] Signal without bullish requirement:")
prev_low_min = low.rolling(30).min().shift(1)
new_low_only = low < prev_low_min
high_vol_only = df["volume"] > vol_mean
sig_no_bull = (new_low_only & high_vol_only).astype(int)
print(f"    New low + high vol (no bullish req): {sig_no_bull.sum()} signals")

# 14. What if the original didn't require high volume?
bullish_s = (df["close"] > df["open"])
sig_no_vol = (new_low_only & bullish_s).astype(int)
print(f"    New low + bullish (no vol req): {sig_no_vol.sum()} signals")

# 15. Just new low alone
print(f"    New low only: {new_low_only.sum().sum() if hasattr(new_low_only, 'sum') else new_low_only.sum()} signals")

print("\n" + "="*70)
print("DIAGNOSIS COMPLETE")
print("="*70)
