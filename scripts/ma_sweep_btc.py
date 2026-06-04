"""MAStateStrategy parameter sweep on BTC/USDT 1h.

Sweeps fast/slow MA combos with use_stop_loss=False, then validates
the best combo on ALL data and 730 days.
"""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from strategy.cta.ma_state import MAStateStrategy
import time

# --- Config ---
PAIR = 'BTC/USDT'
TIMEFRAME = '1h'
BASE_CONFIG = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Parameter grid
FAST_PERIODS = [10, 20, 30, 40, 50, 60, 80, 100]
SLOW_MULTIPLIERS = [2, 3, 4, 5, 6, 8]
MA_TYPES = ['sma', 'ema']
USE_STOP_LOSS = [False]  # only False per task spec

# Build combos
combos = []
for fast in FAST_PERIODS:
    for mult in SLOW_MULTIPLIERS:
        slow = fast * mult
        if slow <= fast:
            continue
        if slow > 400:
            continue
        for ma_type in MA_TYPES:
            for sl in USE_STOP_LOSS:
                combos.append((fast, slow, ma_type, sl))

print(f"Total combinations: {len(combos)}")
print()


def run_test(fast, slow, ma_type, use_sl, days):
    """Run a single backtest. Returns dict or None on failure."""
    engine = BacktestEngine(BASE_CONFIG)
    strategy = MAStateStrategy(f"sweep_{fast}_{slow}_{ma_type}", {
        "fast_ma_period": fast,
        "slow_ma_period": slow,
        "ma_type": ma_type,
        "use_stop_loss": use_sl,
    })
    try:
        result = engine.run_backtest(strategy, PAIR, TIMEFRAME, days=days)
        if result.error:
            return None
        return {
            'fast': fast,
            'slow': slow,
            'ma_type': ma_type,
            'return': result.total_return,
            'trades': len(result.trades) if result.trades else 0,
            'final_value': result.final_value,
        }
    except Exception as e:
        return None


# ============================================================
# PHASE 1: Sweep on 365 days
# ============================================================
print(f"=== BTC/USDT PARAMETER SWEEP (365d) ===")
print(f"Running {len(combos)} combinations...")
print()

results = []
start_time = time.time()
for i, (fast, slow, ma_type, use_sl) in enumerate(combos):
    r = run_test(fast, slow, ma_type, use_sl, days=365)
    if r:
        results.append(r)
    # Progress every 10
    if (i + 1) % 10 == 0:
        elapsed = time.time() - start_time
        eta = elapsed / (i + 1) * (len(combos) - i - 1)
        print(f"  [{i+1}/{len(combos)}] elapsed={elapsed:.0f}s eta={eta:.0f}s  completed={len(results)}")

elapsed = time.time() - start_time
print(f"\nSweep complete: {len(results)}/{len(combos)} succeeded in {elapsed:.0f}s")
print()

# Sort by return
results.sort(key=lambda x: x['return'], reverse=True)

# Print top 10
print("=== BTC/USDT TOP 10 (365d) ===")
for i, r in enumerate(results[:10]):
    label = f"{r['ma_type']}({r['fast']},{r['slow']})"
    print(f"  {label:<20} | {r['return']:>+7.1%} | {r['trades']:>3} trades")
print()

# Best combo
best = results[0]
best_fast = best['fast']
best_slow = best['slow']
best_ma = best['ma_type']
print(f"BEST: {best_ma}({best_fast},{best_slow}) with return={best['return']:.1%}, trades={best['trades']}")
print()

# ============================================================
# PHASE 2: Validate best on ALL data
# ============================================================
print("=== BTC/USDT BEST ON ALL DATA ===")
r_all = run_test(best_fast, best_slow, best_ma, False, days=None)
if r_all:
    label = f"{r_all['ma_type']}({r_all['fast']},{r_all['slow']})"
    print(f"  {label:<20} | {r_all['return']:>+7.1%} | {r_all['trades']:>3} trades")
else:
    print("  ERROR: Failed to run on ALL data")
print()

# ============================================================
# PHASE 3: Validate best on 730 days
# ============================================================
print("=== BTC/USDT BEST ON 730d ===")
r_730 = run_test(best_fast, best_slow, best_ma, False, days=730)
if r_730:
    label = f"{r_730['ma_type']}({r_730['fast']},{r_730['slow']})"
    print(f"  {label:<20} | {r_730['return']:>+7.1%} | {r_730['trades']:>3} trades")
else:
    print("  ERROR: Failed to run on 730d data")
print()

# ============================================================
# Summary
# ============================================================
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Total combos tested: {len(combos)}")
print(f"Successful runs:    {len(results)}")
print(f"Best 365d:          {best_ma}({best_fast},{best_slow}) = {best['return']:.1%} ({best['trades']} trades)")
if r_all:
    print(f"Best ALL data:      {best_ma}({best_fast},{best_slow}) = {r_all['return']:.1%} ({r_all['trades']} trades)")
if r_730:
    print(f"Best 730d:          {best_ma}({best_fast},{best_slow}) = {r_730['return']:.1%} ({r_730['trades']} trades)")
