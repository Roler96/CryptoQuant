
"""TON/USDT parameter sweep for MAStateStrategy."""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from strategy.cta.ma_state import MAStateStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Focused grid for TON (where shorter MAs worked better)
fast_periods = [5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100]
slow_multipliers = [2, 3, 4, 5, 6, 8]
ma_types = ['sma', 'ema']

combos = []
for fast in fast_periods:
    for mult in slow_multipliers:
        slow = fast * mult
        if slow <= fast: continue
        if slow > 400: continue
        for ma_type in ma_types:
            combos.append((fast, slow, ma_type))

print(f"Testing {len(combos)} combinations on TON/USDT 365d...")

results = []
for i, (fast, slow, ma_type) in enumerate(combos):
    engine = BacktestEngine(BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False))
    strategy = MAStateStrategy(f"sweep_{fast}_{slow}", {
        "fast_ma_period": fast, "slow_ma_period": slow,
        "ma_type": ma_type, "use_stop_loss": False,
    })
    try:
        result = engine.run_backtest(strategy, 'TON/USDT', '1h', days=365)
        if not result.error:
            results.append({
                'params': f"{ma_type}({fast},{slow})",
                'return': result.total_return,
                'trades': len(result.trades) if result.trades else 0,
            })
    except:
        pass
    if (i+1) % 20 == 0:
        print(f"  {i+1}/{len(combos)} done...")

results.sort(key=lambda x: x['return'], reverse=True)

print(f"\n=== TON/USDT TOP 15 (365d) ===")
print(f"{'Rank':<5} {'Params':<20} {'Return':>8} {'Trades':>7}")
print("-" * 45)
for i, r in enumerate(results[:15]):
    marker = "***" if r['return'] > 0.30 else "   "
    print(f"{marker}{i+1:<5} {r['params']:<20} {r['return']:>+8.1%} {r['trades']:>7}")

# Test best combo on multiple periods
best = results[0]
print(f"\n=== TON/USDT BEST: {best['params']} ===")
for days in [365, 730, None]:
    engine = BacktestEngine(BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False))
    fast = int(best['params'].split('(')[1].split(',')[0])
    slow = int(best['params'].split(',')[1].split(')')[0])
    ma_type = best['params'].split('(')[0]
    strategy = MAStateStrategy(f"best_{fast}_{slow}", {
        "fast_ma_period": fast, "slow_ma_period": slow,
        "ma_type": ma_type, "use_stop_loss": False,
    })
    r = engine.run_backtest(strategy, 'TON/USDT', '1h', days=days)
    day_label = f"{days}d" if days else "ALL"
    print(f"  {day_label:>5s}: {r.total_return:>+8.1%} ({len(r.trades) if r.trades else 0} trades)")
