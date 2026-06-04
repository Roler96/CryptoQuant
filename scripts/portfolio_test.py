
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.trend_following import TrendFollowingStrategy

# Test 1: Equal weight portfolio ($5000 each)
print("=" * 70)
print("TEST 1: Equal Weight Portfolio ($5000 BTC + $5000 TON)")
print("=" * 70)

config = BacktestConfig(
    initial_cash=5000,  # Half capital each
    commission=0.001,
    slippage=0.0005,
    plot_results=False,
)

engine = BacktestEngine(config)
strategy = engine.load_strategy('cta')

# BTC result
btc_result = engine.run_backtest(strategy, 'BTC/USDT', '1h', days=365)
btc_return = btc_result.total_return
btc_final = btc_result.final_value

# TON result  
engine2 = BacktestEngine(config)
strategy2 = engine2.load_strategy('cta')
ton_result = engine2.run_backtest(strategy2, 'TON/USDT', '1h', days=365)
ton_return = ton_result.total_return
ton_final = ton_result.final_value

# Portfolio calculation
total_initial = 10000
total_final = btc_final + ton_final
portfolio_return = (total_final - total_initial) / total_initial

print(f"BTC: $5000 -> ${btc_final:,.2f} ({btc_return:+.2%})")
print(f"TON: $5000 -> ${ton_final:,.2f} ({ton_return:+.2%})")
print(f"Portfolio: $10000 -> ${total_final:,.2f} ({portfolio_return:+.2%})")

# Test 2: 70/30 allocation (more to TON)
print("\n" + "=" * 70)
print("TEST 2: 70/30 Allocation ($3000 BTC + $7000 TON)")
print("=" * 70)

config3k = BacktestConfig(initial_cash=3000, commission=0.001, slippage=0.0005, plot_results=False)
config7k = BacktestConfig(initial_cash=7000, commission=0.001, slippage=0.0005, plot_results=False)

engine3k = BacktestEngine(config3k)
strat3k = engine3k.load_strategy('cta')
btc_3k = engine3k.run_backtest(strat3k, 'BTC/USDT', '1h', days=365)

engine7k = BacktestEngine(config7k)
strat7k = engine7k.load_strategy('cta')
ton_7k = engine7k.run_backtest(strat7k, 'TON/USDT', '1h', days=365)

total_final_7030 = btc_3k.final_value + ton_7k.final_value
portfolio_return_7030 = (total_final_7030 - 10000) / 10000

print(f"BTC ($3k): ${btc_3k.final_value:,.2f} ({btc_3k.total_return:+.2%})")
print(f"TON ($7k): ${ton_7k.final_value:,.2f} ({ton_7k.total_return:+.2%})")
print(f"Portfolio: $10000 -> ${total_final_7030:,.2f} ({portfolio_return_7030:+.2%})")

# Test 3: 30/70 allocation (less to BTC)
print("\n" + "=" * 70)
print("TEST 3: 30/70 Allocation ($7000 BTC + $3000 TON)")
print("=" * 70)

config_btc_7k = BacktestConfig(initial_cash=7000, commission=0.001, slippage=0.0005, plot_results=False)
config_ton_3k = BacktestConfig(initial_cash=3000, commission=0.001, slippage=0.0005, plot_results=False)

engine_btc_7k = BacktestEngine(config_btc_7k)
strat_btc_7k = engine_btc_7k.load_strategy('cta')
btc_7k = engine_btc_7k.run_backtest(strat_btc_7k, 'BTC/USDT', '1h', days=365)

engine_ton_3k = BacktestEngine(config_ton_3k)
strat_ton_3k = engine_ton_3k.load_strategy('cta')
ton_3k = engine_ton_3k.run_backtest(strat_ton_3k, 'TON/USDT', '1h', days=365)

total_final_3070 = btc_7k.final_value + ton_3k.final_value
portfolio_return_3070 = (total_final_3070 - 10000) / 10000

print(f"BTC ($7k): ${btc_7k.final_value:,.2f} ({btc_7k.total_return:+.2%})")
print(f"TON ($3k): ${ton_3k.final_value:,.2f} ({ton_3k.total_return:+.2%})")
print(f"Portfolio: $10000 -> ${total_final_3070:,.2f} ({portfolio_return_3070:+.2%})")

# Test 4: 100% TON only
print("\n" + "=" * 70)
print("TEST 4: 100% TON (skip BTC entirely)")
print("=" * 70)

config_full = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)
engine_full = BacktestEngine(config_full)
strat_full = engine_full.load_strategy('cta')
ton_full = engine_full.run_backtest(strat_full, 'TON/USDT', '1h', days=365)

print(f"TON ($10k): ${ton_full.final_value:,.2f} ({ton_full.total_return:+.2%})")

# Summary
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"50/50 Portfolio: {portfolio_return:+.2%}")
print(f"30/70 Portfolio: {portfolio_return_7030:+.2%}")
print(f"70/30 Portfolio: {portfolio_return_3070:+.2%}")
print(f"100% TON:        {ton_full.total_return:+.2%}")
