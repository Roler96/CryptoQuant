
"""
Detailed Trade Report Generator.
Produces trade-by-trade records with timestamps, prices, commissions, PnL.
Outputs both CSV (Excel) and Markdown table formats.
"""
import sys, csv, io
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from data.repository import get_repository
from strategy.cta.ma_state import MAStateStrategy
from strategy.cta.small_cap import SmallCapStrategy
from strategy.base import StrategyContext
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone, timedelta

repo = get_repository()
COMM = Decimal('0.001')

def qty(cap, price, min_qty=1):
    usable = cap * (Decimal('1') - COMM)
    raw = usable / price
    return max(min_qty, int(raw.to_integral_value(rounding=ROUND_DOWN)))

def generate_report(pair, strategy_class, params, capital, label, output_dir='/home/roler/Code/CryptoQuant/research'):
    """Run backtest and produce detailed trade report."""
    
    since = int((datetime.now(timezone.utc) - timedelta(days=365)).timestamp() * 1000)
    candles = repo.load_candles(pair, '1h', since=since)
    
    if len(candles) < 300:
        print(f"  {label}: SKIP — only {len(candles)} candles")
        return
    
    strategy = strategy_class(f"{label}", params)
    strategy.initialize()
    
    cash = capital
    side = None
    sz = 0
    entry_price = Decimal('0')
    entry_time = 0
    pnl_total = Decimal('0')
    comm_total = Decimal('0')
    
    trades = []  # [{entry_time, exit_time, side, qty, entry_price, exit_price, pnl, comm, hold_hours}]
    
    warmup = params.get('trend_ma', params.get('slow_ma_period', 200)) + 10
    
    for i in range(warmup, len(candles)):
        c = candles[i]
        w = candles[max(0, i-600):i+1]
        
        ctx = StrategyContext(
            pair=pair, timeframe='1h',
            current_price=c.close, current_time=c.timestamp,
            closes_f=[float(x.close) for x in w],
            highs_f=[float(x.high) for x in w],
            lows_f=[float(x.low) for x in w],
        )
        
        signal = strategy.generate_signal(ctx)
        sig = signal.signal_type.name
        
        # --- LONG ENTRY ---
        if sig == 'LONG' and side is None:
            sz = qty(cash, c.close)
            gross = Decimal(str(sz)) * c.close
            co = gross * COMM
            if gross + co <= cash and sz > 0:
                side = 'long'
                entry_price = c.close
                entry_time = c.timestamp
                cash -= (gross + co)
                comm_total += co
        
        # --- SHORT ENTRY ---
        elif sig == 'SHORT' and side is None:
            sz = qty(cash, c.close)
            gross = Decimal(str(sz)) * c.close
            co = gross * COMM
            if gross + co <= cash and sz > 0:
                side = 'short'
                entry_price = c.close
                entry_time = c.timestamp
                cash -= (gross + co)
                comm_total += co
        
        # --- LONG EXIT ---
        elif sig == 'CLOSE_LONG' and side == 'long':
            gross = Decimal(str(sz)) * c.close
            co = gross * COMM
            pnl = gross - Decimal(str(sz)) * entry_price - co * Decimal('2')
            pnl_total += pnl
            cash += gross - co
            comm_total += co
            
            hold_hours = (c.timestamp - entry_time) / 3600000
            trades.append({
                'entry_time': entry_time,
                'exit_time': c.timestamp,
                'side': 'LONG',
                'quantity': sz,
                'entry_price': float(entry_price),
                'exit_price': float(c.close),
                'gross_entry': float(Decimal(str(sz)) * entry_price),
                'gross_exit': float(gross),
                'commission': float(co * Decimal('2')),  # buy + sell
                'pnl': float(pnl),
                'pnl_pct': float(pnl / (Decimal(str(sz)) * entry_price) * 100),
                'hold_hours': hold_hours,
                'hold_days': hold_hours / 24,
            })
            side = None
        
        # --- SHORT EXIT ---
        elif sig == 'CLOSE_SHORT' and side == 'short':
            gross = Decimal(str(sz)) * c.close
            co = gross * COMM
            pnl = Decimal(str(sz)) * entry_price - gross - co * Decimal('2')
            pnl_total += pnl
            cash += gross - co
            comm_total += co
            
            hold_hours = (c.timestamp - entry_time) / 3600000
            trades.append({
                'entry_time': entry_time,
                'exit_time': c.timestamp,
                'side': 'SHORT',
                'quantity': sz,
                'entry_price': float(entry_price),
                'exit_price': float(c.close),
                'gross_entry': float(Decimal(str(sz)) * entry_price),
                'gross_exit': float(gross),
                'commission': float(co * Decimal('2')),
                'pnl': float(pnl),
                'pnl_pct': float(pnl / (Decimal(str(sz)) * entry_price) * 100),
                'hold_hours': hold_hours,
                'hold_days': hold_hours / 24,
            })
            side = None
    
    # Close any open position
    if side and sz > 0:
        last = candles[-1]
        gross = Decimal(str(sz)) * last.close
        co = gross * COMM
        if side == 'long':
            pnl = gross - Decimal(str(sz)) * entry_price - co * Decimal('2')
        else:
            pnl = Decimal(str(sz)) * entry_price - gross - co * Decimal('2')
        pnl_total += pnl
        cash += gross - co
        comm_total += co
        
        hold_hours = (last.timestamp - entry_time) / 3600000
        trades.append({
            'entry_time': entry_time,
            'exit_time': last.timestamp,
            'side': side.upper(),
            'quantity': sz,
            'entry_price': float(entry_price),
            'exit_price': float(last.close),
            'gross_entry': float(Decimal(str(sz)) * entry_price),
            'gross_exit': float(gross),
            'commission': float(co * Decimal('2')),
            'pnl': float(pnl),
            'pnl_pct': float(pnl / (Decimal(str(sz)) * entry_price) * 100),
            'hold_hours': hold_hours,
            'hold_days': hold_hours / 24,
            'note': 'OPEN (forced close at end)',
        })
    
    final_value = cash + pnl_total
    total_return = float((final_value - capital) / capital)
    
    # --- Generate Report ---
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    base = f"{output_dir}/{label.replace(' ', '_').replace('/', '_')}_{ts}"
    
    # CSV
    csv_path = f"{base}.csv"
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['#', 'Entry Time (UTC)', 'Exit Time (UTC)', 'Side', 'Qty',
                         'Entry Price', 'Exit Price', 'Gross Entry', 'Gross Exit',
                         'Commission', 'PnL', 'PnL%', 'Hold Hours', 'Hold Days'])
        for i, t in enumerate(trades, 1):
            writer.writerow([
                i,
                datetime.fromtimestamp(t['entry_time']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                datetime.fromtimestamp(t['exit_time']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                t['side'], t['quantity'],
                f"{t['entry_price']:.6f}", f"{t['exit_price']:.6f}",
                f"{t['gross_entry']:.2f}", f"{t['gross_exit']:.2f}",
                f"{t['commission']:.4f}", f"{t['pnl']:.2f}",
                f"{t['pnl_pct']:.2f}%", f"{t['hold_hours']:.1f}", f"{t['hold_days']:.1f}",
            ])
    
    # Markdown
    md_path = f"{base}.md"
    with open(md_path, 'w') as f:
        f.write(f"# {label} — 交易明细报告\n\n")
        f.write(f"**币对**: {pair}  |  **时间框架**: 1h  |  **初始资金**: ${float(capital):.2f}\n\n")
        f.write(f"**总收益**: {total_return:+.2%}  |  **最终资金**: ${float(final_value):.2f}  |  ")
        f.write(f"**交易次数**: {len(trades)}  |  **总佣金**: ${float(comm_total):.2f}\n\n")
        
        # Summary stats
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] <= 0]
        wr = len(wins)/len(trades)*100 if trades else 0
        avg_win = sum(t['pnl'] for t in wins)/len(wins) if wins else 0
        avg_loss = sum(t['pnl'] for t in losses)/len(losses) if losses else 0
        max_win = max((t['pnl'] for t in trades), default=0)
        max_loss = min((t['pnl'] for t in trades), default=0)
        avg_hold = sum(t['hold_days'] for t in trades)/len(trades) if trades else 0
        
        f.write(f"| 指标 | 值 |\n")
        f.write(f"|------|----|\n")
        f.write(f"| 胜率 | {wr:.1f}% ({len(wins)}/{len(trades)}) |\n")
        f.write(f"| 平均盈利 | ${avg_win:+.2f} |\n")
        f.write(f"| 平均亏损 | ${avg_loss:+.2f} |\n")
        f.write(f"| 最大盈利 | ${max_win:+.2f} |\n")
        f.write(f"| 最大亏损 | ${max_loss:+.2f} |\n")
        f.write(f"| 平均持仓 | {avg_hold:.1f} 天 |\n")
        f.write(f"| 盈亏比 | {abs(avg_win/avg_loss):.2f}" if avg_loss != 0 else "| 盈亏比 | N/A")
        f.write(f" |\n\n")
        
        f.write(f"## 逐笔交易明细\n\n")
        f.write(f"| # | 入场时间 | 出场时间 | 方向 | 数量 | 入场价 | 出场价 | 入场金额 | 出场金额 | 佣金 | 盈亏 | 盈亏% | 持仓(天) |\n")
        f.write(f"|---|----------|----------|------|------|--------|--------|----------|----------|------|------|-------|----------|\n")
        
        for i, t in enumerate(trades, 1):
            entry_dt = datetime.fromtimestamp(t['entry_time']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
            exit_dt = datetime.fromtimestamp(t['exit_time']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
            side_emoji = '📈' if t['side'] == 'LONG' else '📉'
            note = t.get('note', '')
            
            f.write(f"| {i} | {entry_dt} | {exit_dt} | {side_emoji} {t['side']} | {t['quantity']} | "
                   f"${t['entry_price']:.6f} | ${t['exit_price']:.6f} | "
                   f"${t['gross_entry']:.2f} | ${t['gross_exit']:.2f} | "
                   f"${t['commission']:.4f} | ${t['pnl']:+.2f} | {t['pnl_pct']:+.2f}% | "
                   f"{t['hold_days']:.1f} | {note}\n")
    
    # Print summary
    print(f"\n  {label}")
    print(f"    CSV:  {csv_path}")
    print(f"    MD:   {md_path}")
    print(f"    {float(capital):.0f}→${float(final_value):.2f} ({total_return:+.2%})  "
          f"{len(trades)} trades  {wr:.0f}% WR  avg hold {avg_hold:.1f}d")
    
    return csv_path, md_path


# ============================================================
# Generate reports for best strategies
# ============================================================

print("=" * 70)
print("  GENERATING DETAILED TRADE REPORTS")
print("=" * 70)

# Report 1: Small capital — TON with SmallCapStrategy
generate_report(
    pair='TON/USDT',
    strategy_class=SmallCapStrategy,
    params={'trend_ma': 400, 'entry_ma': 100, 'min_hold_bars': 120, 'cooldown_bars': 504},
    capital=Decimal('50'),
    label='SmallCap_TON_$50',
)

# Report 2: Small capital — TON+BASED combined (simulated as TON $25)
generate_report(
    pair='TON/USDT',
    strategy_class=SmallCapStrategy,
    params={'trend_ma': 400, 'entry_ma': 100, 'min_hold_bars': 120, 'cooldown_bars': 504},
    capital=Decimal('25'),
    label='SmallCap_TON_$25',
)

generate_report(
    pair='BASED/USDT',
    strategy_class=SmallCapStrategy,
    params={'trend_ma': 200, 'entry_ma': 50, 'min_hold_bars': 48, 'cooldown_bars': 168},
    capital=Decimal('25'),
    label='SmallCap_BASED_$25',
)

# Report 3: Large capital — TON with MA State
generate_report(
    pair='TON/USDT',
    strategy_class=MAStateStrategy,
    params={'fast_ma_period': 15, 'slow_ma_period': 60, 'ma_type': 'sma', 'use_stop_loss': False},
    capital=Decimal('10000'),
    label='MAState_TON_$10000',
)

# Report 4: Large capital — BTC with MA State
generate_report(
    pair='BTC/USDT',
    strategy_class=MAStateStrategy,
    params={'fast_ma_period': 100, 'slow_ma_period': 300, 'ma_type': 'sma', 'use_stop_loss': False},
    capital=Decimal('10000'),
    label='MAState_BTC_$10000',
)

print(f"\n{'='*70}")
print(f"  Reports saved to research/ directory")
print(f"{'='*70}")
