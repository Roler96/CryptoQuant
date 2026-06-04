
"""Test SmallCapStrategy on available pairs with integer position sizing."""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from data.repository import get_repository
from strategy.cta.small_cap import SmallCapStrategy
from strategy.base import StrategyContext
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone, timedelta

repo = get_repository()

CAPITAL = Decimal("50")
COMMISSION = Decimal("0.001")

def calc_quantity(capital: Decimal, price: Decimal) -> int:
    usable = capital * (Decimal("1") - COMMISSION)
    return max(1, int((usable / price).to_integral_value(rounding=ROUND_DOWN)))

# Test with TON first (only available data)
for pair in ["TON/USDT"]:
    candles_all = repo.load_candles(pair, "1h")
    
    # Test different time windows
    for label, days in [("1y", 365), ("2y", 730), ("all", None)]:
        if days:
            since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
            candles = repo.load_candles(pair, "1h", since=since)
        else:
            candles = candles_all
        
        if len(candles) < 300:
            continue
        
        # Test strategy variants
        configs = [
            ("default", {"trend_ma": 200, "entry_ma": 50}),
            ("fast", {"trend_ma": 100, "entry_ma": 20, "min_hold_bars": 24, "cooldown_bars": 72}),
            ("slow", {"trend_ma": 350, "entry_ma": 60, "min_hold_bars": 72, "cooldown_bars": 336}),
            ("very_slow", {"trend_ma": 400, "entry_ma": 100, "min_hold_bars": 120, "min_profit_pct": 0.08}),
        ]
        
        for cname, params in configs:
            strategy = SmallCapStrategy(f"sc_{cname}", params)
            strategy.initialize()
            
            cash = CAPITAL
            pos_side = None
            pos_qty = 0
            pos_entry = Decimal("0")
            realized_pnl = Decimal("0")
            trades = 0
            total_commission = Decimal("0")
            
            warmup = params.get("trend_ma", 200) + 10
            
            for i in range(warmup, len(candles)):
                c = candles[i]
                window = candles[max(0, i-600):i+1]
                closes = [float(x.close) for x in window]
                highs = [float(x.high) for x in window]
                lows = [float(x.low) for x in window]
                
                ctx = StrategyContext(
                    pair=pair, timeframe="1h",
                    current_price=c.close, current_time=c.timestamp,
                    closes_f=closes, highs_f=highs, lows_f=lows,
                )
                
                signal = strategy.generate_signal(ctx)
                sig = signal.signal_type.name
                
                if sig == "LONG" and pos_side is None:
                    qty = calc_quantity(cash, c.close)
                    gross = Decimal(str(qty)) * c.close
                    comm = gross * COMMISSION
                    if (gross + comm) <= cash and qty > 0:
                        pos_side = "long"
                        pos_qty = qty
                        pos_entry = c.close
                        cash -= (gross + comm)
                        total_commission += comm
                        trades += 1
                
                elif sig == "CLOSE_LONG" and pos_side == "long":
                    gross = Decimal(str(pos_qty)) * c.close
                    comm = gross * COMMISSION
                    pnl = gross - (Decimal(str(pos_qty)) * pos_entry) - comm
                    realized_pnl += pnl
                    cash += gross - comm
                    total_commission += comm
                    pos_side = None
                    pos_qty = 0
                    trades += 1
            
            # Close open position
            if pos_side and pos_qty > 0:
                last = candles[-1].close
                gross = Decimal(str(pos_qty)) * last
                comm = gross * COMMISSION
                pnl = gross - (Decimal(str(pos_qty)) * pos_entry) - comm
                realized_pnl += pnl
                cash += gross - comm
                total_commission += comm
            
            total = cash + realized_pnl
            ret = float((total - CAPITAL) / CAPITAL)
            comm_pct = float(total_commission / CAPITAL * 100)
            
            marker = "***" if ret > 0.15 else "   "
            print(f"  {marker} {pair:<12} {label:<4} {cname:<12} {ret:>+7.1%} "
                  f"{trades:>3} trades  comm={comm_pct:.1f}%  final=${float(total):.2f}")
        
        print()

print("DONE")
print("KEY: Fewer trades + lower commission % = better small-cap performance")
