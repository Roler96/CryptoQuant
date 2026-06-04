
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
strategy = engine.load_strategy('cta')

result = engine.run_backtest(strategy, 'TON/USDT', '1h', days=365)

print(f"Strategy: {result.strategy_name}")
print(f"Pair: {result.pair} {result.timeframe}")
print(f"Initial Value: ${result.initial_value:,.2f}")
print(f"Final Value: ${result.final_value:,.2f}")
print(f"Total Return: {result.total_return:.2%}")
print(f"Total Trades: {len(result.trades)}")
print(f"Sharpe Ratio: {result.sharpe_ratio}")
print(f"Max Drawdown: {result.max_drawdown:.2%}" if result.max_drawdown else "Max Drawdown: N/A")

if result.equity_curve:
    equity_dec = [Decimal(str(v)) for v in result.equity_curve]
    report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
    
    print(f"\n=== Performance Report ===")
    print(f"Win Rate: {report['trade_metrics']['win_rate_pct']:.1f}%")
    print(f"Profit Factor: {report['trade_metrics']['profit_factor']}")
    print(f"Annualized Return: {report['returns']['annualized_return_pct']:.1f}%")
    print(f"Volatility: {report['returns']['volatility_pct']:.1f}%")
    print(f"Calmar Ratio: {report['risk_metrics']['calmar_ratio']}")
    print(f"Avg Trade P&L: {report['trade_metrics']['average_trade_pnl']:.4f}")
    
    print(f"\n=== Threshold Status ===")
    print(f"Sharpe: {report['thresholds']['sharpe_ratio']['value']:.3f} (threshold: {report['thresholds']['sharpe_ratio']['threshold']}) -> {'PASS' if report['thresholds']['sharpe_ratio']['pass'] else 'FAIL'}")
    print(f"Max DD: {report['thresholds']['max_drawdown']['value']:.1%} (threshold: {report['thresholds']['max_drawdown']['threshold']:.0%}) -> {'PASS' if report['thresholds']['max_drawdown']['pass'] else 'FAIL'}")
    print(f"Win Rate: {report['thresholds']['win_rate']['value']:.1%} (threshold: {report['thresholds']['win_rate']['threshold']:.0%}) -> {'PASS' if report['thresholds']['win_rate']['pass'] else 'FAIL'}")
    print(f"Overall: {'PASS' if report['thresholds']['overall_pass'] else 'FAIL'}")
    
    # Show winning vs losing trades
    wins = [t for t in result.trades if t['pnl'] > 0]
    losses = [t for t in result.trades if t['pnl'] <= 0]
    if wins:
        print(f"\n=== Trade Analysis ===")
        print(f"Winning trades: {len(wins)}, Avg win: {sum(t['pnl'] for t in wins)/len(wins):.4f}")
        print(f"Losing trades: {len(losses)}, Avg loss: {sum(t['pnl'] for t in losses)/len(losses):.4f}")
