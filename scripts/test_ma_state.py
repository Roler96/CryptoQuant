
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.ma_state import MAStateStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Test different parameter combinations
test_cases = [
    {'name': 'SMA_20_50', 'params': {'fast_ma_period': 20, 'slow_ma_period': 50, 'ma_type': 'sma'}},
    {'name': 'EMA_20_50', 'params': {'fast_ma_period': 20, 'slow_ma_period': 50, 'ma_type': 'ema'}},
    {'name': 'SMA_10_30', 'params': {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'sma'}},
    {'name': 'EMA_10_30', 'params': {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'ema'}},
    {'name': 'SMA_20_50_nostop', 'params': {'fast_ma_period': 20, 'slow_ma_period': 50, 'ma_type': 'sma', 'use_stop_loss': False}},
    {'name': 'SMA_20_50_tight', 'params': {'fast_ma_period': 20, 'slow_ma_period': 50, 'ma_type': 'sma', 'stop_loss_pct': 0.03, 'take_profit_pct': 0.10, 'trailing_stop_pct': 0.02}},
    {'name': 'SMA_20_50_wide', 'params': {'fast_ma_period': 20, 'slow_ma_period': 50, 'ma_type': 'sma', 'stop_loss_pct': 0.08, 'take_profit_pct': 0.25, 'trailing_stop_pct': 0.05}},
    {'name': 'SMA_10_50', 'params': {'fast_ma_period': 10, 'slow_ma_period': 50, 'ma_type': 'sma'}},
    {'name': 'SMA_5_30', 'params': {'fast_ma_period': 5, 'slow_ma_period': 30, 'ma_type': 'sma'}},
]

print("=" * 80)
print(f"{'Params':<25} | {'Pair':<12} | {'Return':>8} | {'Trades':>6} | {'L/S':>8} | {'PF':>6}")
print("=" * 80)

for tc in test_cases:
    for pair in ['BTC/USDT', 'TON/USDT']:
        engine = BacktestEngine(config)
        engine.register_strategy('ma_state', MAStateStrategy)
        strategy = MAStateStrategy(name=tc['name'], params=tc['params'])
        result = engine.run_backtest(strategy, pair, '1h', days=365)
        
        long_trades = sum(1 for t in result.trades if t.get('side') == 'long')
        short_trades = sum(1 for t in result.trades if t.get('side') == 'short')
        
        if result.equity_curve and result.trades:
            equity_dec = [Decimal(str(v)) for v in result.equity_curve]
            report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
            pf = report['trade_metrics']['profit_factor'] or 0
        else:
            pf = 0
        
        ret = result.total_return
        marker = "***" if ret >= 0.10 else "   "
        print(f"{marker}{tc['name']:<25} | {pair:<12} | {ret:>+7.1%} | {len(result.trades):>6} | {long_trades:>2d}/{short_trades:<2d} | {pf:>5.2f}")
