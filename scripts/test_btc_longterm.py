
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.trend_following import TrendFollowingStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Long-term MA combinations for BTC
test_cases = [
    # Standard long-term
    {'name': 'SMA_50_200', 'params': {'fast_ma_period': 50, 'slow_ma_period': 200, 'ma_type': 'sma', 'use_rsi_filter': False, 'use_adx_filter': False, 'use_regime_filter': False, 'use_atr_exit': False}},
    {'name': 'EMA_50_200', 'params': {'fast_ma_period': 50, 'slow_ma_period': 200, 'ma_type': 'ema', 'use_rsi_filter': False, 'use_adx_filter': False, 'use_regime_filter': False, 'use_atr_exit': False}},
    {'name': 'SMA_20_100', 'params': {'fast_ma_period': 20, 'slow_ma_period': 100, 'ma_type': 'sma', 'use_rsi_filter': False, 'use_adx_filter': False, 'use_regime_filter': False, 'use_atr_exit': False}},
    {'name': 'EMA_20_100', 'params': {'fast_ma_period': 20, 'slow_ma_period': 100, 'ma_type': 'ema', 'use_rsi_filter': False, 'use_adx_filter': False, 'use_regime_filter': False, 'use_atr_exit': False}},
    # Very long-term
    {'name': 'SMA_100_500', 'params': {'fast_ma_period': 100, 'slow_ma_period': 500, 'ma_type': 'sma', 'use_rsi_filter': False, 'use_adx_filter': False, 'use_regime_filter': False, 'use_atr_exit': False}},
    # With exits
    {'name': 'SMA_50_200_atr', 'params': {'fast_ma_period': 50, 'slow_ma_period': 200, 'ma_type': 'sma', 'use_rsi_filter': False, 'use_adx_filter': False, 'use_regime_filter': False}},
]

for tc in test_cases:
    engine = BacktestEngine(config)
    strategy = TrendFollowingStrategy(name=tc['name'], params=tc['params'])
    result = engine.run_backtest(strategy, 'BTC/USDT', '1h', days=365)
    
    long_trades = sum(1 for t in result.trades if t.get('side') == 'long')
    short_trades = sum(1 for t in result.trades if t.get('side') == 'short')
    wins = sum(1 for t in result.trades if t.get('pnl', 0) > 0)
    
    marker = "***" if result.total_return >= 0.10 else "   "
    print(f"{marker}{tc['name']:20s} | Return={result.total_return:+.1%} | Trades={len(result.trades):3d} | L:{long_trades:2d} S:{short_trades:2d} | Wins:{wins}")
