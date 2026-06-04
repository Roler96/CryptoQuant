
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.adaptive_strategy import AdaptiveStrategy

config = BacktestConfig(
    initial_cash=10000,
    commission=0.001,
    slippage=0.0005,
    plot_results=False,
)

engine = BacktestEngine(config)
engine.register_strategy('adaptive', AdaptiveStrategy)

strategy = engine.load_strategy('adaptive')

result = engine.run_backtest(
    strategy, 
    'BTC/USDT', 
    '1h',
    days=365
)

print(f"Strategy: {result.strategy_name}")
print(f"Initial: ${result.initial_value:,.2f} -> Final: ${result.final_value:,.2f}")
print(f"Return: {result.total_return:.2%}")
print(f"Trades: {len(result.trades)}")
print(f"Sharpe: {result.sharpe_ratio}")
print(f"Max DD: {result.max_drawdown:.2%}" if result.max_drawdown else "Max DD: N/A")

if result.equity_curve:
    equity_dec = [Decimal(str(v)) for v in result.equity_curve]
    report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
    print(f"Win Rate: {report['trade_metrics']['win_rate_pct']:.1f}%")
    print(f"Profit Factor: {report['trade_metrics']['profit_factor']}")
    print(f"Annualized Return: {report['returns']['annualized_return_pct']:.1f}%")
