
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.trend_following import TrendFollowingStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Test 1: Default CTA (no params override)
print("Test 1: Default CTA on TON")
engine1 = BacktestEngine(config)
strategy1 = engine1.load_strategy('cta')
result1 = engine1.run_backtest(strategy1, 'TON/USDT', '1h', days=365)
print(f"  Return: {result1.total_return:+.1%}")

# Test 2: CTA with empty params
print("\nTest 2: CTA with empty params")
engine2 = BacktestEngine(config)
strategy2 = TrendFollowingStrategy(name='test', params={})
result2 = engine2.run_backtest(strategy2, 'TON/USDT', '1h', days=365)
print(f"  Return: {result2.total_return:+.1%}")

# Test 3: CTA with partial params (just ma periods)
print("\nTest 3: CTA with partial params")
engine3 = BacktestEngine(config)
strategy3 = TrendFollowingStrategy(name='test', params={'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'ema'})
result3 = engine3.run_backtest(strategy3, 'TON/USDT', '1h', days=365)
print(f"  Return: {result3.total_return:+.1%}")

# Test 4: CTA with full ton_config
print("\nTest 4: CTA with ton_config")
ton_config = {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'ema'}
engine4 = BacktestEngine(config)
strategy4 = TrendFollowingStrategy(name='test', params=ton_config)
result4 = engine4.run_backtest(strategy4, 'TON/USDT', '1h', days=365)
print(f"  Return: {result4.total_return:+.1%}")
print(f"  Strategy config: fast={strategy4.config.fast_ma_period}, slow={strategy4.config.slow_ma_period}, ma_type={strategy4.config.ma_type}")
print(f"  RSI filter: {strategy4.config.use_rsi_filter}")
print(f"  ADX filter: {strategy4.config.use_adx_filter}")
