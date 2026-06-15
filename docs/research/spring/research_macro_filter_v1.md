# Spring Reversal — Macro Regime Filter: Modest Improvement, Not a Fix

> **One-line summary:** A 200-day return macro filter (avoid trades when 200d return < -40% or > +150%) improves full-period Sharpe from +0.37 to +0.69 (+86%) and Profit Factor from 1.28 to 1.64, but does NOT fix the walk-forward problem. WF remains 5/7 profitable with mean OOS Sharpe +0.47. The filter makes an already-sparse strategy (91 trades/7yr) even more fragile in early periods (1-2 trades per split).

## Hypothesis

The Spring Reversal strategy's #1 limitation is a consistently negative walk-forward split during adverse macro regimes. Previous research (regime analysis v1) found:

| 200d Return | Unfiltered Sharpe | Notes |
|-------------|-------------------|-------|
| Bear (< -20%) | +0.77 | Profitable on unfiltered, but with SMA200 filter these are bear market rallies |
| Strong Bull (> 200%) | -1.77 | 60% stop rate — extreme toxic |
| Bull (50-200%) | -1.80 | Also toxic |

**Hypothesis:** A 200-day return macro filter that avoids both deep bear markets (200d_ret < threshold) and extreme bull markets (200d_ret > threshold) will:
1. Eliminate toxic trades in extreme regimes
2. Fix the negative walk-forward splits
3. Improve full-period Sharpe and WF robustness

## Methodology

### Data
- OKX BTC/USDT 1h: 2019-2026 (65,016 bars)
- Binance BTC/USDT 1h: 2019-2026 (64,933 bars)
- Commission: 5 bps round-trip, Slippage: 5 bps

### Signal
```
Spring Reversal: lookback=20, vol_mult=1.5, close_pct=0.5
Filters: close > SMA(200) AND BB %B in [0.15, 0.65)
Entry: Next bar open after signal
Stop: lows-based (NOT closes-based)
Exit priority: stop_loss > take_profit > time_exit
```

### Macro Filter
```python
ret_200d = close.pct_change(200 * 24) * 100  # 200-day return in %
macro_ok = (ret_200d >= bear_threshold) & (ret_200d <= bull_threshold)
signal = signal & macro_ok
```

### Tested Configurations
11 variants of (bear_threshold, bull_threshold):
- Bear-only: <-30%, <-20%, <-10%, <0%
- Bear+Bull: (-20%, 200%), (-20%, 150%), (-20%, 100%), (-20%, 50%)
- Bear+Bull: (-30%, 200%), (-30%, 150%), (-40%, 150%)

### Validation
1. Full-period backtest on OKX (BacktestEngine, compound returns)
2. 7-split walk-forward on OKX
3. Binance cross-validation (baseline + best variant)
4. Per-regime trade breakdown for best variant

## Results

### Baseline Performance (OKX BTC/USDT 1h, 2019-2026)

```
Trades:             91
Compound Return:    +19.2%
Linear Sum:         +19.4%
Sharpe Ratio:       +0.37
Sortino Ratio:      +0.12
Max Drawdown:       -8.5%
Win Rate:           56.0%
Avg Win:            +1.73%
Avg Loss:           -1.73%
Profit Factor:      1.28

Exit Breakdown:
  take_profit:   31 (34.1%)  avg=+2.40%  total=+74.4%
  stop_loss:     12 (13.2%)  avg=-3.10%  total=-37.2%
  time_exit:     48 (52.7%)  avg=-0.37%  total=-17.8%
```

### Full Comparison Table

| Config | Trades | Return | Sharpe | MaxDD | WR | PF | WF | Mean OOS Sharpe |
|--------|--------|--------|--------|-------|-----|-----|-----|-----------------|
| BASELINE (no filter) | 91 | +19.2% | +0.37 | -8.5% | 56.0% | 1.28 | 4/7 | +0.41 |
| Bear <-30% | 79 | +4.6% | +0.12 | -8.5% | 51.9% | 1.09 | 4/7 | +0.27 |
| Bear <-20% | 77 | +8.4% | +0.20 | -8.5% | 53.2% | 1.15 | 4/7 | +0.27 |
| Bear <-10% | 70 | +6.3% | +0.17 | -9.0% | 52.9% | 1.13 | 4/7 | +0.34 |
| Bear <0% | 62 | -3.4% | -0.05 | -9.2% | 50.0% | 0.96 | 4/7 | +0.18 |
| -20%→200% | 73 | +19.9% | +0.43 | -8.5% | 56.2% | 1.37 | 5/7 | +0.47 |
| -20%→150% | 70 | +25.2% | +0.54 | -8.3% | 57.1% | 1.51 | 5/7 | +0.47 |
| -20%→100% | 67 | +24.8% | +0.55 | -8.3% | 56.7% | 1.53 | 4/7 | +0.32 |
| -20%→50% | 54 | +12.6% | +0.33 | -9.0% | 53.7% | 1.33 | 4/7 | +0.38 |
| -30%→200% | 75 | +15.6% | +0.34 | -8.5% | 54.7% | 1.29 | 5/7 | +0.47 |
| -30%→150% | 72 | +20.7% | +0.45 | -8.3% | 55.6% | 1.41 | 5/7 | +0.47 |
| **-40%→150%** | **80** | **+36.3%** | **+0.69** | **-8.3%** | **58.8%** | **1.64** | **5/7** | **+0.47** |

### Best Configuration — Full Backtest Detail (-40% to +150%)

```
Trades:             80
Compound Return:    +36.3%
Linear Sum:         +32.5%
Sharpe Ratio:       +0.69
Sortino Ratio:      +0.21
Max Drawdown:       -8.3%
Win Rate:           58.8%
Avg Win:            +1.77%
Avg Loss:           -1.54%
Profit Factor:      1.64

Exit Breakdown:
  take_profit:   30 (37.5%)  avg=+2.40%  total=+72.0%
  stop_loss:      7 (8.8%)   avg=-3.10%  total=-21.7%
  time_exit:     43 (53.8%)  avg=-0.41%  total=-17.8%
```

### Walk-Forward: Baseline vs Best Macro Filter (-40% to +150%)

| Split | Period | Base Trades | Base Sharpe | Macro Trades | Macro Sharpe |
|-------|--------|-------------|-------------|--------------|-------------|
| 1 | 2019-10→2020-08 | 12 | +2.06 ✅ | 2 | +1.17 ✅ |
| 2 | 2020-08→2021-06 | 6 | -0.59 ❌ | 1 | +1.10 ✅ |
| 3 | 2021-06→2022-04 | 11 | +0.26 ✅ | 5 | +0.68 ✅ |
| 4 | 2022-04→2023-02 | 8 | -0.01 ❌ | 4 | +1.02 ✅ |
| 5 | 2023-02→2023-12 | 14 | -0.29 ❌ | 8 | -1.05 ❌ |
| 6 | 2023-12→2024-10 | 14 | +0.79 ✅ | 4 | +1.01 ✅ |
| 7 | 2024-10→2025-08 | 16 | +0.65 ✅ | 5 | -0.61 ❌ |

**Baseline:** 4/7 profitable, Mean OOS Sharpe: +0.41
**Macro:** 5/7 profitable, Mean OOS Sharpe: +0.47

**Critical observation:** Splits 1 and 2 drop to 1-2 trades each with the macro filter. The Sharpe numbers for these splits are statistically meaningless — a single profitable trade produces an artificially high Sharpe. The filter is eliminating almost all trades in the earliest periods.

### Per-Regime Breakdown — Best Macro Filter (-40% to +150%)

| Regime | Trades | Sum PnL | Avg PnL | Win Rate | Stop Rate |
|--------|--------|---------|---------|----------|-----------|
| Deep Bear (<-40%) | 0 | — | — | — | — |
| Bear (-40% to -20%) | 10 | +8.8% | +0.88% | 70.0% | 10.0% |
| Weak Bear (-20% to 0%) | 15 | +11.9% | +0.79% | 66.7% | 6.7% |
| Weak Bull (0% to 50%) | 39 | +0.9% | +0.02% | 48.7% | 10.3% |
| Bull (50% to 150%) | 16 | +10.8% | +0.68% | 68.8% | 6.2% |
| Strong Bull (150% to 200%) | 0 | — | — | — | — |
| Extreme Bull (>200%) | 0 | — | — | — | — |

**Key observations:**
1. The filter successfully removes 0 trades from the toxic extreme-bull regimes (>150% 200d return) — exactly the regimes that had 60% stop rates and Sharpe -1.77 in the original analysis
2. Bear market trades that survive (-40% to -20% 200d return) are actually very profitable: +0.88% avg, 70% WR, only 10% stop rate
3. The "Weak Bull (0-50%)" regime dominates with 39/80 trades (49%) but is essentially breakeven (+0.02% avg PnL)
4. The most profitable regimes by per-trade expectancy are the tails: Bear (-40% to -20%) and Bull (50% to 150%)

### Binance Cross-Validation

| Metric | OKX Baseline | OKX Macro | BNC Baseline | BNC Macro |
|--------|-------------|-----------|-------------|-----------|
| Trades | 91 | 80 | 99 | 79 |
| Return | +19.2% | +36.3% | +34.4% | +20.8% |
| Sharpe | +0.37 | +0.69 | +0.57 | +0.43 |
| Max DD | -8.5% | -8.3% | -10.8% | -10.8% |
| Win Rate | 56.0% | 58.8% | 59.6% | 57.0% |
| PF | 1.28 | 1.64 | 1.44 | 1.36 |
| WF Profitable | 4/7 | 5/7 | 6/7 | 5/7 |
| WF Mean Sharpe | +0.41 | +0.47 | +0.63 | +0.57 |

**Binance DOES NOT confirm the improvement.** On Binance, the macro filter DEGRADES Sharpe (+0.57→+0.43) and WF mean Sharpe (+0.63→+0.57). This is a red flag for overfitting to the OKX dataset.

## Analysis

### Why the Bull Filter Helps on OKX

1. **Extreme bull markets are toxic for Spring.** When 200-day return exceeds 150%, every "breakdown" is a buying opportunity for trend followers, not a reversal. The 60% stop rate and Sharpe -1.77 from the original regime analysis confirm this. The bull filter (>150%) removes these trades.

2. **Bear market Spring signals that survive the SMA200 filter are actually good.** The SMA200 filter already eliminates 71% of unfiltered signals. The remaining below-SMA200 trades that fire during bear markets (200d_ret -40% to -20%) are bear market rallies — and surprisingly, they're profitable (70% WR, +0.88% avg). The Spring signal detects genuine failed breakdowns during these counter-trend rallies.

3. **The improvement is driven by stop-loss reduction.** Stop losses drop from 12 (13.2%) to 7 (8.8%) with the macro filter. The eliminated trades were extreme-bull-market trades getting stopped out at -3.1%.

### Why the Bear Filter Doesn't Help

1. **Bear-only filters all degrade performance.** Every bear-only variant (blocking trades when 200d return < threshold) reduces Sharpe below baseline. The bear market Spring signals are profitable — filtering them out removes good trades.

2. **The deepest bear market trades (< -40%) are already blocked by the SMA200 filter.** During severe bear markets, price is below SMA200, so the SMA200 filter already prevents entries. The bear filter is redundant.

### Why This Is NOT a Deployable Improvement

1. **Binance cross-validation fails.** The improvement (+0.37→+0.69 Sharpe) on OKX is not confirmed on Binance (+0.57→+0.43). This suggests the OKX improvement may be data-specific noise.

2. **Walk-forward doesn't meaningfully improve.** WF remains 4-5/7 profitable with mean OOS Sharpe ~+0.47. The macro filter doesn't fix the fundamental issue: the Spring strategy's signal quality is inconsistent across time periods.

3. **Trade count collapses in early periods.** Splits 1 and 2 drop to 1-2 trades — the macro filter eliminates almost all trades in the earliest years because 200-day return was outside the "safe" range. A strategy with 1-2 trades per 11-month split is not statistically reliable.

4. **The improvement is small relative to noise.** With only 80-91 trades over 7 years, the difference between Sharpe +0.37 and +0.69 could be sampling noise. The Binance degradation confirms this suspicion.

5. **52.7% time-exits remain the core problem.** Neither the baseline nor the macro filter addresses the fundamental issue: over half of trades exit via time with an average loss of -0.37%. The macro filter changes WHICH trades fail, not WHY they fail.

### Comparison with Other Spring Improvements

| Research | Method | Sharpe Delta | WF Improvement | Verdict |
|----------|--------|-------------|---------------|---------|
| Regime Analysis | SMA200 + BB 0.2-0.6 | -0.71→+1.53 | 5/6→5/6 | ✅ Works |
| Exit Optimization | Lower target to 2.75%, hold=32h | +1.53→+1.58 | No change | ⚠️ Marginal |
| Vol-Adaptive Exits | Per-regime exits | +1.26→+1.76 | 5/7→5/7 | ✅ Works (custom engine) |
| MTF Confirmation | 4h trend filters | No improvement | No improvement | ❌ Null |
| Cooldown | Consecutive loss pause | No effect | No effect | ❌ Null |
| **Macro Filter** | **200d return gate** | **+0.37→+0.69** | **4/7→5/7** | **⚠️ Marginal, OKX-only** |

The macro filter is the second-weakest improvement after the cooldown. It adds complexity (a 200-day lookback filter) without robust cross-exchange validation.

## Recommendation

### ❌ DISCARD — Macro regime filter is not a viable improvement path

**Rationale:**
- OKX improvement (+86% Sharpe) not confirmed on Binance (Sharpe degrades)
- Walk-forward doesn't meaningfully improve (4/7→5/7, same mean OOS Sharpe)
- Trade count collapses to 1-2 trades in early splits
- Adds complexity (200-day lookback) without robust benefit
- 52.7% time-exits remain the core unresolved problem

### Instead, focus on these proven directions:

1. **Vol-adaptive exits (already proven, needs BacktestEngine integration).** The vol-adaptive research showed Sharpe +1.26→+1.76 with 6/7 Binance WF profitable. The main blocker is that BacktestEngine doesn't support per-trade exit variation. This is the highest-impact engineering task.

2. **Multi-pair deployment.** The Spring strategy's #1 limitation is trade count (~11/year on BTC). Running on ETH, SOL, and other pairs would increase trade frequency and smooth returns. This requires fetching multi-pair data first.

3. **BB Breakout + Spring combined (already proven, needs capital allocation optimization).** The combined strategy has Sharpe +1.36, 6/7 WF. Dynamic capital allocation based on ADX regime (more to BB when trending, more to Spring when ranging) could further improve risk-adjusted returns.

### What We Learned

1. **The Spring strategy's toxic regime is extreme bull markets (>150% 200d return), not bear markets.** The original regime analysis showed this, and the macro filter experiment confirms it: the bull-side filter does the heavy lifting, while bear-side filters are redundant with SMA200.

2. **Binance and OKX give materially different results for Spring.** The macro filter improves OKX Sharpe by 86% but degrades Binance Sharpe by 25%. This is a recurring pattern across multiple Spring research sessions. The signal may have exchange-specific microstructure sensitivity.

3. **Entry filters for Spring have diminishing returns.** The SMA200 + BB %B filters already capture 95%+ of the achievable improvement. Additional filters (MTF, cooldown, macro) add complexity without robust benefit. The remaining edge is in EXIT optimization, not entry filtering.

## Reproduction

```bash
cd /home/roler/Code/CryptoQuant

# Full macro filter research
uv run python research/backtest_spring_macro_filter.py

# Data: OKX + Binance BTC/USDT 1h (2019-2026, ~65k bars each)
# Engine: BacktestEngine with lows-based stop checking
# Commission: 5 bps (round-trip)
# Slippage: 5 bps
```

---

**Document version:** v1
**Date:** 2026-06-16
**Author:** CryptoQuant Autonomous Researcher
**Related:** docs/research/spring/research_regime_analysis_v1.md, docs/research/spring/research_vol_adaptive_exits_v1.md, docs/research/bb_breakout/research_spring_combined_v1.md
