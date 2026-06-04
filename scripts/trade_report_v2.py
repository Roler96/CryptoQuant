
"""
Trade report using BacktestEngine (authoritative) + manual SmallCap walk-through.
"""
import sys, csv
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from backtest.engine import BacktestEngine, BacktestConfig
from strategy.cta.ma_state import MAStateStrategy
from strategy.cta.small_cap import SmallCapStrategy
from strategy.base import StrategyContext
from data.repository import get_repository
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone, timedelta

repo = get_repository()
COMM = Decimal('0.001')

def qty(cap, price, min_qty=1):
    usable = cap * (Decimal('1') - COMM)
    return max(min_qty, int((usable / price).to_integral_value(rounding=ROUND_DOWN)))

def ts_to_dt(ms):
    return datetime.fromtimestamp(ms/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')

def write_csv_md(trades, label, capital, pair, output_dir):
    """Write CSV and MD from trades list."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    base = f"{output_dir}/{label.replace(' ', '_').replace('/', '_')}_{ts}"
    
    total_pnl = sum(t['pnl'] for t in trades)
    total_comm = sum(t['commission'] for t in trades)
    final = capital + Decimal(str(total_pnl))
    ret = float((final - capital) / capital)
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]
    wr = len(wins)/len(trades)*100 if trades else 0
    
    # CSV
    csv_path = f"{base}.csv"
    with open(csv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['#','Entry Time','Exit Time','Side','Qty','Entry Price','Exit Price',
                     'Commission','PnL','PnL%','Hold Hours'])
        for i, t in enumerate(trades, 1):
            w.writerow([i, ts_to_dt(t['entry_time']), ts_to_dt(t['exit_time']),
                       t['side'], t['quantity'],
                       f"{t['entry_price']:.6f}", f"{t['exit_price']:.6f}",
                       f"{t['commission']:.4f}", f"{t['pnl']:.2f}",
                       f"{t['pnl_pct']:.2f}%", f"{t['hold_hours']:.1f}"])
    
    # MD
    md_path = f"{base}.md"
    with open(md_path, 'w') as f:
        f.write(f"# {label}\n\n")
        f.write(f"**{pair}** | 1h | ${float(capital):.2f} → ${float(final):.2f} | {ret:+.2%}\n\n")
        f.write(f"| 胜率 | 平均盈利 | 平均亏损 | 总佣金 |\n")
        avg_w = sum(t['pnl'] for t in wins)/len(wins) if wins else 0
        avg_l = sum(t['pnl'] for t in losses)/len(losses) if losses else 0
        f.write(f"|------|----------|----------|--------|\n")
        f.write(f"| {wr:.0f}% ({len(wins)}/{len(trades)}) | ${avg_w:+.2f} | ${avg_l:+.2f} | ${float(total_comm):.2f} |\n\n")
        f.write(f"| # | 入场 | 出场 | 方向 | 数量 | 入场价 | 出场价 | 佣金 | 盈亏 | 盈亏% | 持仓(h) |\n")
        f.write(f"|---|------|------|------|------|--------|--------|------|------|-------|----------|\n")
        for i, t in enumerate(trades, 1):
            emoji = '📈' if t['side'] == 'LONG' else '📉'
            f.write(f"| {i} | {ts_to_dt(t['entry_time'])} | {ts_to_dt(t['exit_time'])} | "
                   f"{emoji} | {t['quantity']} | ${t['entry_price']:.4f} | ${t['exit_price']:.4f} | "
                   f"${t['commission']:.4f} | ${t['pnl']:+.2f} | {t['pnl_pct']:+.2f}% | {t['hold_hours']:.1f} |\n")
    
    print(f"  {label}: ${float(capital):.0f}→${float(final):.2f} ({ret:+.2%})  {len(trades)}trades  {wr:.0f}%WR")
    print(f"    CSV: {csv_path}")
    print(f"    MD:  {md_path}")
    return csv_path, md_path


# ============================================================
# REPORT 1: MA State via BacktestEngine (authoritative)
# ============================================================

print("=" * 70)
print("  MA STATE STRATEGY — via BacktestEngine")
print("=" * 70)

config = BacktestConfig(initial_cash=10000, commission=0.001, slippage=0.0005, plot_results=False)

for pair, fast, slow in [('TON/USDT', 15, 60), ('BTC/USDT', 100, 300)]:
    engine = BacktestEngine(config)
    strategy = MAStateStrategy(f"rpt", {
        'fast_ma_period': fast, 'slow_ma_period': slow,
        'ma_type': 'sma', 'use_stop_loss': False,
    })
    result = engine.run_backtest(strategy, pair, '1h', days=365)
    
    if not result.trades:
        print(f"  {pair}: NO TRADES")
        continue
    
    # Convert Backtrader trades to our format
    trades = []
    for bt in result.trades:
        side = bt.get('side', 'LONG').upper()
        size = float(bt.get('position_size', 0))
        ep = float(bt.get('entry_price', 0))
        xp = float(bt.get('exit_price', 0))
        pnl_pct = float(bt.get('pnl', 0))  # percentage return
        et = bt.get('entry_time', 0)
        xt = bt.get('exit_time', 0)
        entry_value = float(bt.get('entry_value', 0))
        
        # Dollar PnL
        if entry_value > 0:
            pnl_dollar = entry_value * pnl_pct
        elif size > 0:
            pnl_dollar = size * ep * pnl_pct
        else:
            pnl_dollar = 0
        
        comm_est = (entry_value if entry_value > 0 else size * ep) * 0.001 * 2
        
        trades.append({
            'entry_time': et,
            'exit_time': xt,
            'side': side,
            'quantity': size,
            'entry_price': ep,
            'exit_price': xp,
            'commission': comm_est,
            'pnl': pnl_dollar,
            'pnl_pct': pnl_pct * 100,
            'hold_hours': (xt - et) / 3600000 if et and xt else 0,
        })
    
    label = f"MA_State_{pair.replace('/','')}"
    write_csv_md(trades, label, Decimal('10000'), pair, '/home/roler/Code/CryptoQuant/research')


# ============================================================
# REPORT 2: SmallCap Strategy — manual walk-through
# ============================================================

print(f"\n{'='*70}")
print(f"  SMALL CAP STRATEGY — manual walk-through")
print(f"{'='*70}")

for pair, capital, params, label in [
    ('TON/USDT', Decimal('50'),
     {'trend_ma': 400, 'entry_ma': 100, 'min_hold_bars': 120, 'cooldown_bars': 504},
     'SmallCap_TON_$50'),
    ('BASED/USDT', Decimal('25'),
     {'trend_ma': 200, 'entry_ma': 50, 'min_hold_bars': 48, 'cooldown_bars': 168},
     'SmallCap_BASED_$25'),
]:
    since = int((datetime.now(timezone.utc) - timedelta(days=365)).timestamp() * 1000)
    candles = repo.load_candles(pair, '1h', since=since)
    
    strategy = SmallCapStrategy(label, params)
    strategy.initialize()
    
    cash = capital
    side = None; sz = 0; ep = Decimal('0'); et = 0
    trades = []
    
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
        
        sig = strategy.generate_signal(ctx).signal_type.name
        
        if sig == 'LONG' and side is None:
            sz = qty(cash, c.close)
            gross = Decimal(str(sz)) * c.close
            co = gross * COMM
            if gross + co <= cash and sz > 0:
                side = 'long'; ep = c.close; et = c.timestamp
                cash -= (gross + co)
        
        elif sig == 'CLOSE_LONG' and side == 'long':
            gross = Decimal(str(sz)) * c.close
            co = gross * COMM
            pnl = gross - Decimal(str(sz)) * ep - co * Decimal('2')
            cash += gross - co
            
            hold_h = (c.timestamp - et) / 3600000
            gross_entry = Decimal(str(sz)) * ep
            trades.append({
                'entry_time': et, 'exit_time': c.timestamp,
                'side': 'LONG', 'quantity': sz,
                'entry_price': float(ep), 'exit_price': float(c.close),
                'commission': float(co * 2),
                'pnl': float(pnl),
                'pnl_pct': float(pnl / gross_entry * 100) if gross_entry > 0 else 0,
                'hold_hours': hold_h,
            })
            side = None
    
    if side and sz > 0:
        last = candles[-1]
        gross = Decimal(str(sz)) * last.close
        co = gross * COMM
        pnl = gross - Decimal(str(sz)) * ep - co * Decimal('2')
        cash += gross - co
        hold_h = (last.timestamp - et) / 3600000
        gross_entry = Decimal(str(sz)) * ep
        trades.append({
            'entry_time': et, 'exit_time': last.timestamp,
            'side': 'LONG', 'quantity': sz,
            'entry_price': float(ep), 'exit_price': float(last.close),
            'commission': float(co * 2),
            'pnl': float(pnl),
            'pnl_pct': float(pnl / gross_entry * 100) if gross_entry > 0 else 0,
            'hold_hours': hold_h,
        })
    
    write_csv_md(trades, label, capital, pair, '/home/roler/Code/CryptoQuant/research')

print(f"\n{'='*70}")
print(f"  All reports in /home/roler/Code/CryptoQuant/research/")
print(f"{'='*70}")
