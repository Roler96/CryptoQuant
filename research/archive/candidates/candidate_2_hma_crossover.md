# Candidate 2: Hull Moving Average Crossover Trend

**Date:** 2026-06-29
**Source:** Sunday free search — reduced-lag moving average domain
**Status:** Candidate

## Concept

Hull Moving Average (HMA) uses weighted moving averages and square-root smoothing to virtually eliminate lag while preserving smoothness. Standard EMA/SMA crossovers generate late entries; HMA produces more timely signals by design. This is the simplest reduced-lag MA we haven't tested yet (we tested KAMA which failed 4h due to adaptive smoothing compounding lag).

## Entry Signal (2 conditions)

1. **Condition 1 — HMA crossover:**
   - Compute fast HMA (period `hma_fast`, e.g., 16) and slow HMA (period `hma_slow`, e.g., 32)
   - Long when HMA_fast > HMA_slow
   - Short when HMA_fast < HMA_slow

2. **Condition 2 — Trend direction filter:**
   - Long only when close > EMA(`trend_period`)
   - Short only when close < EMA(`trend_period`)

## HMA Formula

```
WMA1 = WMA(price, period/2)
WMA2 = WMA(price, period)
raw = 2 * WMA1 - WMA2
HMA = WMA(raw, sqrt(period))
```

Where WMA = linearly weighted moving average.

## Exit

- Exit long when HMA_fast crosses below HMA_slow (reverse crossover)
- Also exit if price crosses EMA(trend_period) against position direction

## Why This Is Different From Prior MA Strategies

| Strategy | MA Type | Lag | Result |
|----------|---------|-----|--------|
| EMACrossATRFilter | EMA(12/26) | Medium | ✅ 4/4 passed |
| KamaTrend | KAMA (adaptive) | High (4h) | ⚠️ 1h only |
| HMACrossoverTrend | HMA (reduced-lag) | Low | **Untested** |

HMA sits between EMA (standard lag) and KAMA (variable/high lag). It reduces lag without the adaptive slowdown that killed KAMA on 4h.

## Expected Characteristics

- Signal count: 80–200 trades/year (HMA crossovers more frequent than EMA due to reduced lag)
- Commission sensitivity: Low–medium (more trades than EMA crossover, but signals are quality)
- 4h potential: Better than KAMA (fixed √n smoothing vs adaptive), but still limited by bar count
- ETH vulnerability: Unknown — first reduced-lag MA in the suite

## Parameter Space

| Parameter | Default | Range |
|-----------|---------|-------|
| `hma_fast` | 16 | 8–32 |
| `hma_slow` | 32 | 16–64 |
| `trend_period` | 200 | 100–300 |
| `min_bars` | 32 | — |

## Anti-Pattern Check

- [x] ≤2 AND conditions (HMA crossover + trend filter)
- [x] No ADX, no Ichimoku, no CLV, no candle patterns
- [x] Not mean-reversion (trend filter ensures trend-following direction)
- [x] No hysteresis, no regime switching
- [x] Entry trigger not gated by volume percentile
- [x] min_bars ≤ 300 (set to 32)
- [x] Not adaptive smoothing on 4h (HMA is deterministic, unlike KAMA)
