
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.ma_state import MAStateStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

# Fine-tune around SMA_50_300
test_cases = [
    {'name': 'SMA_50_300_nostop', 'params': {'fast_ma_period': 50, 'slow_ma_period': 300, 'ma_type': 'sma', 'use_stop_loss': False}},
    {'name': 'SMA_50_300_wide_stop', 'params': {'fast_ma_period': 50, 'slow_ma_period': 300, 'ma_type': 'sma', 'stop_loss_pct': 0.15, 'take_profit_pct': 0.40}},
    {'name': 'SMA_40_250_nostop', 'params': {'fast_ma_period': 40, 'slow_ma_period': 250, 'ma_type': 'sma', 'use_stop_loss': False}},
    {'name': 'SMA_60_350_nostop', 'params': {'fast_ma_period': 60, 'slow_ma_period': 350, 'ma_type': 'sma', 'use_stop_loss': False}},
    {'name': 'SMA_50_300_trail', 'params': {'fast_ma_period': 50, 'slow_ma_period': 300, 'ma_type': 'sma', 'stop_loss_pct': 0.10, 'take_profit_pct': 0.30, 'trailing_stop_pct': 0.05}},
    {'name': 'SMA_50_300_trail_wide', 'params': {'fast_ma_period': 50, 'slow_ma_period': 300, 'ma_type': 'sma', 'stop_loss_pct': 0.15, 'take_profit_pct': 0.50, 'trailing_stop_pct': 0.08}},
]

for tc in test_cases:
    for pair in ['BTC/USDT', 'TON/USDT']:
        engine = BacktestEngine(config)
        strategy = MAStateStrategy(name=tc['name'], params=tc['params'])
        result = engine.run_backtest(strategy, pair, '1h', days=365)
        
        long_trades = sum(1 for t in result.trades if t.get('side') == 'long')
        short_trades = sum(1 for t in result.trades if t.get('side') == 'short')
        
        pf = 0
        wr = 0
        mdd = 0
        if result.equity_curve and result.trades:
            equity_dec = [Decimal(str(v)) for v in result.equity_curve]
            report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
            pf = report['trade_metrics']['profit_factor'] or 0
            wr = report['trade_metrics']['win_rate_pct'] or 0
            mdd = report['risk_metrics']['max_drawdown_pct'] or 0
        
        ret = result.total_return
        marker = "***" if ret >= 0.10 else "   "
        print(f"{marker}{tc['name']:25s} | {pair:12s} | {ret:>+7.1%} | {len(result.trades):4d} | L:{long_trades:3d} S:{short_trades:3d} | PF:{pf:.2f} | WR:{wr:.0f}% | MDD:{mdd:.1f}%")
