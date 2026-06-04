
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.trend_following import TrendFollowingStrategy, TrendFollowingConfig

config = BacktestConfig(
    initial_cash=10000,
    commission=0.001,
    slippage=0.0005,
    plot_results=False,
)

pairs = ['BTC/USDT', 'TON/USDT']
timeframes = ['1h', '4h']

# Parameter grid
param_sets = [
    {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'sma', 'name': 'default_sma'},
    {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'ema', 'name': 'default_ema'},
    {'fast_ma_period': 5, 'slow_ma_period': 20, 'ma_type': 'ema', 'name': 'fast_ema'},
    {'fast_ma_period': 20, 'slow_ma_period': 50, 'ma_type': 'ema', 'name': 'slow_ema'},
    {'fast_ma_period': 8, 'slow_ma_period': 21, 'ma_type': 'ema', 'name': 'fib_ema'},
    {'fast_ma_period': 12, 'slow_ma_period': 26, 'ma_type': 'ema', 'name': 'macd_ema'},
    {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'ema', 'use_rsi_filter': False, 'name': 'no_rsi'},
    {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'ema', 'use_adx_filter': False, 'name': 'no_adx'},
    {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'ema', 'use_atr_exit': False, 'name': 'no_atr'},
    {'fast_ma_period': 10, 'slow_ma_period': 30, 'ma_type': 'ema', 'use_regime_filter': False, 'name': 'no_regime'},
    {'fast_ma_period': 7, 'slow_ma_period': 25, 'ma_type': 'ema', 'name': 'balanced_ema'},
    {'fast_ma_period': 15, 'slow_ma_period': 40, 'ma_type': 'ema', 'name': 'medium_ema'},
]

print("=" * 100)
print(f"{'Parameters':<20} | {'Pair':<12} | {'TF':<4} | {'Return':>8} | {'Trades':>6} | {'Win%':>6} | {'PF':>6} | {'MaxDD':>7} | {'Sharpe':>7}")
print("=" * 100)

results = []

for params in param_sets:
    param_name = params.pop('name')
    
    for pair in pairs:
        for tf in timeframes:
            try:
                engine = BacktestEngine(config)
                
                # Build strategy with custom params
                strat_params = params.copy()
                strategy = TrendFollowingStrategy(name=param_name, params=strat_params)
                
                result = engine.run_backtest(strategy, pair, tf, days=365)
                
                if result.equity_curve and result.trades:
                    equity_dec = [Decimal(str(v)) for v in result.equity_curve]
                    report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
                    
                    ret = result.total_return
                    trades = len(result.trades)
                    wr = report['trade_metrics']['win_rate_pct'] / 100 if report['trade_metrics']['win_rate_pct'] else 0
                    pf = report['trade_metrics']['profit_factor'] or 0
                    mdd = report['risk_metrics']['max_drawdown_pct'] / 100 if report['risk_metrics']['max_drawdown_pct'] else 0
                    sharpe = report['risk_metrics']['sharpe_ratio'] or 0
                    
                    # Color coding
                    ret_str = f"{ret:+.1%}"
                    if ret >= 0.10:
                        ret_str = f"***{ret_str}"
                    
                    print(f"{param_name:<20} | {pair:<12} | {tf:<4} | {ret_str:>8} | {trades:>6} | {wr:>5.1%} | {pf:>5.2f} | {mdd:>6.1%} | {sharpe:>6.3f}")
                    
                    results.append({
                        'params': param_name,
                        'pair': pair,
                        'tf': tf,
                        'return': ret,
                        'trades': trades,
                        'win_rate': wr,
                        'profit_factor': pf,
                        'max_dd': mdd,
                        'sharpe': sharpe,
                    })
            except Exception as e:
                print(f"{param_name:<20} | {pair:<12} | {tf:<4} | ERROR: {str(e)[:30]}")

# Find best combined results
print("\n" + "=" * 100)
print("BEST COMBINATIONS (both pairs > 5% return):")
print("=" * 100)

btc_results = {r['params'] + '_' + r['tf']: r for r in results if r['pair'] == 'BTC/USDT'}
ton_results = {r['params'] + '_' + r['tf']: r for r in results if r['pair'] == 'TON/USDT'}

for key in btc_results:
    if key in ton_results:
        btc = btc_results[key]
        ton = ton_results[key]
        avg_return = (btc['return'] + ton['return']) / 2
        if btc['return'] > 0.05 and ton['return'] > 0.05:
            print(f"*** {key}: BTC={btc['return']:.1%}, TON={ton['return']:.1%}, Avg={avg_return:.1%}")
        elif btc['return'] > 0 and ton['return'] > 0:
            print(f"    {key}: BTC={btc['return']:.1%}, TON={ton['return']:.1%}, Avg={avg_return:.1%}")
