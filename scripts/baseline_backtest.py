
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal

# Run backtest on BTC/USDT 1h with default parameters
config = BacktestConfig(
    initial_cash=10000,
    commission=0.001,
    slippage=0.0005,
    plot_results=False,
)

engine = BacktestEngine(config)
strategy = engine.load_strategy('cta')

result = engine.run_backtest(
    strategy, 
    'BTC/USDT', 
    '1h',
    days=365  # 1 year of data
)

print(f"Strategy: {result.strategy_name}")
print(f"Pair: {result.pair} {result.timeframe}")
print(f"Initial Value: ${result.initial_value:,.2f}")
print(f"Final Value: ${result.final_value:,.2f}")
print(f"Total Return: {result.total_return:.2%}")
print(f"Total Trades: {len(result.trades)}")
print(f"Sharpe Ratio: {result.sharpe_ratio}")
print(f"Max Drawdown: {result.max_drawdown}")

# Calculate additional metrics
if result.equity_curve:
    equity_dec = [Decimal(str(v)) for v in result.equity_curve]
    report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
    
    print(f"\n--- Performance Report ---")
    print(f"Win Rate: {report['trade_metrics']['win_rate_pct']:.1f}%")
    print(f"Profit Factor: {report['trade_metrics']['profit_factor']}")
    print(f"Annualized Return: {report['returns']['annualized_return_pct']:.1f}%")
    print(f"Calmar Ratio: {report['risk_metrics']['calmar_ratio']}")
