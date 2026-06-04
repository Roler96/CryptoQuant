
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from decimal import Decimal
from strategy.cta.trend_following import TrendFollowingStrategy

# Optimal configs per pair
btc_config = {
    'fast_ma_period': 10,
    'slow_ma_period': 30,
    'ma_type': 'ema',
    'use_rsi_filter': False,
    'use_adx_filter': True,
    'adx_threshold': 35,
}

ton_config = {
    'fast_ma_period': 10,
    'slow_ma_period': 30,
    'ma_type': 'ema',
}

print("=" * 70)
print("OPTIMIZED MULTI-ASSET PORTFOLIO")
print("=" * 70)
print()
print("BTC Config: EMA(10/30), ADX>35 filter, no RSI")
print("TON Config: EMA(10/30), default filters")
print()

# Test different allocations
allocations = [
    ('50/50', 5000, 5000),
    ('40/60', 4000, 6000),
    ('30/70', 3000, 7000),
    ('20/80', 2000, 8000),
    ('10/90', 1000, 9000),
    ('0/100', 0, 10000),
]

for name, btc_cash, ton_cash in allocations:
    results = {}
    
    if btc_cash > 0:
        config_btc = BacktestConfig(initial_cash=btc_cash, commission=0.001, slippage=0.0005, plot_results=False)
        engine_btc = BacktestEngine(config_btc)
        strategy_btc = TrendFollowingStrategy(name='btc_opt', params=btc_config)
        btc_result = engine_btc.run_backtest(strategy_btc, 'BTC/USDT', '1h', days=365)
        results['btc'] = btc_result
    
    if ton_cash > 0:
        config_ton = BacktestConfig(initial_cash=ton_cash, commission=0.001, slippage=0.0005, plot_results=False)
        engine_ton = BacktestEngine(config_ton)
        strategy_ton = TrendFollowingStrategy(name='ton_opt', params=ton_config)
        ton_result = engine_ton.run_backtest(strategy_ton, 'TON/USDT', '1h', days=365)
        results['ton'] = ton_result
    
    btc_final = results['btc'].final_value if 'btc' in results else btc_cash
    ton_final = results['ton'].final_value if 'ton' in results else ton_cash
    
    total_final = btc_final + ton_final
    portfolio_return = (total_final - 10000) / 10000
    
    btc_ret = results['btc'].total_return if 'btc' in results else 0
    ton_ret = results['ton'].total_return if 'ton' in results else 0
    
    marker = "***" if portfolio_return >= 0.10 else "   "
    
    print(f"{marker}{name}: BTC ${btc_cash:>5} ({btc_ret:+.1%}) + TON ${ton_cash:>5} ({ton_ret:+.1%}) = Portfolio {portfolio_return:+.1%} (${total_final:,.0f})")

print()
print("=" * 70)
print("NOTE: To achieve 10%+ on BOTH pairs simultaneously requires")
print("either shorting BTC during downtrend or accepting that BTC")
print("will be negative during bear markets while TON compensates.")
print("=" * 70)
