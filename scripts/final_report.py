
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from datetime import datetime

config = BacktestConfig(
    initial_cash=10000,
    commission=0.001,
    slippage=0.0005,
    plot_results=False,
)

engine = BacktestEngine(config)
strategy = engine.load_strategy('cta')
result = engine.run_backtest(strategy, 'TON/USDT', '1h', days=365)

equity_dec = [Decimal(str(v)) for v in result.equity_curve]
report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))

wins = [t for t in result.trades if t['pnl'] > 0]
losses = [t for t in result.trades if t['pnl'] <= 0]

print("=" * 70)
print("       CRYPTOQUANT STRATEGY OPTIMIZATION - FINAL REPORT")
print("=" * 70)
print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"Exchange: OKX (Sandbox)")
print(f"Data Period: 365 days (1h candles)")
print()

print("-" * 70)
print("CONFIGURATION")
print("-" * 70)
print(f"Strategy: Trend Following (CTA)")
print(f"  - Fast MA: EMA(10)")
print(f"  - Slow MA: EMA(30)")
print(f"  - RSI Filter: Enabled (30/70)")
print(f"  - ADX Filter: Enabled (threshold: 25)")
print(f"  - ATR Exit: Enabled (Stop: 2x, Take: 3x)")
print(f"  - Regime Filter: Enabled")
print(f"Pair: TON/USDT")
print(f"Timeframe: 1h")
print(f"Initial Capital: $10,000.00")
print(f"Commission: 0.1%")
print(f"Slippage: 0.05%")
print()

print("-" * 70)
print("PERFORMANCE RESULTS")
print("-" * 70)
print(f"Final Value: ${result.final_value:,.2f}")
print(f"Total Return: {result.total_return:.2%}")
print(f"Total Trades: {len(result.trades)}")
print(f"  - Winning: {len(wins)} ({len(wins)/len(result.trades)*100:.1f}%)")
print(f"  - Losing: {len(losses)} ({len(losses)/len(result.trades)*100:.1f}%)")
print()

print("-" * 70)
print("RISK METRICS")
print("-" * 70)
print(f"Sharpe Ratio: {report['risk_metrics']['sharpe_ratio']:.3f}")
print(f"Max Drawdown: {report['risk_metrics']['max_drawdown_pct']:.1f}%")
print(f"Calmar Ratio: {report['risk_metrics']['calmar_ratio']:.3f}")
print(f"Volatility: {report['returns']['volatility_pct']:.1f}%")
print()

print("-" * 70)
print("TRADE METRICS")
print("-" * 70)
print(f"Win Rate: {report['trade_metrics']['win_rate_pct']:.1f}%")
print(f"Profit Factor: {report['trade_metrics']['profit_factor']:.3f}")
print(f"Avg Win: {sum(t['pnl'] for t in wins)/len(wins):.4f} ({sum(t['pnl'] for t in wins)/len(wins)*100:.2f}%)")
print(f"Avg Loss: {sum(t['pnl'] for t in losses)/len(losses):.4f} ({sum(t['pnl'] for t in losses)/len(losses)*100:.2f}%)")
print(f"Avg Trade: {report['trade_metrics']['average_trade_pnl']:.4f}")
print()

print("-" * 70)
print("THRESHOLD STATUS")
print("-" * 70)
print(f"Sharpe Ratio: {report['thresholds']['sharpe_ratio']['value']:.3f} >= {report['thresholds']['sharpe_ratio']['threshold']:.1f} -> {'PASS' if report['thresholds']['sharpe_ratio']['pass'] else 'FAIL'}")
print(f"Max Drawdown: {report['thresholds']['max_drawdown']['value']:.1%} <= {report['thresholds']['max_drawdown']['threshold']:.0%} -> {'PASS' if report['thresholds']['max_drawdown']['pass'] else 'FAIL'}")
print(f"Win Rate: {report['thresholds']['win_rate']['value']:.1%} >= {report['thresholds']['win_rate']['threshold']:.0%} -> {'PASS' if report['thresholds']['win_rate']['pass'] else 'FAIL'}")
print()

print("=" * 70)
if result.total_return >= 0.10:
    print(f" TARGET ACHIEVED: {result.total_return:.2%} return (>10% target)")
else:
    print(f" TARGET NOT MET: {result.total_return:.2%} return (<10% target)")
print("=" * 70)
