# Candidate: Awesome Oscillator Trend

**Date:** 2026-06-26
**Source:** GitHub trending — je-suis-tm/quant-trading (Awesome Oscillator), Bill Williams indicators
**Type:** Momentum trend-following

## Rationale

The Awesome Oscillator (AO) is a Bill Williams indicator that measures market momentum as the difference between a 5-period and 34-period SMA of bar midpoints (HL/2). Unlike RSI (smoothed), Stochastic (positional), and CMO (sum-based), AO uses raw SMA of midpoints — a fundamentally different signal generation mechanism.

**Why now:** After 12 loops, CMO (sum-based) showed best Sharpe/quality, but crossover-based oscillators consistently fail on 4h. AO's zero-line crossover is simpler than SMA-of-CMO crossover — the raw difference crossing zero should generate more signals.

**Key differentiator:** AO uses bar midpoints (HL/2), not close prices. This could make it more robust on ETH where close prices are influenced by fragmented liquidity — midpoints average out the exchange-specific extremes.

## Strategy Design

```
Entry (Long):  AO crosses above 0 AND close > EMA(200)
Entry (Short): AO crosses below 0 AND close < EMA(200)
Exit:          AO crosses back across 0
```

- **AO** = SMA(midpoint, 5) - SMA(midpoint, 34)
- **midpoint** = (High + Low) / 2
- **EMA200** trend filter
- **min_bars** = 200 (AO needs 34 bars to initialize)

## Anti-Pattern Check

- ✅ 2 conditions (AO crossover + EMA200) — not ≥3
- ✅ Midpoint-based, not close-based — different from all previous oscillators
- ✅ No CLV, candle patterns, volume percentiles, ADX, hysteresis, raw price extremes
- ✅ Not tested before — different from MACD, Stochastic, RSI, CMO, Force Index
- ⚠️ Crossover-based on 4h — expected to generate fewer trades on 4h (consistent pattern)
- ⚠️ ETH 1h — may fail OOS like all previous oscillators

## Expected Outcome

- Should generate 60-150 trades on 1h (midpoint crossover is more frequent than CMO crossover)
- 4h will likely fail on trade count (< 30) — crossover on 4h is proven anti-pattern
- BTC expected to outperform ETH
- If AO shows positive Sharpe on ETH 1h + passes OOS, it would be the first oscillator to do so in 12 loops (Force Index came close)
