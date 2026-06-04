
"""TON/USDT focused sweep - slimmed grid."""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from strategy.cta.ma_state import MAStateStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Focused: we know SMA works, shorter periods for TON
fast_periods = [10, 15, 20, 25, 30, 40, 50, 60, 80, 100]
slow_multipliers = [2, 3, 4, 5, 6]  # slow = fast * mult
ma_types = ['sma', 'ema']

combos = []
for fast in fast_periods:
    for mult in slow_multipliers:
        slow = fast * mult
        if slow <= fast or slow > 400: continue
        for ma_type in ma_types:
            combos.append((fast, slow, ma_type))

print(f"Testing {len(combos)} combos on TON/USDT 365d...")

results = []
for i, (fast, slow, ma_type) in enumerate(combos):
    engine = BacktestEngine(BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False))
    strategy = MAStateStrategy(f"s_{fast}_{slow}", {
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
                'fast': fast, 'slow': slow, 'ma_type': ma_type,
            })
    except:
        pass

results.sort(key=lambda x: x['return'], reverse=True)

print(f"\n=== TON/USDT TOP 10 (365d) ===")
print(f"{'Rank':<5} {'Params':<20} {'Return':>8} {'Trades':>7}")
for i, r in enumerate(results[:10]):
    m = "***" if r['return'] > 0.30 else "   "
    print(f"{m}{i+1:<5} {r['params']:<20} {r['return']:>+8.1%} {r['trades']:>7}")

# Best combo multi-period
best = results[0]
fast = best['fast']; slow = best['slow']; ma_type = best['ma_type']
print(f"\n=== BEST {ma_type}({fast},{slow}) ROBUSTNESS ===")
for days in [365, 730, None]:
    engine = BacktestEngine(BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False))
    strategy = MAStateStrategy("robust", {
        "fast_ma_period": fast, "slow_ma_period": slow,
        "ma_type": ma_type, "use_stop_loss": False,
    })
    r = engine.run_backtest(strategy, 'TON/USDT', '1h', days=days)
    label = f"{days}d" if days else "ALL"
    print(f"  {label:>5s}: {r.total_return:>+8.1%} ({len(r.trades) if r.trades else 0} trades)")
print("DONE")
