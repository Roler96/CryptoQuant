"""Final optimized portfolio report."""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from datetime import datetime
from strategy.cta.trend_following import TrendFollowingStrategy

print("=" * 70)
print("  CRYPTOQUANT STRATEGY OPTIMIZATION - FINAL REPORT")
print("=" * 70)
print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"Exchange: OKX (Sandbox)")
print(f"Data Period: 365 days (1h candles)")
print(f"Initial Capital: $10,000.00")
print()

config_ton = BacktestConfig(initial_cash=8000, commission=0.001, slippage=0.0005, plot_results=False)
config_btc = BacktestConfig(initial_cash=2000, commission=0.001, slippage=0.0005, plot_results=False)

engine_ton = BacktestEngine(config_ton)
strategy_ton = TrendFollowingStrategy(name='ton', params={
    'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'sma',
})
ton_result = engine_ton.run_backtest(strategy_ton, 'TON/USDT', '1h', days=365)

engine_btc = BacktestEngine(config_btc)
strategy_btc = TrendFollowingStrategy(name='btc', params={
    'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'sma',
    'use_adx_filter': True, 'adx_threshold': 35, 'use_rsi_filter': False,
})
btc_result = engine_btc.run_backtest(strategy_btc, 'BTC/USDT', '1h', days=365)

total_final = ton_result.final_value + btc_result.final_value
portfolio_return = (total_final - 10000) / 10000

print("-" * 70)
print("ALLOCATION: 80% TON / 20% BTC")
print("-" * 70)
print()

print(f"TON/USDT ($8,000):")
print(f"  Return: {ton_result.total_return:+.1%} | Trades: {len(ton_result.trades)}")
ton_equity = [Decimal(str(v)) for v in ton_result.equity_curve]
ton_report = generate_performance_report(ton_result.trades, ton_equity, Decimal(str(ton_result.initial_value)))
print(f"  Win Rate: {ton_report['trade_metrics']['win_rate_pct']:.1f}% | PF: {ton_report['trade_metrics']['profit_factor']:.3f}")
print(f"  Max DD: {ton_report['risk_metrics']['max_drawdown_pct']:.1f}%")

print()
print(f"BTC/USDT ($2,000):")
print(f"  Return: {btc_result.total_return:+.1%} | Trades: {len(btc_result.trades)}")
btc_equity = [Decimal(str(v)) for v in btc_result.equity_curve]
btc_report = generate_performance_report(btc_result.trades, btc_equity, Decimal(str(btc_result.initial_value)))
print(f"  Win Rate: {btc_report['trade_metrics']['win_rate_pct']:.1f}% | PF: {btc_report['trade_metrics']['profit_factor']:.3f}")
print(f"  Max DD: {btc_report['risk_metrics']['max_drawdown_pct']:.1f}%")

print()
print("-" * 70)
print("PORTFOLIO: $10,000 -> ${:,.2f} ({:+.1%})".format(total_final, portfolio_return))
print("-" * 70)

if portfolio_return >= 0.10:
    print()
    print("=" * 70)
    print(f"  TARGET ACHIEVED: {portfolio_return:.1%} return (>= 10%)")
    print("=" * 70)
