
"""Smoke test for ProductionRunner."""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from live.runner import ProductionRunner
from strategy.base import StrategyContext

runner = ProductionRunner(mode='paper')
if runner.initialize():
    print("\n=== INIT OK ===")
    
    # Manual tick test for both pairs
    for pair, (strategy, sc) in runner.strategies.items():
        closes, highs, lows, price, timestamp = runner._get_candles(pair)
        
        context = StrategyContext(
            pair=pair,
            timeframe=runner.data_config['timeframe'],
            current_price=price,
            positions={},
            balances={'USDT': runner.portfolio.current_capital},
            candles=[],
            current_time=timestamp,
            closes_f=closes,
            highs_f=highs,
            lows_f=lows,
        )
        
        signal = strategy.generate_signal(context)
        print(f"  {pair}: signal={signal.signal_type.name}, price=${float(price):.4f}")
        if not signal.is_hold():
            trade = runner._process_signal(pair, signal)
            if trade:
                print(f"    -> {trade['action']} qty={trade['quantity']:.6f} @ ${trade['price']:.2f}")
        
        state = runner.pair_states[pair]
        pos = f"{state.position_side} size={float(state.position_size):.4f}" if state.position_side else "FLAT"
        print(f"    position={pos}")
    
    print(f"\nPortfolio: ${float(runner.portfolio.current_capital):,.2f}")
    
print("DONE")
