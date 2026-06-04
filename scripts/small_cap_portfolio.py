
"""Small-cap portfolio combinations for $50-$100 capital."""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from data.repository import get_repository
from strategy.cta.small_cap import SmallCapStrategy
from strategy.base import StrategyContext
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone, timedelta

repo = get_repository()
COMM = Decimal('0.001')

def qty(cap, price):
    return max(1, int((cap*(1-COMM)/price).to_integral_value(rounding=ROUND_DOWN)))

def run_backtest(pair, capital, params):
    """Run single-pair backtest. Returns (final_value, trades, comm_pct)."""
    since = int((datetime.now(timezone.utc)-timedelta(days=365)).timestamp()*1000)
    candles = repo.load_candles(pair, '1h', since=since)
    
    s = SmallCapStrategy(pair, params)
    s.initialize()
    
    cash = capital
    side = None
    sz = 0
    entry = Decimal('0')
    pnl = Decimal('0')
    tr = 0
    tcomm = Decimal('0')
    
    warmup = params.get('trend_ma', 200) + 10
    
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
    
    final = cash + pnl
    ret = float((final - capital) / capital)
    comm_pct = float(tcomm / capital * 100)
    return final, ret, tr, comm_pct

# Best per-pair params (from sweep)
BEST_PARAMS = {
    'TON/USDT':   {'trend_ma':400,'entry_ma':100,'min_hold_bars':120,'cooldown_bars':504},
    'BASED/USDT': {'trend_ma':200,'entry_ma':50,'min_hold_bars':48,'cooldown_bars':168},
    'XPL/USDT':   {'trend_ma':300,'entry_ma':50,'min_hold_bars':48,'cooldown_bars':240},
    'DOGE/USDT':  {'trend_ma':350,'entry_ma':60,'min_hold_bars':72,'cooldown_bars':336},
}

print(f"{'='*70}")
print(f"  SMALL CAP PORTFOLIO OPTIMIZATION")
print(f"{'='*70}")

for label, total_capital in [("$50", Decimal('50')), ("$100", Decimal('100'))]:
    print(f"\n--- {label} CAPITAL ---")
    print(f"  {'Strategy':<30} {'Return':>8} {'Trades':>6} {'Comm%':>6} {'Final$':>9}")
    print(f"  {'-'*65}")
    
    # 1. Single best pair
    for pair, params in BEST_PARAMS.items():
        cap = total_capital
        final, ret, tr, cp = run_backtest(pair, cap, params)
        m = "***" if ret > 0.5 else "   "
        print(f"  {m} {pair:<30} {ret:>+7.1%} {tr:>6} {cp:>5.1f}% ${float(final):>8.2f}")
    
    # 2. Portfolio combinations
    if total_capital >= 50:
        combos = [
            ("TON+BASED 50/50", [('TON/USDT', total_capital/2), ('BASED/USDT', total_capital/2)]),
            ("TON+XPL 50/50", [('TON/USDT', total_capital/2), ('XPL/USDT', total_capital/2)]),
            ("TON+BASED+XPL 40/30/30", [
                ('TON/USDT', total_capital*Decimal('0.4')),
                ('BASED/USDT', total_capital*Decimal('0.3')),
                ('XPL/USDT', total_capital*Decimal('0.3')),
            ]),
        ]
        
        for cname, allocations in combos:
            total_final = Decimal('0')
            total_tr = 0
            total_comm = Decimal('0')
            for pair, cap in allocations:
                final, ret, tr, cp = run_backtest(pair, cap, BEST_PARAMS[pair])
                total_final += final
                total_tr += tr
                total_comm += Decimal(str(cp/100)) * cap
            
            portfolio_ret = float((total_final - total_capital) / total_capital)
            total_cp = float(total_comm / total_capital * 100)
            m = "***" if portfolio_ret > 0.5 else "   "
            print(f"  {m} {cname:<30} {portfolio_ret:>+7.1%} {total_tr:>6} {total_cp:>5.1f}% ${float(total_final):>8.2f}")

print(f"\n{'='*70}")
print(f"  RECOMMENDATION: TON-only for max return. TON+BASED for lower risk.")
print(f"{'='*70}")
