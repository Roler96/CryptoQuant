# Candidate: Chaikin Money Flow Trend (CMFTrend)

**Date:** 2026-06-26
**Source:** Research synthesis — CMF indicator from Chaikin (1980s), adapted for crypto trend following
**Loop:** 10

## Concept

Chaikin Money Flow (CMF) measures volume-weighted accumulation/distribution over N periods. Unlike CLV (which gates entry on bar position and failed in Loop 6), CMF ACCUMULATES the A/D formula over time — this is sum-based (like CMO's success pattern), not position-gating.

Entry: CMF(21) crosses above/below 0 (accumulation is net positive/negative)
Filter: EMA200 trend direction (price > EMA200 = long only)
2 conditions total.

## Rationale

1. CMF is sum-based (∑ volume_weighted_position / ∑ volume) — same mechanism as CMO (sum-based momentum) which succeeded in Loop 12
2. Volume is used as a signal-weight multiplier, not a gate — preserves trade count (Loop 10 Force Index lesson)
3. Entry is fixed-threshold (zero-cross), not crossover — better for 4h viability per Loop 11-12 lessons
4. Normalized-ish: CMF ranges roughly -1 to +1 but zero-cross is the natural threshold
5. A/D accumulation over 21 bars captures genuine institutional flow patterns in crypto

## Anti-Pattern Checks

- ✅ 2 conditions (not ≥3)
- ✅ No Ichimoku disguised gates
- ✅ Not candle pattern-based
- ✅ Not raw price-extreme (doesn't use High/Low as gating, accumulates)
- ✅ Volume is multiplier, not gate
- ✅ Fixed-threshold entry (not crossover that compounds on 4h)
- ⚠️ Uses A/D formula which includes close-position — but ACCUMULATES over time (unlike CLV threshold)
- ⚠️ Smoothing period = 21. Effective conditions = 0 (floor(21/20)=0) per formula

## Expected Performance

- 1h: Should generate 50-150 trades (sum-based, zero-cross, comparable to CMO at 114 trades)
- 4h: May be sparse (20-50 trades) but zero-cross is fixed threshold — better than crossover oscillators
- ETH risk: A/D formula uses close position within bar → may suffer from ETH liquidity fragmentation (like Elder Ray/Aroon)

## Parameters

```python
DEFAULT_PARAMS = {
    "cmf_period": 21,
    "trend_period": 200,
}
```
