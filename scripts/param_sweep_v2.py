
"""Systematic parameter sweep for MA State strategy across both pairs."""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.ma_state import MAStateStrategy
import time

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Parameter grid
fast_periods = [5, 10, 15, 20, 30, 40, 50, 60, 80, 100]
slow_multipliers = [2, 3, 4, 5, 6, 8]  # slow = fast * multiplier
ma_types = ['sma', 'ema']
stop_loss_opts = [False, True]
pairs = ['BTC/USDT', 'TON/USDT']
data_periods = [365, None]  # None = all data

# Filter: skip too-short combos
combos = []
for fast in fast_periods:
    for mult in slow_multipliers:
        slow = fast * mult
        if slow <= fast: continue
        if slow > 400: continue  # too long
        for ma_type in ma_types:
            for sl in stop_loss_opts:
                combos.append((fast, slow, ma_type, sl))

print(f"Total combinations: {len(combos)} x 2 pairs x 2 periods = {len(combos) * 4}")
print()

def run_test(pair, fast, slow, ma_type, use_sl, days):
    engine = BacktestEngine(BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False))
    strategy = MAStateStrategy(f"sweep_{fast}_{slow}_{ma_type}", {
        "fast_ma_period": fast, "slow_ma_period": slow,
        "ma_type": ma_type, "use_stop_loss": use_sl,
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
    except:
        return None

for pair in pairs:
    for days in data_periods:
        day_label = f"{days}d" if days else "ALL"
        print(f"=== {pair} ({day_label}) ===")
        print(f"{'Params':<25} | {'Return':>8} | {'Trades':>6}")
        print("-" * 55)
        
        results = []
        for fast, slow, ma_type, use_sl in combos:
            r = run_test(pair, fast, slow, ma_type, use_sl, days)
            if r:
                results.append({
                    'params': f"{ma_type}({fast},{slow}) sl={use_sl}",
                    'return': r['return'],
                    'trades': r['trades'],
                    'fast': fast, 'slow': slow, 'ma_type': ma_type, 'use_sl': use_sl,
                })
        
        # Sort by return
        results.sort(key=lambda x: x['return'], reverse=True)
        
        # Print top 5
        for i, r in enumerate(results[:5]):
            marker = "***" if r['return'] > 0.20 else "   "
            print(f"{marker}{i+1}. {r['params']:<21} | {r['return']:>+7.1%} | {r['trades']:>6}")
        
        print()
