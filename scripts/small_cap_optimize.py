
"""
Small Capital Strategy Optimizer ($10-$500).
Key differences from regular trading:
1. Integer position sizing (can't buy fractional tokens)
2. Higher commission impact (use configured rate, typically 0.1%)
3. Minimum order value check ($10 on OKX)
4. Fewer pairs — diversification impossible with tiny capital
"""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from data.repository import get_repository
from strategy.cta.ma_state import MAStateStrategy
from strategy.base import StrategyContext
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone, timedelta

repo = get_repository()

# --- Configuration ---
CAPITAL = Decimal("50")  # Test with $50
COMMISSION = Decimal("0.001")  # 0.1% per trade
SLIPPAGE = Decimal("0.0005")   # 0.05%
MIN_ORDER_VALUE = Decimal("10")  # OKX minimum

# Candidate pairs
SMALL_CAP_PAIRS = [
    ("DOGE/USDT", 0.091),   # ~$0.09
    ("XPL/USDT", 0.091),    # ~$0.09
    ("WLFI/USDT", 0.061),   # ~$0.06
    ("BASED/USDT", 0.065),  # ~$0.06
    ("CHZ/USDT", 0.030),    # ~$0.03
]

# --- Position Sizing ---

def calc_quantity(capital: Decimal, price: Decimal) -> int:
    """Calculate integer token quantity for small capital."""
    # Reserve 0.2% for commission (buy+sell)
    usable = capital * (Decimal("1") - COMMISSION * Decimal("2"))
    raw_qty = usable / price
    qty = int(raw_qty.to_integral_value(rounding=ROUND_DOWN))
    return max(qty, 1)

def calc_cost(quantity: int, price: Decimal) -> Decimal:
    """Total cost including commission."""
    gross = Decimal(str(quantity)) * price
    return gross * (Decimal("1") + COMMISSION)

# --- Quick inventory check ---

print("Checking available data...")
available_pairs = []
for pair, _ in SMALL_CAP_PAIRS:
    candles = repo.load_candles(pair, "1h", limit=100)
    if len(candles) >= 100:
        available_pairs.append(pair)
        print(f"  {pair:<16} ✓ ({len(candles)} recent candles)")
    else:
        print(f"  {pair:<16} ✗ (only {len(candles)} candles)")

if not available_pairs:
    print("\nNo data yet — download in progress. Testing with existing pairs...")
    available_pairs = ["TON/USDT"]  # Fallback

print(f"\n{'='*65}")
print(f"  SMALL CAPITAL STRATEGY TEST — ${float(CAPITAL):.0f} CAPITAL")
print(f"{'='*65}")

for pair in available_pairs:
    # Get price
    candles = repo.load_candles(pair, "1h", limit=500)
    if len(candles) < 300:
        continue
    
    price = candles[-1].close
    qty = calc_quantity(CAPITAL, price)
    cost = calc_cost(qty, price)
    
    print(f"\n  {pair}:")
    print(f"    Price: ${float(price):.6f}")
    print(f"    ${float(CAPITAL):.0f} buys: {qty} tokens (cost: ${float(cost):.2f})")
    print(f"    Min price move to profit: ${float(price * COMMISSION * 3):.6f} (3x commission)")
    
    # Check if meets minimum order
    if cost < MIN_ORDER_VALUE:
        print(f"    ⚠ UNDER MIN ORDER ({float(cost):.2f} < {float(MIN_ORDER_VALUE)})")

# --- Run backtest for available pairs ---

print(f"\n{'='*65}")
print(f"  BACKTEST: Small Capital MA State Strategy")
print(f"  Capital: ${float(CAPITAL):.0f} | Integer lots | 0.1% commission")
print(f"{'='*65}")

# Focus on pairs where we have data
for pair in available_pairs:
    candles_all = repo.load_candles(pair, "1h")
    if len(candles_all) < 1000:
        print(f"  {pair}: SKIP (only {len(candles_all)} candles)")
        continue
    
    # Use last 365 days
    since_dt = datetime.now(timezone.utc) - timedelta(days=365)
    since_ms = int(since_dt.timestamp() * 1000)
    candles = repo.load_candles(pair, "1h", since=since_ms)
    
    if len(candles) < 500:
        print(f"  {pair}: SKIP (only {len(candles)} candles in last year)")
        continue
    
    # Test different MA configurations for small cap
    configs = [
        ("sma(15,60)", 15, 60, "sma"),
        ("sma(20,50)", 20, 50, "sma"),
        ("sma(10,30)", 10, 30, "sma"),
        ("sma(30,120)", 30, 120, "sma"),
        ("sma(50,200)", 50, 200, "sma"),
    ]
    
    best_return = -999
    best_config = None
    
    for name, fast, slow, ma_type in configs:
        strategy = MAStateStrategy(f"sc_{fast}_{slow}", {
            "fast_ma_period": fast, "slow_ma_period": slow,
            "ma_type": ma_type, "use_stop_loss": False,
        })
        strategy.initialize()
        
        # Walk-through simulation with integer lots
        cash = CAPITAL
        pos_side = None
        pos_qty = 0
        pos_entry = Decimal("0")
        realized_pnl = Decimal("0")
        trades = 0
        
        warmup = slow + 10
        
        for i in range(warmup, len(candles)):
            c = candles[i]
            window = candles[max(0, i-500):i+1]
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
            
            # Entry
            if sig in ("LONG", "SHORT") and pos_side is None:
                qty = calc_quantity(cash, c.close)
                entry_cost = calc_cost(qty, c.close)
                if entry_cost <= cash and qty > 0:
                    pos_side = "long" if sig == "LONG" else "short"
                    pos_qty = qty
                    pos_entry = c.close
                    cash -= entry_cost
                    trades += 1
            
            # Exit
            elif sig in ("CLOSE_LONG", "CLOSE_SHORT") and pos_side:
                expected = "long" if sig == "CLOSE_LONG" else "short"
                if pos_side == expected:
                    gross = Decimal(str(pos_qty)) * c.close
                    commission_cost = gross * COMMISSION
                    if pos_side == "long":
                        pnl = gross - (Decimal(str(pos_qty)) * pos_entry) - commission_cost * Decimal("2")
                    else:
                        pnl = (Decimal(str(pos_qty)) * pos_entry) - gross - commission_cost * Decimal("2")
                    realized_pnl += pnl
                    cash += gross - commission_cost
                    pos_side = None
                    pos_qty = 0
                    trades += 1
        
        # Close any open position at last price
        if pos_side and pos_qty > 0:
            last_price = candles[-1].close
            gross = Decimal(str(pos_qty)) * last_price
            commission_cost = gross * COMMISSION
            if pos_side == "long":
                pnl = gross - (Decimal(str(pos_qty)) * pos_entry) - commission_cost * Decimal("2")
            else:
                pnl = (Decimal(str(pos_qty)) * pos_entry) - gross - commission_cost * Decimal("2")
            realized_pnl += pnl
            cash += gross - commission_cost
        
        total_return = float((cash + realized_pnl - CAPITAL) / CAPITAL)
        
        if total_return > best_return:
            best_return = total_return
            best_config = name
        
        marker = "***" if total_return > 0.3 else "   "
        print(f"  {marker} {pair:<14} {name:<15} {total_return:>+7.1%} {trades:>4} trades")
    
    if best_config:
        print(f"  → Best: {best_config} ({best_return:+.1%})")

print("\nDONE")
