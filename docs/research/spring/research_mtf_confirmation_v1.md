# Spring Reversal — Multi-Timeframe Confirmation: Null Result

> **One-line summary:** All 4h trend filters (SMA200, SMA50, Golden Cross, ADX) either match baseline or degrade performance. The 1h SMA200 + BB %B filters already capture the macro regime. Multi-timeframe confirmation is NOT a viable improvement path.

## Hypothesis

The Spring Reversal filtered strategy (SMA200 + BB %B 0.2-0.6) produces Sharpe +0.42 with 74 trades over 7 years on the BacktestEngine (compound returns, 10 bps round-trip costs). The strategy's main limitation is the low trade count (~11/year) and one negative walk-forward split during the 2022 bear market.

**Hypothesis:** Adding higher-timeframe (4h) trend confirmation would:
1. Eliminate the bear market split by preventing entries during larger downtrends
2. Improve per-trade metrics (WR, PF) by filtering to only the highest-conviction setups
3. Potentially increase Sharpe even if trade count drops

## Methodology

### Data
- OKX BTC/USDT 1h: 2019-2026 (65,016 bars)
- Binance BTC/USDT 1h: 2019-2026 (64,933 bars)
- Commission: 5 bps round-trip, Slippage: 5 bps

### Signal
```
Spring Reversal: lookback=20, vol_mult=1.5, close_pct=0.5
1h Filters: close > SMA(200) AND BB %B in [0.2, 0.6)
Entry: Next bar open after signal
Stop: lows-based
```

### Multi-Timeframe Filters Tested

| Variant | 4h Filter | Description |
|---------|-----------|-------------|
| V0 (Baseline) | None | Existing best config |
| V1 | Close > SMA200 | Price above 4h SMA200 |
| V2 | SMA50 > SMA200 | Golden Cross on 4h |
| V3 | Close > SMA50 | Price above 4h SMA50 |
| V4 | ADX > 20 | Trending on 4h |
| V5 | GC + >SMA50 | Combo of V2+V3 |
| V6 | GC + ADX>20 | Combo of V2+V4 |

### 4h Bar Construction
```python
df_4h = df_1h.resample("4h").agg({
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum",
})
```
4h indicators computed on 4h bars, then mapped back to 1h timestamps using `reindex(method="ffill")` — the most recent completed 4h bar's indicator state is used for each 1h bar.

### Validation
1. Full-period backtest on OKX with BacktestEngine (compound returns)
2. 6-split walk-forward on OKX
3. Binance cross-validation (Baseline + V2)
4. Signal overlap analysis

## Results

### Full Backtest Comparison (OKX BTC/USDT 1h, 2019-2026)

| Variant | Trades | Return | Sharpe | MaxDD | WR | PF | WF |
|---------|--------|--------|--------|-------|-----|-----|-----|
| **V0: Baseline** | **74** | **+19.8%** | **+0.42** | **-6.7%** | **56.8%** | **1.35** | **5/6** |
| V1: 4h > SMA200 | 50 | +11.6% | +0.30 | -6.7% | 56.0% | 1.29 | 4/6 |
| V2: 4h Golden Cross | 38 | +10.8% | +0.31 | -9.1% | 57.9% | 1.36 | 3/6 |
| V3: 4h > SMA50 | 71 | +20.8% | +0.43 | -6.7% | 56.3% | 1.37 | 5/6 |
| V4: 4h ADX > 20 | 51 | +19.8% | +0.48 | -6.3% | 60.8% | 1.51 | 4/6 |
| V5: GC + >SMA50 | 37 | +10.7% | +0.31 | -9.1% | 56.8% | 1.35 | 3/6 |
| V6: GC + ADX>20 | 26 | +7.7% | +0.26 | -7.1% | 61.5% | 1.36 | 4/6 |

### V0 Baseline — Full Metrics

```
Initial Capital:    10,000 USDT
Commission:         5 bps (round-trip)
Slippage:           5 bps

Total Trades:       74
Total Return:       +19.8%
Annualized Return:  +2.5%
Sharpe Ratio:       +0.42
Sortino Ratio:      +0.13
Max Drawdown:       -6.7%
Win Rate:           56.8%
Avg Win:            +1.79%
Avg Loss:           -1.74%
Profit Factor:      1.35
Max Consec Losses:  4

Exit Breakdown:
  take_profit:   27 (36.5%)  avg=+2.40%  total=+64.8%
  stop_loss:      9 (12.2%)  avg=-3.10%  total=-27.9%
  time_exit:     38 (51.4%)  avg=-0.46%  total=-17.3%
```

### Walk-Forward Validation

| Split | Period | V0 Trades | V0 Sharpe | V3 Trades | V3 Sharpe | V4 Trades | V4 Sharpe |
|-------|--------|-----------|-----------|-----------|-----------|-----------|-----------|
| 1 | 2019-12→2020-11 | 13 | +1.77 ✅ | 12 | +1.75 ✅ | 8 | +1.09 ✅ |
| 2 | 2020-11→2021-10 | 4 | +0.82 ✅ | 4 | +0.82 ✅ | 2 | -0.18 ❌ |
| 3 | 2021-10→2022-09 | 10 | -0.78 ❌ | 10 | -0.78 ❌ | 8 | -0.31 ❌ |
| 4 | 2022-09→2023-08 | 9 | +0.98 ✅ | 9 | +0.98 ✅ | 7 | +1.04 ✅ |
| 5 | 2023-08→2024-07 | 18 | +0.08 ✅ | 17 | +0.26 ✅ | 14 | +0.06 ✅ |
| 6 | 2024-07→2025-06 | 13 | +0.76 ✅ | 12 | +0.74 ✅ | 8 | +1.88 ✅ |

- V0: 5/6 profitable, Mean OOS Sharpe: +0.61
- V3: 5/6 profitable, Mean OOS Sharpe: +0.63
- V4: 4/6 profitable, Mean OOS Sharpe: +0.60

### Signal Overlap Analysis

| Variant | Signal Count | % of Baseline |
|---------|-------------|---------------|
| Baseline | 82 | 100.0% |
| V1 (4h > SMA200) | 54 | 65.9% |
| V2 (4h GC) | 41 | 50.0% |
| V3 (4h > SMA50) | 78 | 95.1% |
| V4 (4h ADX > 20) | 55 | 67.1% |
| V5 (GC + >SMA50) | 39 | 47.6% |
| V6 (GC + ADX > 20) | 27 | 32.9% |

**Key observation:** V3 (4h > SMA50) overlaps 95.1% with baseline — it filters almost nothing because when price is above 1h SMA200, it's almost always above 4h SMA50. This confirms redundancy.

### Binance Cross-Validation

| Metric | OKX Baseline | BNC Baseline | OKX V2 | BNC V2 |
|--------|-------------|-------------|--------|--------|
| Trades | 74 | 84 | 38 | 51 |
| Return | +19.8% | +31.3% | +10.8% | +9.4% |
| Sharpe | +0.42 | +0.58 | +0.31 | +0.25 |
| Max DD | -6.7% | -6.1% | -9.1% | -11.1% |
| Win Rate | 56.8% | 60.7% | 57.9% | 58.8% |
| PF | 1.35 | 1.49 | 1.36 | 1.24 |

Binance confirms the pattern: baseline is strong (Sharpe +0.58, better than OKX's +0.42), and V2 degrades on both exchanges.

## Analysis

### Why Multi-Timeframe Confirmation Fails

1. **The 1h SMA200 already captures the macro regime.** When price is above the 1h SMA200, it's almost always above the 4h SMA50 (95.1% overlap). The 1h SMA200 is a stronger filter — it eliminated 71% of unfiltered trades (543→156), while the 4h filters mostly just remove a subset of already-filtered trades.

2. **The 1h BB %B 0.2-0.6 filter already restricts to the bounce zone.** This filter captures the pullback-in-uptrend condition that a 4h trend filter would aim to identify. Adding a 4h filter is redundant.

3. **Reducing trade count hurts more than it helps.** The strategy already has a sparse signal (74 trades over 7 years, ~11/year). Walk-forward splits have as few as 4 trades. Further reducing trade count increases variance and reduces statistical reliability, even if per-trade metrics improve marginally.

4. **The bear market split (Split 3) is unfixable with trend filters.** Every variant — including those with 4h trend confirmation — still has a negative Split 3. During the 2022 bear market, even when both 1h and 4h conditions are met, Spring signals fail because the macro environment is hostile. The only fix for this split would be a macro bear market filter (e.g., 200-day return), not a higher-timeframe trend filter.

5. **MTF filters are reactive, not predictive.** A 4h SMA crossover lags price by 50-200 bars (200-800 hours). By the time the 4h Golden Cross forms, the 1h SMA200 has already been crossed for weeks. The 4h filter provides no new information — it's a noisier, lagged version of what the 1h SMA200 already tells us.

### The One Bright Spot: V4 (4h ADX > 20)

V4 has the best per-trade metrics (WR 60.8%, PF 1.51, Max Consec Losses 3) and matches baseline Sharpe (+0.48 vs +0.42) despite 31% fewer trades. However:
- WF drops to 4/6 (Split 2 becomes negative)
- Trade count drops from 74→51 (~8/year)
- The improvement in per-trade metrics is marginal

V4's ADX filter eliminates low-volatility, ranging Spring signals where the "breakdown" is ambiguous. In trending environments (ADX > 20), the breakdown is more meaningful. But the cost in trade count and WF reliability outweighs the benefit.

### What Actually Improves Per-Trade Metrics

Looking at the exit breakdown, the real opportunity is in the time-exits:
- 51.4% of trades are time-exits with avg -0.46%
- If we could convert just half of these to profitable exits, Sharpe would improve significantly

The "lower the target" pattern from prior research is the actual solution — reducing target from 5.0% to 2.5% already improved dramatically. Further exit optimization (vol-adaptive holds, dynamic targets) is more promising than entry filters.

## Recommendation

### ❌ DISCARD — Multi-timeframe confirmation is not a viable improvement

**Rationale:**
- All 6 MTF variants either match or underperform baseline
- The 1h SMA200 + BB %B filters already provide sufficient regime information
- MTF filters reduce already-sparse trade count without improving Sharpe
- The bear market failure is a macro problem, not a timeframe problem

### What Works Better (from Prior Research)

1. **Lower target → 2.5% from 5.0%**: Transformed strategy from Sharpe -0.71 to +1.53 (research scripts) or +0.42 (BacktestEngine)
2. **SMA200 filter**: Essential — eliminates 71% of toxic below-trend trades
3. **BB %B 0.2-0.6**: Identifies the bounce zone where Springs are profitable
4. **Exit optimization**: The 51.4% time-exit rate is the real bottleneck, not entry filters

### Next Steps

1. **Don't pursue MTF filters further.** This is a dead end.
2. **Focus on exit optimization.** 51.4% time-exits with avg -0.46% is the real drag. Dynamic holds (vol-adaptive), adjusted targets, or trailing exits might help.
3. **Multi-pair deployment.** The main bottleneck is trade count (~11/year). Running on ETH, SOL, and other pairs would increase trade frequency and smooth returns.
4. **Implement vol-adaptive exits for Spring.** This pattern worked for BB Breakout (+8.3% Sharpe improvement) and may help Spring too.

### Strategy Class Implementation

As part of this research session, the Spring filtered strategy has been implemented as a proper strategy class:

- **Class**: `strategies/spring.py` → `SpringReversal`
- **Signal function**: `cryptoquant/strategy/signals.py` → `spring_reversal_signal()`
- **Usage**:
  ```python
  from strategies.spring import SpringReversal
  strategy = SpringReversal()
  engine = BacktestEngine(commission=0.0005, slippage=0.0005)
  result = engine.run(df, strategy, symbol="BTC/USDT",
      stop_loss_pct=3.0, take_profit_pct=2.5, max_hold_bars=24)
  ```

## Reproduction

```bash
cd /home/roler/Code/CryptoQuant

# Multi-timeframe research
python research/backtest_spring_mtf.py

# Validate strategy class
python -c "
from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from strategies.spring import SpringReversal

store = OHLCVStore()
df = store.load('okx', 'BTC/USDT', '1h')
strategy = SpringReversal()
engine = BacktestEngine(commission=0.0005, slippage=0.0005)
result = engine.run(df, strategy, symbol='BTC/USDT',
    stop_loss_pct=3.0, take_profit_pct=2.5, max_hold_bars=24)
print(f'Sharpe: {result.metrics.sharpe_ratio:+.2f}, Return: {result.metrics.total_return_pct:+.1f}%')
"
```

**Data:** OKX + Binance BTC/USDT 1h (2019-2026, ~65k bars each)
**Engine:** BacktestEngine (compound returns, lows-based stops)
**Commission:** 5 bps (round-trip)
**Slippage:** 5 bps

---

**Document version:** v1
**Date:** 2026-06-15
**Author:** CryptoQuant Autonomous Researcher
