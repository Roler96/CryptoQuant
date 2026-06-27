# Candidate 2: PVT (Price Volume Trend) Trend

**Date:** 2026-06-28
**Loop:** 31
**Source:** Internal pattern mining (cumulative volume family variant)

## Rationale

PVT (Price Volume Trend) = cumulative sum of (volume × %price_change). Unlike OBV (which uses sign(close - prev_close) — binary accumulation), PVT uses the proportional price change — more granular, more signals.

PVT is a middle ground between OBV (binary accumulation, rare zero-crosses) and Force Index (per-bar reset, many signals). The cumulative property + proportional weighting should produce 80-150 trades on 1h and 30-45 on 4h — right in the sweet spot.

OBV 4/4 clean sweep proved cumulative volume works. PVT is the natural extension: same accumulation mechanic, but with proportional weighting that should generate more nuanced signals.

## Strategy Design

```
Entry (LONG):  PVT crosses above SMA(PVT, 20) AND Close > EMA200
Entry (SHORT): PVT crosses below SMA(PVT, 20) AND Close < EMA200
Exit:          PVT crosses opposite SMA OR trailing stop at 2× ATR(14)

Conditions: 2 (PVT-SMA crossover + EMA200 trend)
```

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| pvt_sma_long | 20 | Same as OBV SMA — proven 20-bar crossover |
| pvt_sma_short | 5 | Exit signal line |
| trend_period | 200 | Proven EMA200 trend filter |
| atr_period | 14 | Standard ATR |
| trailing_mult | 2.0 | Standard trailing stop |
| min_bars | 150 | Allow sufficient warmup |

## Expected Performance

- **1h BTC:** 100-180 trades, Sharpe 1.5-2.5 (PVT more granular than OBV = more trades)
- **1h ETH:** 100-180 trades, Sharpe 0.5-1.5 (cumulative property smooths ETH noise)
- **4h BTC:** 30-45 trades, Sharpe 1.0-2.0 (proportional weighting should fire more than binary OBV)
- **4h ETH:** 25-40 trades, Sharpe 0.5-1.5

## Anti-Pattern Check

- ✅ 2 AND conditions only
- ✅ Not a raw price-extreme indicator
- ✅ Not triple-smoothed
- ✅ Cumulative volume family (proven)
- ✅ Proportional weighting generates more signals than binary OBV
- ✅ SMA crossover on cumulative line (not zero-cross of cumulative line — avoids TMF-style sparsity)
- ✅ Not previously tested
