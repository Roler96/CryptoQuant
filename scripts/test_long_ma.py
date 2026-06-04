
import sys, json
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.ma_state import MAStateStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Very long MAs that should establish SHORT early and hold
test_cases = [
    {'name': 'SMA_50_200', 'params': {'fast_ma_period': 50, 'slow_ma_period': 200, 'ma_type': 'sma', 'use_stop_loss': False}},
    {'name': 'SMA_30_120', 'params': {'fast_ma_period': 30, 'slow_ma_period': 120, 'ma_type': 'sma', 'use_stop_loss': False}},
    {'name': 'SMA_20_100', 'params': {'fast_ma_period': 20, 'slow_ma_period': 100, 'ma_type': 'sma', 'use_stop_loss': False}},
    {'name': 'EMA_50_200', 'params': {'fast_ma_period': 50, 'slow_ma_period': 200, 'ma_type': 'ema', 'use_stop_loss': False}},
    {'name': 'EMA_30_120', 'params': {'fast_ma_period': 30, 'slow_ma_period': 120, 'ma_type': 'ema', 'use_stop_loss': False}},
    # With stops
    {'name': 'SMA_50_200_stop', 'params': {'fast_ma_period': 50, 'slow_ma_period': 200, 'ma_type': 'sma', 'stop_loss_pct': 0.10, 'take_profit_pct': 0.30}},
    {'name': 'SMA_30_120_stop', 'params': {'fast_ma_period': 30, 'slow_ma_period': 120, 'ma_type': 'sma', 'stop_loss_pct': 0.10, 'take_profit_pct': 0.30}},
]

results = []

for tc in test_cases:
    for pair in ['BTC/USDT', 'TON/USDT']:
        engine = BacktestEngine(config)
        strategy = MAStateStrategy(name=tc['name'], params=tc['params'])
        result = engine.run_backtest(strategy, pair, '1h', days=365)
        
        long_trades = sum(1 for t in result.trades if t.get('side') == 'long')
        short_trades = sum(1 for t in result.trades if t.get('side') == 'short')
        
        pf = 0
        if result.equity_curve and result.trades:
            equity_dec = [Decimal(str(v)) for v in result.equity_curve]
            report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
            pf = report['trade_metrics']['profit_factor'] or 0
        
        results.append({
            'params': tc['name'],
            'pair': pair,
            'return': result.total_return,
            'trades': len(result.trades),
            'long': long_trades,
            'short': short_trades,
            'pf': pf,
        })

for r in results:
    marker = "***" if r['return'] >= 0.10 else "   "
    print(f"{marker}{r['params']:25s} | {r['pair']:12s} | {r['return']:>+7.1%} | {r['trades']:4d} | L:{r['long']:3d} S:{r['short']:3d} | PF:{r['pf']:.2f}")
