
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.dual_optimized import DualOptimizedStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Test different trend MA periods
for trend_period in [100, 200, 500, 1000]:
    for pair in ['BTC/USDT', 'TON/USDT']:
        engine = BacktestEngine(config)
        params = {
            'use_trend_filter': True,
            'trend_ma_period': trend_period,
            'ma_type': 'sma',
            'use_rsi_filter': True,
            'use_adx_filter': False,
        }
        strategy = DualOptimizedStrategy(name=f'dual_{pair}', params=params)
        result = engine.run_backtest(strategy, pair, '1h', days=365)
        
        trades = len(result.trades)
        ret = result.total_return
        marker = "***" if ret >= 0.10 else "   "
        print(f"{marker}{pair:12s} | Trend MA={trend_period:4d} | Return={ret:+.1%} | Trades={trades:3d}")
