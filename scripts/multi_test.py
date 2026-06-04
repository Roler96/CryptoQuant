
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal

config = BacktestConfig(
    initial_cash=10000,
    commission=0.001,
    slippage=0.0005,
    plot_results=False,
)

engine = BacktestEngine(config)

# Test both strategies on TON
pairs_timeframes = [
    ('TON/USDT', '1h'),
]

for pair, tf in pairs_timeframes:
    for strat_name in ['cta', 'optimized', 'adaptive']:
        try:
            if strat_name == 'optimized':
                from strategy.cta.optimized_trend import OptimizedTrendStrategy
                engine.register_strategy('optimized', OptimizedTrendStrategy)
            elif strat_name == 'adaptive':
                from strategy.cta.adaptive_strategy import AdaptiveStrategy
                engine.register_strategy('adaptive', AdaptiveStrategy)
            
            strategy = engine.load_strategy(strat_name)
            result = engine.run_backtest(strategy, pair, tf, days=365)
            
            print(f"{strat_name:12s} | {pair:12s} {tf:3s} | Return: {result.total_return:7.2%} | Trades: {len(result.trades):3d} | Sharpe: {result.sharpe_ratio:6.3f} | Win%: ", end="")
            
            if result.equity_curve and result.trades:
                equity_dec = [Decimal(str(v)) for v in result.equity_curve]
                report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
                print(f"{report['trade_metrics']['win_rate_pct']:5.1f}%")
            else:
                print("N/A")
        except Exception as e:
            print(f"{strat_name:12s} | {pair:12s} {tf:3s} | ERROR: {e}")
