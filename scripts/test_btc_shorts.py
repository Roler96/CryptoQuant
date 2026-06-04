
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.trend_following import TrendFollowingStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Test different configs that should generate more SHORT signals
test_cases = [
    {'name': 'default (long+short)', 'params': {}},
    {'name': 'no_rsi (more signals)', 'params': {'use_rsi_filter': False}},
    {'name': 'no_adx (more signals)', 'params': {'use_adx_filter': False}},
    {'name': 'no_regime (more signals)', 'params': {'use_regime_filter': False}},
    {'name': 'no_atr_exit', 'params': {'use_atr_exit': False}},
    {'name': 'no_filters', 'params': {'use_rsi_filter': False, 'use_adx_filter': False, 'use_regime_filter': False, 'use_atr_exit': False}},
    {'name': 'fast_ma_5_15', 'params': {'fast_ma_period': 5, 'slow_ma_period': 15, 'use_rsi_filter': False}},
    {'name': 'fast_ma_3_10', 'params': {'fast_ma_period': 3, 'slow_ma_period': 10, 'use_rsi_filter': False}},
]

for tc in test_cases:
    engine = BacktestEngine(config)
    strategy = TrendFollowingStrategy(name=tc['name'], params=tc['params'])
    result = engine.run_backtest(strategy, 'BTC/USDT', '1h', days=365)
    
    # Count long vs short trades
    long_trades = sum(1 for t in result.trades if 'side' in t and t.get('side') == 'long')
    short_trades = sum(1 for t in result.trades if 'side' in t and t.get('side') == 'short')
    
    print(f"{tc['name']:25s} | Return={result.total_return:+.1%} | Trades={len(result.trades):3d} | L:{long_trades:2d} S:{short_trades:2d}")
