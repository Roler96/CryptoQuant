"""Standalone backtest: TrendPullbackRSI on BTC/USDT 1h, 2022-2023.
Uses existing SQLite data — no API fetch needed."""

import os
import sys
from datetime import datetime, timezone

import pandas as pd

# Ensure project root is in sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.risk.sizer import ATRSizer
from research.backtest_trend_pullback_rsi import TrendPullbackRSI

# ─── Config ──────────────────────────────────────────────────────
SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"
EXCHANGE = "okx"
INITIAL_CAPITAL = 10_000
COMMISSION = 0.0005
SLIPPAGE = 0.0005
DB_PATH = "data/cryptoquant.db"

# ─── Load data for 2022-01-01 → 2023-12-31 ───────────────────────
start_dt = datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
end_dt   = datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

print(f"Loading {EXCHANGE} {SYMBOL} {TIMEFRAME} from SQLite: {start_dt.date()} → {end_dt.date()}")

store = OHLCVStore(db_path=DB_PATH)
df = store.load(EXCHANGE, SYMBOL, TIMEFRAME, start=int(start_dt.timestamp()*1000), end=int(end_dt.timestamp()*1000))

if df.empty:
    print("ERROR: No data in DB for this range")
    sys.exit(1)

print(f"Loaded {len(df)} bars, {df.index[0]} → {df.index[-1]}")

# ─── Run full-period backtest ────────────────────────────────────
strategy = TrendPullbackRSI()
strategy.timeframe = TIMEFRAME

sizer = ATRSizer(base_risk_pct=5.0, atr_period=14, multiplier=1.0, min_order=10.0, max_pct=100.0)

engine = BacktestEngine(
    initial_capital=INITIAL_CAPITAL, commission=COMMISSION,
    slippage=SLIPPAGE, use_lows_for_stops=True, sizer=sizer,
)
result = engine.run(df, strategy, symbol=SYMBOL)
m = result.metrics

print(f"\n{'='*60}")
print(f"  TrendPullbackRSI | {SYMBOL} {TIMEFRAME} | 2022-01-01 → 2023-12-31")
print(f"{'='*60}")
print(f"  Net Profit:       {m.total_return_pct:+.2f}%")
print(f"  Final Equity:     ${result.final_equity:,.2f} (start: ${INITIAL_CAPITAL:,})")
print(f"  Annual Return:    {m.annualized_return_pct:+.2f}%")
print(f"  Sharpe Ratio:     {m.sharpe_ratio:.2f}")
print(f"  Sortino Ratio:    {m.sortino_ratio:.2f}")
print(f"  Max Drawdown:     {m.max_drawdown_pct:.2f}%")
print(f"  Max DD Days:      {m.max_drawdown_days}")
print(f"  Volatility (ann): {m.volatility_annual_pct:.2f}%")
print(f"  Total Trades:     {m.total_trades}")
print(f"  Win Rate:         {m.win_rate_pct:.1f}%")
print(f"  Profit Factor:    {m.profit_factor:.2f}")
print(f"  Avg Win:          {m.avg_win_pct:.2f}%")
print(f"  Avg Loss:         {m.avg_loss_pct:.2f}%")
print(f"  Avg Hold:         {m.avg_hold_hours:.1f}h")
print(f"  Commission:       {COMMISSION:.4f} (5 bps)")
print(f"  Slippage:         {SLIPPAGE:.4f} (5 bps)")
print(f"{'='*60}")

# ─── OOS split: IS=2022, OOS=2023 ────────────────────────────────
mid_dt = pd.Timestamp("2023-01-01", tz=None)
split_mask = df.index < mid_dt
df_is = df.loc[split_mask].copy()
df_oos = df.loc[~split_mask].copy()

print(f"\n─── OOS Validation: IS=2022 ({len(df_is)} bars), OOS=2023 ({len(df_oos)} bars) ───")

# IS
strategy_is = TrendPullbackRSI()
strategy_is.timeframe = TIMEFRAME
engine_is = BacktestEngine(
    initial_capital=INITIAL_CAPITAL, commission=COMMISSION,
    slippage=SLIPPAGE, use_lows_for_stops=True, sizer=sizer,
)
result_is = engine_is.run(df_is, strategy_is, symbol=SYMBOL)
mi = result_is.metrics

# OOS
strategy_oos = TrendPullbackRSI()
strategy_oos.timeframe = TIMEFRAME
engine_oos = BacktestEngine(
    initial_capital=INITIAL_CAPITAL, commission=COMMISSION,
    slippage=SLIPPAGE, use_lows_for_stops=True, sizer=sizer,
)
result_oos = engine_oos.run(df_oos, strategy_oos, symbol=SYMBOL)
mo = result_oos.metrics

print(f"  {'Metric':<22} {'IS (2022)':>12} {'OOS (2023)':>12} {'Full':>12}")
print(f"  {'─'*22} {'─'*12} {'─'*12} {'─'*12}")
print(f"  {'Sharpe Ratio':<22} {mi.sharpe_ratio:>12.2f} {mo.sharpe_ratio:>12.2f} {m.sharpe_ratio:>12.2f}")
print(f"  {'Total Return %':<22} {mi.total_return_pct:>+11.2f} {mo.total_return_pct:>+11.2f} {m.total_return_pct:>+11.2f}")
print(f"  {'Max Drawdown %':<22} {mi.max_drawdown_pct:>12.2f} {mo.max_drawdown_pct:>12.2f} {m.max_drawdown_pct:>12.2f}")
print(f"  {'Total Trades':<22} {mi.total_trades:>12} {mo.total_trades:>12} {m.total_trades:>12}")
print(f"  {'Win Rate %':<22} {mi.win_rate_pct:>12.1f} {mo.win_rate_pct:>12.1f} {m.win_rate_pct:>12.1f}")
print(f"  {'Profit Factor':<22} {mi.profit_factor:>12.2f} {mo.profit_factor:>12.2f} {m.profit_factor:>12.2f}")
print(f"  {'Avg Hold (h)':<22} {mi.avg_hold_hours:>12.1f} {mo.avg_hold_hours:>12.1f} {m.avg_hold_hours:>12.1f}")
print(f"  {'Volatility (ann)%':<22} {mi.volatility_annual_pct:>12.2f} {mo.volatility_annual_pct:>12.2f} {m.volatility_annual_pct:>12.2f}")

# Assessment
print("\n─── Verdict ───")
if mo.sharpe_ratio > 0.5 and mo.max_drawdown_pct < 30 and mo.total_trades >= 30:
    deg = (mi.sharpe_ratio - mo.sharpe_ratio) / mi.sharpe_ratio * 100 if mi.sharpe_ratio > 0 else 0
    print(f"  OOS PASS: Sharpe {mo.sharpe_ratio:.2f}, MaxDD {mo.max_drawdown_pct:.1f}%, Trades {mo.total_trades}")
    if deg > 50:
        print(f"  ⚠ OVERFIT WARNING: {deg:.0f}% Sharpe degradation from IS to OOS")
    else:
        print(f"  Stable: {deg:.0f}% Sharpe change IS→OOS (OK)")
else:
    print("  OOS FAIL:")
    if mo.sharpe_ratio < 0.5:
        print(f"    - Sharpe {mo.sharpe_ratio:.2f} < 0.5 threshold")
    if mo.max_drawdown_pct > 30:
        print(f"    - MaxDD {mo.max_drawdown_pct:.1f}% > 30% threshold")
    if mo.total_trades < 30:
        print(f"    - Only {mo.total_trades} trades < 30 minimum")
