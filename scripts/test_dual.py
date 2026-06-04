
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.dual_optimized import DualOptimizedStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

pairs_configs = [
    ('BTC/USDT', {'use_trend_filter': True, 'trend_ma_period': 200, 'ma_type': 'sma', 'use_rsi_filter': True}),
    ('TON/USDT', {'use_trend_filter': True, 'trend_ma_period': 200, 'ma_type': 'sma', 'use_rsi_filter': True}),
    ('BTC/USDT', {'use_trend_filter': False, 'ma_type': 'sma', 'use_rsi_filter': True}),
    ('TON/USDT', {'use_trend_filter': False, 'ma_type': 'sma', 'use_rsi_filter': True}),
]

for pair, params in pairs_configs:
    engine = BacktestEngine(config)
    strategy = DualOptimizedStrategy(name=f'dual_{pair.replace("/", "_")}', params=params)
    result = engine.run_backtest(strategy, pair, '1h', days=365)
    
    if result.equity_curve:
        equity_dec = [Decimal(str(v)) for v in result.equity_curve]
        report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
        
        trend = "With 200-SMA filter" if params.get('use_trend_filter') else "No trend filter"
        print(f"{pair:12s} ({trend:20s}): Return={result.total_return:+.1%}, Trades={len(result.trades):3d}, Win%={report['trade_metrics']['win_rate_pct']:.0f}%, PF={report['trade_metrics']['profit_factor']:.2f}, MaxDD={report['risk_metrics']['max_drawdown_pct']:.1f}%")
