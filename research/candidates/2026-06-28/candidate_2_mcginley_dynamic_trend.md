# Candidate: McGinley Dynamic Trend

**Date:** 2026-06-28
**Loop:** 32
**Source:** Free search (Sunday) — low-lag MA indicator family

## Rationale

The McGinley Dynamic is a self-adjusting moving average developed by John McGinley. Unlike standard EMAs (fixed smoothing), HMA (WMA-based), or adaptive MAs (MAMA/FAMA, KAMA — which self-adjust smoothing period), McGinley Dynamic self-adjusts the smoothing **force** based on how far price is from the current value:

```
MD_t = MD_{t-1} + (Close - MD_{t-1}) / (k × N × (Close/MD_{t-1})^4)
```

The denominator's 4th power term makes it:
- Speed up dramatically when price moves away from the MA (strong trend)
- Slow down when price hugs the MA (consolidation)
- Eliminate the false crossovers that plague standard EMA systems during choppy periods

This is fundamentally different from HMA (which uses WMA sqrt(N) weighting for constant lag reduction) and MAMA/KAMA (which self-adjust the period itself). McGinley adjusts the RESPONSE FORCE while keeping the period fixed — potentially solving the 4h trade-scarcity problem that plagues adaptive-period indicators.

## Strategy Template (2 conditions)

1. **Entry:** Close crosses above McGinley Dynamic (long) / below (short)
2. **Trend Filter:** Close > EMA200 (long) / Close < EMA200 (short)
3. **Exit:** Close crosses below McGinley Dynamic (long exit) / above (short exit)

## Parameters

- `md_period=20` — McGinley Dynamic lookback period
- `md_k=0.6` — adjustment constant (0.6 = standard for trending markets; 0.5 for more aggressive)
- `trend_period=200` — EMA trend filter
- `min_bars=200` — minimum warmup bars

## Expected Trade Count

- 1h: 60-150 trades/year (close crosses MA mechanically — similar frequency to EMA crossover)
- 4h: 30-50 trades/year (McGinley's self-adjustment should preserve more crossovers than fixed EMA on 4h)

## Anti-Pattern Check

- ✅ 2 conditions exactly
- ✅ Close vs MA crossover is mechanically frequent (unlike VWAP/HeikinAshi/HA flips)
- ✅ Self-adjusting response force ≠ self-adjusting period (MAMA/KAMA anti-pattern)
- ✅ Not signal-sparse — close crosses any MA 50+ times/year on 1h
- ⚠️ 4h trade count may still be borderline (30-50 target) — McGinley designed to help
- ✅ Not tested in any previous loop
