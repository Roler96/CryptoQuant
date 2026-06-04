
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.trend_following import TrendFollowingStrategy

# Extensive parameter search for BTC
btc_params = [
    {'fast_ma_period': 5, 'slow_ma_period': 15, 'ma_type': 'ema', 'use_rsi_filter': False, 'name': 'btc_fast5_ema15'},
    {'fast_ma_period': 5, 'slow_ma_period': 20, 'ma_type': 'ema', 'use_rsi_filter': False, 'name': 'btc_fast5_ema20'},
    {'fast_ma_period': 3, 'slow_ma_period': 10, 'ma_type': 'ema', 'use_rsi_filter': False, 'name': 'btc_fast3_ema10'},
    {'fast_ma_period': 8, 'slow_ma_period': 34, 'ma_type': 'ema', 'use_rsi_filter': False, 'name': 'btc_fib8_34'},
    {'fast_ma_period': 13, 'slow_ma_period': 48, 'ma_type': 'ema', 'use_rsi_filter': False, 'name': 'btc_fib13_48'},
    {'fast_ma_period': 20, 'slow_ma_period': 60, 'ma_type': 'sma', 'use_rsi_filter': False, 'name': 'btc_sma20_60'},
    {'fast_ma_period': 50, 'slow_ma_period': 200, 'ma_type': 'sma', 'use_rsi_filter': False, 'name': 'btc_sma50_200'},
    {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'ema', 'use_rsi_filter': False, 'use_adx_filter': False, 'use_atr_exit': False, 'use_regime_filter': False, 'name': 'btc_plain_ema'},
    {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'ema', 'use_rsi_filter': False, 'use_adx_filter': True, 'adx_threshold': 20, 'name': 'btc_adx20'},
    {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'ema', 'use_rsi_filter': False, 'use_adx_filter': True, 'adx_threshold': 35, 'name': 'btc_adx35'},
    {'fast_ma_period': 20, 'slow_ma_period': 50, 'ma_type': 'ema', 'use_rsi_filter': False, 'name': 'btc_ema20_50'},
    {'fast_ma_period': 12, 'slow_ma_period': 35, 'ma_type': 'ema', 'use_rsi_filter': False, 'name': 'btc_ema12_35'},
]

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

print("=" * 80)
print(f"{'Params':<25} | {'Return':>8} | {'Trades':>6} | {'Win%':>6} | {'PF':>6} | {'MaxDD':>7}")
print("=" * 80)

btc_results = []

for params in btc_params:
    name = params.pop('name')
    try:
        engine = BacktestEngine(config)
        strategy = TrendFollowingStrategy(name=name, params=params)
        result = engine.run_backtest(strategy, 'BTC/USDT', '1h', days=365)
        
        if result.equity_curve and result.trades:
            equity_dec = [Decimal(str(v)) for v in result.equity_curve]
            report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
            
            ret = result.total_return
            trades = len(result.trades)
            wr = report['trade_metrics']['win_rate_pct'] / 100 if report['trade_metrics']['win_rate_pct'] else 0
            pf = report['trade_metrics']['profit_factor'] or 0
            mdd = report['risk_metrics']['max_drawdown_pct'] / 100 if report['risk_metrics']['max_drawdown_pct'] else 0
            
            marker = "***" if ret > -0.15 else ""
            print(f"{marker}{name:<25} | {ret:>+7.1%} | {trades:>6} | {wr:>5.1%} | {pf:>5.2f} | {mdd:>6.1%}")
            
            btc_results.append({
                'name': name,
                'params': params,
                'return': ret,
                'trades': trades,
                'win_rate': wr,
                'profit_factor': pf,
                'max_dd': mdd,
            })
    except Exception as e:
        print(f"{name:<25} | ERROR: {str(e)[:30]}")

# Sort by return
btc_results.sort(key=lambda x: x['return'], reverse=True)
print("\n" + "=" * 80)
print("TOP 5 BTC CONFIGURATIONS:")
print("=" * 80)
for i, r in enumerate(btc_results[:5]):
    print(f"{i+1}. {r['name']}: {r['return']:+.1%} (Trades: {r['trades']}, Win%: {r['win_rate']:.0%}, PF: {r['profit_factor']:.2f})")
