# Spring Reversal — EMA50>EMA200 Crossover as Trend Filter v1

> **One-line summary:** Replacing the static SMA200 trend filter with EMA50>EMA200 crossover produces +36% more trades (98 vs 72), higher Sharpe (+1.63 vs +1.43), better walk-forward robustness (5/7 vs 4/7, mean WF Sharpe +0.73 vs +0.59), and cross-exchange confirmation on Binance (Sharpe +1.65 vs +1.56). The tradeoff is higher drawdown (-13.9% vs -9.4%).

## Hypothesis

Previous research established that SMA200 + BB %B 0.2-0.6 is the best filter for Spring Reversal (Sharpe +1.43, 74 trades, 5/7 WF). However, SMA200 is a static, slow-moving filter that may miss valid Spring signals during trend transitions.

**Hypothesis:** A more responsive trend filter — EMA50>EMA200 crossover — should:
1. Capture Spring signals earlier during uptrend initiations (more trades)
2. Exit signals sooner during trend breakdowns (avoid holding through reversals)
3. Maintain or improve risk-adjusted returns compared to SMA200

The EMA crossover is classic trend-following: when the faster EMA (50) is above the slower EMA (200), the market is in an uptrend. This is more responsive than price > SMA200 because it uses two moving averages and captures the relationship between short-term and long-term momentum.

## Methodology

### Data
- OKX BTC/USDT 1h: 2019-2026 (~65k bars)
- Binance BTC/USDT 1h: 2019-2026 (~65k bars)
- Commission: 5 bps round-trip, Slippage: 5 bps

### Signal
```
Spring Reversal: lookback=20, vol_mult=1.5, close_pct=0.5
BB Zone filter: %B in [0.2, 0.6)
Trend filters tested:
  1. None (unfiltered)
  2. SMA200: close > SMA(200)           ← baseline
  3. SMA50: close > SMA(50)
  4. SMA100: close > SMA(100)
  5. EMA50>EMA200: EMA(50) > EMA(200)   ← new
  6. PDI > MDI (directional movement)
  7. Above BB Middle: close > SMA(50) via BB
  8. SMA200 + PDI>MDI (combined)
```

### Exit Parameters
- Baseline exits: stop=3.0%, target=2.5%, hold=24h
- Optimized exits: grid search 3 stops × 3 targets × 3 holds = 27 combinations

### Validation
1. Full backtest on OKX
2. 7-split walk-forward on OKX
3. Binance cross-validation

**Critical:** Always used `lows[i]` for stop checking (not `closes[i]`).

## Results

### Filter Comparison (OKX BTC/USDT 1h, baseline exits s3.0/t2.5/h24)

| Filter | Sigs | Trades | Sum | Sharpe | MaxDD | WR | PF |
|--------|------|--------|-----|--------|-------|-----|-----|
| No trend filter | 236 | 221 | -12.7% | -0.40 | -25.0% | 53.4% | 0.94 |
| SMA200 (baseline) | 82 | 74 | +24.5% | +1.43 | -6.7% | 58.1% | 1.45 |
| SMA50 | 48 | 46 | +6.6% | +0.45 | -14.1% | 54.3% | 1.17 |
| SMA100 | 65 | 63 | +14.3% | +0.87 | -11.9% | 58.7% | 1.28 |
| **EMA50>EMA200** | **108** | **101** | **+26.4%** | **+1.34** | **-11.2%** | **59.4%** | **1.36** |
| PDI > MDI | 19 | 19 | +2.9% | +0.33 | -8.0% | 57.9% | 1.19 |
| Above BB Middle | 25 | 25 | -13.1% | -1.28 | -12.8% | 44.0% | 0.54 |
| SMA200 + PDI>MDI | 12 | 12 | +11.7% | +1.85 | -4.6% | 66.7% | 3.11 |

**Key findings:**
1. **EMA50>EMA200 is the second-best filter** by Sharpe (+1.34 vs SMA200's +1.43) but produces 36% more trades (101 vs 74)
2. **SMA200 + PDI>MDI is a "sniper" filter** with extraordinary quality (Sharpe +1.85, PF 3.11) but only 12 trades in 7 years — too sparse for practical use
3. **SMA50 is too tight** (48 trades, Sharpe +0.45) — eliminates too many good signals
4. **All filters benefit from the BB %B zone** — without any filter, Sharpe is -0.40

### Exit Optimization (grid search: 3×3×3 = 27 combinations)

#### EMA50>EMA200 Best: stop=3.0%, target=3.0%, hold=32h
| Metric | Baseline (s3.0/t2.5/h24) | Optimized (s3.0/t3.0/h32) |
|--------|--------------------------|---------------------------|
| Trades | 101 | 98 |
| Sharpe | +1.34 | **+1.63** |
| Sum | +26.4% | **+37.6%** |
| Max DD | -11.2% | -13.9% |
| Win Rate | 59.4% | **61.2%** |
| PF | 1.36 | **1.44** |

The optimization raises the target from 2.5% to 3.0% and extends hold from 24h to 32h. This captures larger moves (avg take-profit +2.90%) while the longer hold allows more trades to reach target. The cost is higher DD (-13.9% vs -11.2%) from wider stops being hit.

#### SMA200 Best: stop=3.0%, target=3.0%, hold=32h
| Metric | Baseline (s3.0/t2.5/h24) | Optimized (s3.0/t3.0/h32) |
|--------|--------------------------|---------------------------|
| Trades | 74 | 72 |
| Sharpe | +1.43 | **+1.43** |
| Sum | +24.5% | **+28.8%** |
| Max DD | -6.7% | -9.4% |

SMA200 didn't improve Sharpe with exit optimization — the baseline exits were already near-optimal.

### Final Comparison: EMA50>EMA200 vs SMA200 (both optimized)

| Metric | SMA200 (s3.0/t3.0/h32) | EMA50>EMA200 (s3.0/t3.0/h32) | Delta |
|--------|------------------------|-------------------------------|-------|
| Trades | 72 | **98** | +36% |
| Sharpe | +1.43 | **+1.63** | +14% |
| Compound Return | +30.6% | **+41.7%** | +36% |
| Max Drawdown | **-9.4%** | -13.9% | -4.5pp |
| Win Rate | 59.7% | **61.2%** | +1.5pp |
| Profit Factor | **1.44** | 1.44 | — |
| WF Profitable | 4/7 | **5/7** | +1 |
| Mean WF Sharpe | +0.59 | **+0.73** | +24% |

### Full Backtest: EMA50>EMA200 + BB %B 0.2-0.6 (OKX BTC/USDT 1h, 2019-2026)

```
Initial Capital:    10,000 USDT
Commission:         5 bps (round-trip)
Slippage:           5 bps

Total Trades:       98
Compound Return:    +41.7%
Linear Sum:         +37.6%
Sharpe Ratio:       +1.63
Sortino Ratio:      +3.81
Max Drawdown:       -13.9%
Win Rate:           61.2%
Avg Win:            +2.06%
Avg Loss:           -2.26%
Profit Factor:      1.44
Max Consec Losses:  4

Exit Breakdown:
  take_profit:    33 (33.7%)  avg=+2.90%  total=+95.7%
  stop_loss:      20 (20.4%)  avg=-3.10%  total=-62.0%
  time_exit:      45 (45.9%)  avg=+0.09%  total=+3.9%

MFE: mean=+2.04%  median=+1.85%  max=+7.88%
MAE: mean=-1.77%  median=-1.51%
Time-exits profitable at some point: 44/45 (97.8%)
```

### Walk-Forward Validation (OKX, 7 splits)

**EMA50>EMA200:**
| Split | Period | Trades | Sum | Sharpe | DD | Status |
|-------|--------|--------|-----|--------|-----|--------|
| 1 | 2019-10→2020-08 | 18 | +17.1% | +1.88 | -6.1% | ✅ |
| 2 | 2020-08→2021-06 | 8 | +1.4% | +0.17 | -3.4% | ✅ |
| 3 | 2021-06→2022-04 | 9 | -6.6% | -0.83 | -7.7% | ❌ |
| 4 | 2022-04→2023-02 | 7 | +7.3% | +1.77 | -1.2% | ✅ |
| 5 | 2023-02→2023-12 | 15 | +5.0% | +0.54 | -5.8% | ✅ |
| 6 | 2023-12→2024-10 | 16 | +14.2% | +1.76 | -5.4% | ✅ |
| 7 | 2024-10→2025-08 | 15 | -1.9% | -0.21 | -11.1% | ❌ |

**5/7 OOS profitable | Mean OOS Sharpe: +0.73 | Total OOS Sum: +36.5%**

**SMA200 Baseline:**
| Split | Period | Trades | Sum | Sharpe | Status |
|-------|--------|--------|-----|--------|--------|
| 1 | 2019-10→2020-08 | 13 | +16.6% | +2.17 | ✅ |
| 2 | 2020-08→2021-06 | 4 | -4.2% | -0.86 | ❌ |
| 3 | 2021-06→2022-04 | 7 | -0.8% | -0.11 | ❌ |
| 4 | 2022-04→2023-02 | 9 | +4.1% | +0.73 | ✅ |
| 5 | 2023-02→2023-12 | 11 | -1.6% | -0.19 | ❌ |
| 6 | 2023-12→2024-10 | 12 | +12.3% | +1.74 | ✅ |
| 7 | 2024-10→2025-08 | 11 | +4.8% | +0.63 | ✅ |

**4/7 OOS profitable | Mean OOS Sharpe: +0.59 | Total OOS Sum: +31.3%**

### Binance Cross-Validation

| Metric | OKX EMA | OKX SMA | BIN EMA | BIN SMA |
|--------|---------|---------|---------|---------|
| Trades | 98 | 72 | 102 | 81 |
| Sharpe | +1.63 | +1.43 | **+1.65** | +1.56 |
| Max DD | -13.9% | -9.4% | -12.6% | -9.6% |
| Win Rate | 61.2% | 59.7% | 62.8% | 61.7% |
| PF | 1.44 | 1.44 | 1.44 | 1.47 |
| Sum | +37.6% | +28.8% | +39.3% | +33.4% |

**Binance confirms:** EMA50>EMA200 outperforms SMA200 on both exchanges. Sharpe is consistently higher (+1.63→+1.65 vs +1.43→+1.56). Trade count is consistently higher (98→102 vs 72→81).

## Analysis

### Why EMA50>EMA200 Works Better Than SMA200

1. **Earlier entry into uptrends.** SMA200 requires price to be above a 200-bar moving average, which lags significantly. When BTC transitions from a downtrend to an uptrend, the EMA50 crosses above EMA200 weeks before price crosses above SMA200. Spring signals in this transition zone are caught by EMA but missed by SMA.

2. **More trades with maintained quality.** The 36% increase in trade count (98 vs 72) comes from capturing Spring signals during trend initiations. These additional trades have similar per-trade quality — the profit factor is unchanged at 1.44.

3. **Better walk-forward consistency.** EMA is 5/7 profitable vs SMA's 4/7. The extra split comes from Split 2 (2020-08→2021-06), where EMA caught the post-COVID recovery trend earlier than SMA. SMA had only 4 trades in this split (vs 8 for EMA) and was negative.

4. **The BB %B zone does the heavy lifting.** Both filters rely on BB %B 0.2-0.6 to identify the "bounce zone." The trend filter's job is to eliminate Spring signals during downtrends (where they're "falling knives"). EMA does this slightly better than SMA because it's more responsive to trend changes.

### Why the Tradeoff (Higher DD)

The -4.5pp worse drawdown comes from two sources:
1. **More trades = more exposure.** More signals means more opportunities for adverse excursions.
2. **Trend transition whipsaws.** During choppy markets (e.g., 2024-2025), the EMA50 crosses EMA200 multiple times, generating signals that SMA200 filters out. Some of these are losers.

However, the net effect is positive: +11% more compound return for -4.5pp more drawdown. This is a favorable risk/reward tradeoff.

### The "Sniper" Filter: SMA200 + PDI>MDI

The combination of SMA200 + PDI>MDI produced extraordinary quality (Sharpe +1.85, PF 3.11, Max DD -4.6%) but only 12 trades in 7 years. This filter requires:
- Price above SMA200 (trend is up)
- PDI > MDI (directional movement is bullish)
- BB %B 0.2-0.6 (price in bounce zone)

This is a "perfect storm" filter — Spring signals in the bounce zone of a confirmed uptrend with bullish momentum. But at 1.7 trades/year, it's not deployable as a standalone strategy. It could be used as a "high-conviction" signal for larger position sizing.

### Limitations

1. **Max DD is still elevated at -13.9%.** While better than unfiltered Spring (-52%), this is worse than the SMA200 baseline (-9.4%). Position sizing and capital allocation must account for this.

2. **The 2022 bear market split is negative for both filters.** Split 3 (2021-06→2022-04, the post-peak bear market) is the only consistently negative split. Spring signals in bear markets remain problematic regardless of the trend filter.

3. **Trades remain sparse.** Even with 98 trades over 7 years, that's ~14 trades/year or ~1.2 trades/month. This is not a high-frequency signal and requires patience.

4. **Cross-validation is BTC-only.** Both exchanges trade the same underlying. True out-of-sample would require testing on different assets (ETH, SOL, etc.).

## Recommendation

### ✅ IMPLEMENT (replace SMA200 with EMA50>EMA200 in Spring strategy)

**For the Spring strategy class (`strategies/spring.py`):**
- Replace SMA200 filter with EMA50>EMA200 crossover
- Update default exits to: stop=3.0%, target=3.0%, hold=32h
- Keep BB %B 0.2-0.6 zone filter (essential)

**Implementation:**
```python
# New trend filter
ema50 = ema(close, 50)
ema200 = ema(close, 200)
trend_filter = ema50 > ema200

# Replace: sma200_filter = close > sma(close, 200)
```

**Parameter changes:**
- `sma200_filter` → rename to `trend_filter` or add `ema_crossover_filter`
- `stop_pct`: 3.0% (unchanged)
- `target_pct`: 2.5% → **3.0%**
- `hold_hours`: 24 → **32**

### Next Steps

1. **Implement in strategy class.** Update `strategies/spring.py` to use EMA crossover.
2. **Multi-pair validation.** Test on ETH/USDT and other pairs when data is available.
3. **Position sizing.** Given -13.9% Max DD, use fractional position sizing (e.g., 25% of capital per trade).
4. **Live paper trading.** Deploy as cron job with EMA filter, track real-time performance vs backtest.
5. **Combine with BB Breakout for regime detection.** Use BB Breakout signals as additional uptrend confirmation (exploratory).

## Reproduction

```bash
# Filter comparison (all trend filters)
uv run python research/backtest_spring_filter_compare.py

# Exit optimization for EMA filter
uv run python research/backtest_spring_exit_opt_ema.py

# Final validation (walk-forward + Binance cross-val)
uv run python research/backtest_spring_ema_final.py

# BB Regime experiment (negative result — documented for completeness)
uv run python research/backtest_bb_regime_spring.py
```

## References

- Spring Reversal regime analysis: `docs/research/spring/research_regime_analysis_v1.md`
- Spring exit optimization: `docs/research/spring/research_exit_optimization_v1.md`
- BB Breakout strategy: `docs/research/bb_breakout/STRATEGY.md`
- Sharpe ratio benchmarks: `references/sharpe-ratio-benchmarks.md`
