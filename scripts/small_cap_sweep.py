
"""
Comprehensive SmallCap strategy sweep across all pairs.
Tests SmallCapStrategy with different MA configs for $50 capital.
"""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from data.repository import get_repository
from strategy.cta.small_cap import SmallCapStrategy
from strategy.base import StrategyContext
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone, timedelta

repo = get_repository()

CAPITAL = Decimal('50')
COMM = Decimal('0.001')

def qty(cap, price):
    return max(1, int((cap*(1-COMM)/price).to_integral_value(rounding=ROUND_DOWN)))

# Pairs to test (with approx prices for reporting)
PAIRS = {
    'DOGE/USDT': 0.091,
    'TON/USDT': 1.90,
    'XPL/USDT': 0.091,
    'WLFI/USDT': 0.061,
    'BASED/USDT': 0.065,
    'CHZ/USDT': 0.030,
}

# Parameter grid
CONFIGS = [
    ("slow200/50",   {'trend_ma':200,'entry_ma':50,'min_hold_bars':48,'cooldown_bars':168}),
    ("vslow350/60",  {'trend_ma':350,'entry_ma':60,'min_hold_bars':72,'cooldown_bars':336}),
    ("mid100/30",    {'trend_ma':100,'entry_ma':30,'min_hold_bars':24,'cooldown_bars':96}),
    ("slow300/50",   {'trend_ma':300,'entry_ma':50,'min_hold_bars':48,'cooldown_bars':240}),
    ("vslow400/100", {'trend_ma':400,'entry_ma':100,'min_hold_bars':120,'cooldown_bars':504}),
]

print(f"{'='*75}")
print(f"  SMALL CAP STRATEGY SWEEP — ${float(CAPITAL):.0f} CAPITAL")
print(f"  Integer lots | 0.1% commission | Long-only golden cross")
print(f"{'='*75}")

since = int((datetime.now(timezone.utc)-timedelta(days=365)).timestamp()*1000)

for pair in PAIRS:
    candles = repo.load_candles(pair, '1h', since=since)
    if len(candles) < 500:
        print(f"\n{pair}: SKIP ({len(candles)} candles)")
        continue
    
    price = candles[-1].close
    q = qty(CAPITAL, price)
    print(f"\n  {pair} — ${float(price):.6f}, {q} tokens/${float(CAPITAL):.0f}")
    print(f"  {'Config':<18} {'Return':>8} {'Trades':>6} {'Comm%':>6} {'Final$':>8}")
    print(f"  {'-'*52}")
    
    best_ret = -999
    best_cfg = None
    
    for cname, params in CONFIGS:
        s = SmallCapStrategy(cname, params)
        s.initialize()
        
        cash = CAPITAL
        side = None
        sz = 0
        entry = Decimal('0')
        pnl = Decimal('0')
        tr = 0
        tcomm = Decimal('0')
        
        warmup = params['trend_ma'] + 10
        
        for i in range(warmup, len(candles)):
            c = candles[i]
            w = candles[max(0,i-600):i+1]
            
            ctx = StrategyContext(
                pair=pair, timeframe='1h',
                current_price=c.close, current_time=c.timestamp,
                closes_f=[float(x.close) for x in w],
                highs_f=[float(x.high) for x in w],
                lows_f=[float(x.low) for x in w],
            )
            
            sig = s.generate_signal(ctx).signal_type.name
            
            if sig == 'LONG' and side is None:
                sz = qty(cash, c.close)
                g = Decimal(str(sz)) * c.close
                co = g * COMM
                if g + co <= cash and sz > 0:
                    side = 'long'
                    entry = c.close
                    cash -= (g + co)
                    tcomm += co
                    tr += 1
            
            elif sig == 'CLOSE_LONG' and side == 'long':
                g = Decimal(str(sz)) * c.close
                co = g * COMM
                pnl += g - Decimal(str(sz)) * entry - co
                cash += g - co
                tcomm += co
                side = None
                tr += 1
        
        if side:
            last = candles[-1].close
            g = Decimal(str(sz)) * last
            co = g * COMM
            pnl += g - Decimal(str(sz)) * entry - co
            cash += g - co
        
        ret = float((cash + pnl - CAPITAL) / CAPITAL)
        final_val = float(cash + pnl)
        comm_pct = float(tcomm / CAPITAL * 100)
        
        if ret > best_ret:
            best_ret = ret
            best_cfg = cname
        
        marker = "***" if ret > 0.15 else "   "
        print(f"  {marker} {cname:<18} {ret:>+7.1%} {tr:>6} {comm_pct:>5.1f}% ${final_val:>7.2f}")
    
    print(f"  → Best: {best_cfg} ({best_ret:+.1%})")

print(f"\n{'='*75}")
print("  KEY: Trade frequency is the #1 factor for small capital.")
print(f"{'='*75}")
