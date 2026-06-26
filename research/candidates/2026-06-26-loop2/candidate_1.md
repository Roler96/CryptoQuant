# Candidate: Vortex Indicator Trend

**Date:** 2026-06-26
**Source:** GitHub trending — freqtrade/technical (Vortex Indicator implementation), Wikipedia
**Type:** Directional movement trend-following

## Rationale

The Vortex Indicator (Etienne Botes & Douglas Siepman, 2010) measures directional movement using True Range normalization. Unlike smoothed oscillators (RSI, Stochastic, CMO) that lag behind price, the Vortex uses raw bar-level directional movement (current high vs previous low) — making it fundamentally faster and better suited for crypto's volatile microstructure.

**Why now:** After 13 loops, the research frontier shows:
1. Directional movement indicators (not smoothing-based) are untested — VI is the purest directional measure
2. Range-based normalization (True Range denominator) = self-adapting to volatility, like Dual Thrust's range multiplier
3. 2 conditions: VI crossover + EMA200 trend filter
4. VI+ and VI- are computed per-bar from raw OHLC (not smoothed crossovers) — should generate more signals on 4h than oscillator crossovers

**Key differentiator:** All previous oscillators (RSI, Stochastic, CMO, MACD, AO) smooth price data before generating signals. The Vortex uses raw directional movement with True Range ratio — the signal emerges from the geometric relationship between consecutive bars, not from smoothed statistics.

## Strategy Design

```
Entry (Long):  VI+ crosses above VI- AND close > EMA(200)
Entry (Short): VI- crosses above VI+ AND close < EMA(200)
Exit:          VI reverse crossover (VI+ crosses below VI- for longs)

Where:
  VM_plus  = |high - previous_low|
  VM_minus = |low - previous_high|
  TR       = max(high - low, |high - prev_close|, |low - prev_close|)
  VI+      = sum(VM_plus, N) / sum(TR, N)
  VI-      = sum(VM_minus, N) / sum(TR, N)
```

- **N = 14** (standard Vortex period)
- **EMA200** trend filter (standard from all successful loops)
- **min_bars = 200** (EMA200 warmup covers VI warmup)

## Anti-Pattern Check

- ✅ 2 conditions (VI cross + EMA200) — not ≥3
- ✅ Directional movement based — no smoothing lag, different from all tested oscillators
- ✅ True Range normalization — self-adapting to volatility
- ✅ No CLV, candle patterns, volume percentiles, ADX, hysteresis, raw price extremes
- ✅ Not tested before — new indicator family (31 strategies previously, none used Vortex)
- ⚠️ VI+/VI- ratio comparison — may whipsaw in choppy markets (inherent to all crossover systems)
- ⚠️ ETH — may fail OOS like all oscillators (expect BTC to outperform)

## Expected Outcome

- Should generate 80-200 trades on 1h (VI crosses are frequent because they use raw bar relationships)
- 4h: uncertain — VI uses range normalization, not smoothing, so signals may be frequent enough (>30)
- BTC expected to outperform ETH (consistent pattern across all oscillators)
- If VI generates ≥30 trades on 4h with positive Sharpe, it would be the FIRST non-breakout entry to do so in 6 loops
