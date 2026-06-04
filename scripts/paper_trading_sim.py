
"""
End-to-end Paper Trading simulation over historical data.
Walks through all candles chronologically to simulate real trading.
"""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from data.repository import get_repository
from strategy.cta.ma_state import MAStateStrategy
from strategy.base import StrategyContext
from decimal import Decimal
from datetime import datetime, timezone

# Config: replicate production setup
BTC_CONFIG = {"fast_ma_period": 100, "slow_ma_period": 300, "ma_type": "sma", "use_stop_loss": False}
TON_CONFIG = {"fast_ma_period": 15, "slow_ma_period": 60, "ma_type": "sma", "use_stop_loss": False}

# Load strategies
btc_strat = MAStateStrategy("btc", BTC_CONFIG)
btc_strat.initialize()
ton_strat = MAStateStrategy("ton", TON_CONFIG)
ton_strat.initialize()

# Load data for last 365 days only (paper trading simulation)
repo = get_repository()
from datetime import datetime, timezone, timedelta
since_dt = datetime.now(timezone.utc) - timedelta(days=365)
since_ms = int(since_dt.timestamp() * 1000)
btc_candles = repo.load_candles("BTC/USDT", "1h", since=since_ms)
ton_candles = repo.load_candles("TON/USDT", "1h", since=since_ms)

print(f"BTC: {len(btc_candles)} candles, {btc_candles[0].iso_time[:10]} -> {btc_candles[-1].iso_time[:10]}")
print(f"TON: {len(ton_candles)} candles, {ton_candles[0].iso_time[:10]} -> {ton_candles[-1].iso_time[:10]}")

# Portfolio state
INITIAL_CAPITAL = Decimal("10000")
BTC_ALLOC = Decimal("0.20")  # 20%
TON_ALLOC = Decimal("0.80")  # 80%

btc_capital = INITIAL_CAPITAL * BTC_ALLOC
ton_capital = INITIAL_CAPITAL * TON_ALLOC

# Position tracking
class Position:
    def __init__(self):
        self.side = None
        self.size = Decimal("0")
        self.entry_price = Decimal("0")
        self.realized_pnl = Decimal("0")
        self.trades = 0
        
    def close(self, price: Decimal) -> Decimal:
        if self.side == "long":
            pnl = (price - self.entry_price) * self.size
        elif self.side == "short":
            pnl = (self.entry_price - price) * self.size
        else:
            return Decimal("0")
        self.realized_pnl += pnl
        self.side = None
        self.size = Decimal("0")
        return pnl

btc_pos = Position()
ton_pos = Position()
portfolio_cash = INITIAL_CAPITAL

# Simulation
warmup = max(BTC_CONFIG["slow_ma_period"], TON_CONFIG["slow_ma_period"]) + 10
btc_start = warmup
ton_start = warmup

# Align time ranges — use the overlapping period
# Find common start
btc_times = {c.timestamp for c in btc_candles}
ton_times = {c.timestamp for c in ton_candles}
common = sorted(btc_times & ton_times)

print(f"Common timestamps: {len(common)}")

if len(common) < warmup:
    print("Not enough overlapping data!")
    sys.exit(1)

# Walk through common timestamps
last_report = 0

for i, ts in enumerate(common):
    if i < warmup:
        continue
    
    # Find candles up to this timestamp
    btc_idx = next((j for j, c in enumerate(btc_candles) if c.timestamp == ts), None)
    ton_idx = next((j for j, c in enumerate(ton_candles) if c.timestamp == ts), None)
    
    if btc_idx is None or ton_idx is None:
        continue
    
    # BTC signal
    btc_window = btc_candles[max(0, btc_idx-500):btc_idx+1]
    btc_closes = [float(c.close) for c in btc_window]
    btc_highs = [float(c.high) for c in btc_window]
    btc_lows = [float(c.low) for c in btc_window]
    btc_price = btc_window[-1].close
    
    btc_ctx = StrategyContext(
        pair="BTC/USDT", timeframe="1h",
        current_price=btc_price, current_time=ts,
        closes_f=btc_closes, highs_f=btc_highs, lows_f=btc_lows,
    )
    btc_signal = btc_strat.generate_signal(btc_ctx)
    
    # TON signal
    ton_window = ton_candles[max(0, ton_idx-500):ton_idx+1]
    ton_closes = [float(c.close) for c in ton_window]
    ton_highs = [float(c.high) for c in ton_window]
    ton_lows = [float(c.low) for c in ton_window]
    ton_price = ton_window[-1].close
    
    ton_ctx = StrategyContext(
        pair="TON/USDT", timeframe="1h",
        current_price=ton_price, current_time=ts,
        closes_f=ton_closes, highs_f=ton_highs, lows_f=ton_lows,
    )
    ton_signal = ton_strat.generate_signal(ton_ctx)
    
    # Process BTC
    btc_sig = btc_signal.signal_type.name
    if btc_sig in ("LONG", "SHORT") and btc_pos.side is None:
        btc_pos.side = "long" if btc_sig == "LONG" else "short"
        position_value = btc_capital * Decimal("0.95")
        btc_pos.size = position_value / btc_price
        btc_pos.entry_price = btc_price
        btc_pos.trades += 1
    elif btc_sig in ("CLOSE_LONG", "CLOSE_SHORT") and btc_pos.side:
        expected = "long" if btc_sig == "CLOSE_LONG" else "short"
        if btc_pos.side == expected:
            pnl = btc_pos.close(btc_price)
            portfolio_cash += pnl
    
    # Process TON
    ton_sig = ton_signal.signal_type.name
    if ton_sig in ("LONG", "SHORT") and ton_pos.side is None:
        ton_pos.side = "long" if ton_sig == "LONG" else "short"
        position_value = ton_capital * Decimal("0.95")
        ton_pos.size = position_value / ton_price
        ton_pos.entry_price = ton_price
        ton_pos.trades += 1
    elif ton_sig in ("CLOSE_LONG", "CLOSE_SHORT") and ton_pos.side:
        expected = "long" if ton_sig == "CLOSE_LONG" else "short"
        if ton_pos.side == expected:
            pnl = ton_pos.close(ton_price)
            portfolio_cash += pnl
    
    # Report every 1000 bars
    if i - last_report >= 1000:
        date_str = datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime('%Y-%m-%d')
        btc_pos_str = f"{btc_pos.side.upper()}" if btc_pos.side else "FLAT"
        ton_pos_str = f"{ton_pos.side.upper()}" if ton_pos.side else "FLAT"
        total_pnl = btc_pos.realized_pnl + ton_pos.realized_pnl
        total_equity = portfolio_cash + total_pnl
        ret = float((total_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL)
        print(f"  {date_str} | BTC: {btc_pos_str:>5} PnL=${float(btc_pos.realized_pnl):>+8.2f} | "
              f"TON: {ton_pos_str:>5} PnL=${float(ton_pos.realized_pnl):>+9.2f} | "
              f"Total: ${float(total_equity):>10,.2f} ({ret:>+6.1%})")
        last_report = i

# Final report
total_pnl = btc_pos.realized_pnl + ton_pos.realized_pnl
total_equity = portfolio_cash + total_pnl
total_return = float((total_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL)

print(f"\n{'='*70}")
print(f"  PAPER TRADING FINAL REPORT")
print(f"  Period: {datetime.fromtimestamp(common[warmup]/1000).strftime('%Y-%m-%d')} -> "
      f"{datetime.fromtimestamp(common[-1]/1000).strftime('%Y-%m-%d')}")
print(f"  BTC: {btc_pos.trades} trades, PnL=${float(btc_pos.realized_pnl):+,.2f}")
print(f"  TON: {ton_pos.trades} trades, PnL=${float(ton_pos.realized_pnl):+,.2f}")
print(f"  Total: ${float(INITIAL_CAPITAL):,.0f} -> ${float(total_equity):,.2f} ({total_return:+.2%})")
print(f"{'='*70}")
