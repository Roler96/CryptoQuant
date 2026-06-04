
"""MAStateStrategy parameter sweep for TON/USDT + TrendFollowing comparison."""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from strategy.cta.ma_state import MAStateStrategy
from strategy.cta.trend_following import TrendFollowingStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Parameter grid
fast_periods = [5, 10, 15, 20, 25, 30, 40, 50, 60, 80]
slow_multipliers = [2, 3, 4, 5, 6, 8]
ma_types = ['sma', 'ema']

# Build combos
combos = []
for fast in fast_periods:
    for mult in slow_multipliers:
        slow = fast * mult
        if slow <= fast:
            continue
        if slow > 400:
            continue
        for ma_type in ma_types:
            combos.append((fast, slow, ma_type))

print(f"Total MA State combos: {len(combos)}")
print()

def run_ma_test(pair, fast, slow, ma_type, days):
    engine = BacktestEngine(BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False))
    strategy = MAStateStrategy(f"sweep_{fast}_{slow}_{ma_type}", {
        "fast_ma_period": fast, "slow_ma_period": slow,
        "ma_type": ma_type, "use_stop_loss": False,
    })
    try:
        result = engine.run_backtest(strategy, pair, '1h', days=days)
        if result.error:
            return None
        return {
            'return': result.total_return,
            'trades': len(result.trades) if result.trades else 0,
            'final_value': result.final_value,
        }
    except Exception as e:
        print(f"  ERROR ({fast},{slow},{ma_type}): {e}")
        return None

# ===== PHASE 1: 365-day sweep =====
print("=== TON/USDT MA State Parameter Sweep (365d) ===")
print(f"Running {len(combos)} combinations...")
print()

results_365 = []
n = 0
for fast, slow, ma_type in combos:
    n += 1
    r = run_ma_test('TON/USDT', fast, slow, ma_type, days=365)
    if r:
        results_365.append({
            'params': f"{ma_type}({fast},{slow})",
            'return': r['return'],
            'trades': r['trades'],
            'final_value': r['final_value'],
            'fast': fast, 'slow': slow, 'ma_type': ma_type,
        })
    if n % 20 == 0:
        print(f"  Progress: {n}/{len(combos)}...")

# Sort by return
results_365.sort(key=lambda x: x['return'], reverse=True)

print()
print("=== TON/USDT TOP 10 (365d) ===")
print(f"{'#':>3} | {'Params':<20} | {'Return':>8} | {'Trades':>6} | {'Final':>10}")
print("-" * 60)
for i, r in enumerate(results_365[:10]):
    marker = "***" if r['return'] > 0.20 else "   "
    print(f"{marker}{i+1:>3} | {r['params']:<20} | {r['return']:>+7.1%} | {r['trades']:>6} | {r['final_value']:>10.2f}")

print()

# ===== PHASE 2: Validate best on multiple periods =====
if results_365:
    best = results_365[0]
    b_fast = best['fast']
    b_slow = best['slow']
    b_ma = best['ma_type']
    print(f"Best 365d params: {best['params']} with return {best['return']:+.1%}, {best['trades']} trades")
    print()
    
    # Test on ALL data
    r_all = run_ma_test('TON/USDT', b_fast, b_slow, b_ma, days=None)
    print("=== TON/USDT BEST ON ALL DATA ===")
    if r_all:
        print(f"  {best['params']:<20} | {r_all['return']:>+7.1%} | {r_all['trades']:>6} trades | final={r_all['final_value']:.2f}")
    else:
        print("  ERROR: backtest failed")
    print()
    
    # Test on 730d
    r_730 = run_ma_test('TON/USDT', b_fast, b_slow, b_ma, days=730)
    print("=== TON/USDT BEST ON 730d ===")
    if r_730:
        print(f"  {best['params']:<20} | {r_730['return']:>+7.1%} | {r_730['trades']:>6} trades | final={r_730['final_value']:.2f}")
    else:
        print("  ERROR: backtest failed")
    print()
else:
    print("ERROR: No valid results from sweep!")
    sys.exit(1)

# ===== PHASE 3: TrendFollowing comparison =====
print("=== TREND FOLLOWING COMPARISON (default params) ===")
print(f"{'Period':<10} | {'Return':>8} | {'Trades':>6} | {'Final':>10}")
print("-" * 45)

for days, label in [(365, '365d'), (730, '730d'), (None, 'ALL')]:
    engine = BacktestEngine(BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False))
    strategy = TrendFollowingStrategy(name='trend_default')
    try:
        result = engine.run_backtest(strategy, 'TON/USDT', '1h', days=days)
        if result.error:
            print(f"  {label:<10} | ERROR: {result.error}")
        else:
            trades = len(result.trades) if result.trades else 0
            print(f"  {label:<10} | {result.total_return:>+7.1%} | {trades:>6} | {result.final_value:>10.2f}")
    except Exception as e:
        print(f"  {label:<10} | EXCEPTION: {e}")

print()
print("=== DONE ===")
