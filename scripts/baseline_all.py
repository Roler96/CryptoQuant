
"""Baseline backtest: run all existing strategies on both pairs with 1 year of data."""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.trend_following import TrendFollowingStrategy
from strategy.cta.ma_state import MAStateStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)
engine = BacktestEngine(config)

strategies = [
    ("trend_default", TrendFollowingStrategy("trend_def", {})),
    ("trend_sma", TrendFollowingStrategy("trend_sma", {"ma_type": "sma"})),
    ("ma_state_def", MAStateStrategy("ma_def", {})),
    ("ma_state_60_350", MAStateStrategy("ma_60_350", {
        "fast_ma_period": 60, "slow_ma_period": 350,
        "ma_type": "sma", "use_stop_loss": False
    })),
    ("ma_state_20_50", MAStateStrategy("ma_20_50", {
        "fast_ma_period": 20, "slow_ma_period": 50,
        "ma_type": "sma", "use_stop_loss": False
    })),
    ("ma_state_10_30", MAStateStrategy("ma_10_30", {
        "fast_ma_period": 10, "slow_ma_period": 30,
        "ma_type": "ema", "use_stop_loss": False
    })),
]

pairs = ["BTC/USDT", "TON/USDT"]

print(f"{'Pair':>10} | {'Strategy':<20} | {'Return':>8} | {'Trades':>6} | {'Win%':>6} | {'PF':>6} | {'MDD':>7} | {'Sharpe':>7}")
print("-" * 95)

for pair in pairs:
    for sname, strategy in strategies:
        try:
            result = engine.run_backtest(strategy, pair, '1h', days=365)
            if result.error:
                print(f"{pair:>10} | {sname:<20} | ERROR: {result.error}")
                continue
            
            ret = result.total_return
            trades = len(result.trades) if result.trades else 0
            
            wr = 0
            pf = 0
            mdd = result.max_drawdown or 0
            sharpe = result.sharpe_ratio or 0
            
            if result.trades and result.equity_curve:
                try:
                    equity_dec = [Decimal(str(v)) for v in result.equity_curve]
                    report = generate_performance_report(result.trades, equity_dec, Decimal(str(result.initial_value)))
                    wr = (report['trade_metrics']['win_rate_pct'] or 0) / 100
                    pf = report['trade_metrics']['profit_factor'] or 0
                    mdd2 = (report['risk_metrics']['max_drawdown_pct'] or 0) / 100
                    if mdd2 > 0:
                        mdd = mdd2
                except:
                    pass
            
            if not mdd:
                mdd = result.max_drawdown or 0
            
            marker = "***" if ret > 0.10 else "   "
            print(f"{marker}{pair:>10} | {sname:<20} | {ret:>+7.1%} | {trades:>6} | {wr:>5.1%} | {pf:>5.2f} | {mdd:>6.1%} | {sharpe:>6.2f}")
            
        except Exception as e:
            print(f"{pair:>10} | {sname:<20} | EXC: {str(e)[:40]}")
    
    print("-" * 95)
