
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from strategy.cta.trend_following import TrendFollowingStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Test different ma_type for TON
for ma_type in ['sma', 'ema']:
    engine = BacktestEngine(config)
    strategy = TrendFollowingStrategy(name=f'test_{ma_type}', params={'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': ma_type})
    result = engine.run_backtest(strategy, 'TON/USDT', '1h', days=365)
    print(f"TON with {ma_type}: {result.total_return:+.1%}")

# Also test with no params at all (should use defaults)
engine2 = BacktestEngine(config)
strategy2 = TrendFollowingStrategy(name='default')
result2 = engine2.run_backtest(strategy2, 'TON/USDT', '1h', days=365)
print(f"TON default (no params): {result2.total_return:+.1%}")
print(f"  ma_type: {strategy2.config.ma_type}")
print(f"  fast: {strategy2.config.fast_ma_period}, slow: {strategy2.config.slow_ma_period}")
