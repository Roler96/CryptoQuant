
"""Verify BTC best params and test alternative strategies."""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.ma_state import MAStateStrategy
from strategy.cta.trend_following import TrendFollowingStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

print("=" * 80)
print("BTC/USDT - BEST MA STATE PARAMS VALIDATION")
print("=" * 80)

# Test top 5 from sweep
top_params = [
    ("sma(100,300)", 100, 300, "sma"),
    ("sma(80,320)", 80, 320, "sma"),
    ("sma(80,400)", 80, 400, "sma"),
    ("sma(60,360)", 60, 360, "sma"),
    ("sma(50,400)", 50, 400, "sma"),
]

print(f"{'Params':<20} | {'1y Ret':>8} | {'1y Tr':>6} | {'2y Ret':>8} | {'ALL Ret':>8} | {'ALL Tr':>7}")
print("-" * 80)

for name, fast, slow, ma_type in top_params:
    row = f"{name:<20}"
    for days in [365, 730, None]:
        engine = BacktestEngine(BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False))
        strategy = MAStateStrategy("v", {
            "fast_ma_period": fast, "slow_ma_period": slow,
            "ma_type": ma_type, "use_stop_loss": False,
        })
        r = engine.run_backtest(strategy, 'BTC/USDT', '1h', days=days)
        row += f" | {r.total_return:>+7.1%}"
        if days == 365:
            row += f" {len(r.trades):>4}"
        elif days is None:
            row += f" {len(r.trades):>5}"
    print(row)

# Also test with TrendFollowing for comparison
print()
print("=" * 80)
print("BTC/USDT - TREND FOLLOWING BENCHMARK")
print("=" * 80)
for params_name, params in [
    ("default", {"ma_type": "sma"}),
    ("no_filters", {"ma_type": "sma", "use_rsi_filter": False, "use_adx_filter": False, 
                     "use_regime_filter": False, "use_atr_exit": False}),
    ("sma(50,200)", {"ma_type": "sma", "fast_ma_period": 50, "slow_ma_period": 200,
                     "use_rsi_filter": False, "use_adx_filter": False}),
]:
    engine = BacktestEngine(config)
    strategy = TrendFollowingStrategy(params_name, params)
    r = engine.run_backtest(strategy, 'BTC/USDT', '1h', days=365)
    print(f"  {params_name:<15}: {r.total_return:>+7.1%} ({len(r.trades)} trades)")

print()
print("=" * 80)
print("PORTFOLIO SIMULATION: 50/50 BTC+TON")
print("=" * 80)

# BTC best: sma(100,300), TON best (from baseline): sma(20,50)
for alloc_name, btc_pct, ton_pct in [("50/50", 0.5, 0.5), ("40/60", 0.4, 0.6), ("60/40", 0.6, 0.4)]:
    # BTC
    engine_btc = BacktestEngine(BacktestConfig(initial_cash=10000*btc_pct, commission=0.001, slippage=0.0005, plot_results=False))
    strat_btc = MAStateStrategy("btc", {"fast_ma_period": 100, "slow_ma_period": 300, "ma_type": "sma", "use_stop_loss": False})
    btc_r = engine_btc.run_backtest(strat_btc, 'BTC/USDT', '1h', days=365)
    
    # TON  
    engine_ton = BacktestEngine(BacktestConfig(initial_cash=10000*ton_pct, commission=0.001, slippage=0.0005, plot_results=False))
    strat_ton = MAStateStrategy("ton", {"fast_ma_period": 20, "slow_ma_period": 50, "ma_type": "sma", "use_stop_loss": False})
    ton_r = engine_ton.run_backtest(strat_ton, 'TON/USDT', '1h', days=365)
    
    total_final = btc_r.final_value + ton_r.final_value
    total_return = (total_final - 10000) / 10000
    print(f"  {alloc_name}: BTC ${10000*btc_pct:.0f}→${btc_r.final_value:,.0f} ({btc_r.total_return:+.1%}) | "
          f"TON ${10000*ton_pct:.0f}→${ton_r.final_value:,.0f} ({ton_r.total_return:+.1%}) | "
          f"Total → ${total_final:,.0f} ({total_return:+.1%})")
