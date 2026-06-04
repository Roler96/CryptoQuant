
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.optimized_trend import OptimizedTrendStrategy

# Register the optimized strategy
config = BacktestConfig(
    initial_cash=10000,
    commission=0.001,
    slippage=0.0005,
    plot_results=False,
)

engine = BacktestEngine(config)
engine.register_strategy('optimized', OptimizedTrendStrategy)

# Run backtest
strategy = engine.load_strategy('optimized')

result = engine.run_backtest(
    strategy, 
    'BTC/USDT', 
    '1h',
    days=365
)

print(f"Strategy: {result.strategy_name}")
print(f"Pair: {result.pair} {result.timeframe}")
print(f"Initial Value: ${result.initial_value:,.2f}")
print(f"Final Value: ${result.final_value:,.2f}")
print(f"Total Return: {result.total_return:.2%}")
print(f"Total Trades: {len(result.trades)}")
print(f"Sharpe Ratio: {result.sharpe_ratio}")
print(f"Max Drawdown: {result.max_drawdown:.2%}" if result.max_drawdown else "Max Drawdown: N/A")

# Calculate additional metrics
if result.equity_curve:
    equity_dec = [Decimal(str(v)) for v in result.equity_curve]
    report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
    
    print(f"\n--- Performance Report ---")
    print(f"Win Rate: {report['trade_metrics']['win_rate_pct']:.1f}%")
    print(f"Profit Factor: {report['trade_metrics']['profit_factor']}")
    print(f"Annualized Return: {report['returns']['annualized_return_pct']:.1f}%")
    print(f"Calmar Ratio: {report['risk_metrics']['calmar_ratio']}")
    
    # Show threshold status
    print(f"\n--- Threshold Status ---")
    print(f"Sharpe Pass: {report['thresholds']['sharpe_ratio']['pass']}")
    print(f"Max DD Pass: {report['thresholds']['max_drawdown']['pass']}")
    print(f"Win Rate Pass: {report['thresholds']['win_rate']['pass']}")
    print(f"Overall Pass: {report['thresholds']['overall_pass']}")
