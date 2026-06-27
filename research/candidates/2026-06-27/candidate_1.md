# Candidate 1: ADLineTrend

**Date:** 2026-06-27
**Source:** Cumulative volume family extension (Loop 24 OBV success pattern)
**Anti-pattern check:** PASS — 2 conditions, cumulative not gated, no retrospective, no smoothing >20 bars

## Strategy Concept

**Accumulation/Distribution Line (A/D Line) crossover + EMA200 trend filter.**

A/D Line = cumulative sum of Money Flow Multiplier × Volume, where:
- Money Flow Multiplier = ((Close - Low) - (High - Close)) / (High - Low)
- This measures whether price closed in the upper or lower portion of the bar

Unlike OBV (which only uses sign(Δclose) × volume), A/D Line uses close-position-within-bar weighting. This makes it a hybrid of OBV's cumulative property and position-based weighting — but accumulated (noise averages out) unlike raw CLV which failed in Loop 6.

## Entry Conditions (exactly 2)
1. A/D Line crosses above its SMA(20) → long entry
2. Close > EMA200 → trend filter (only go long in uptrend)

## Exit
- A/D Line crosses below SMA(5) → exit (faster exit than entry for quick reaction)
- Or trailing stop at 2× ATR(14)

## Why this should work
- OBV (same family) achieved 4/4 pass
- A/D Line's close-position weighting adds another dimension — volume on strong-close bars counts more
- Cumulative property preserves signal density on 4h (OBV generated 36 trades on 4h)
- The Money Flow Multiplier normalizes per-bar contribution — ETH noise bars have lower weight
- 2 condition template, no hidden gates

## Expected signal density
- 1h: 150-200 trades/year (similar to OBV's 188-196)
- 4h: 30-40 trades/year (similar to OBV's 36)

## Parameters
- ad_sma_long: 20
- ad_sma_short: 5
- trend_period: 200
- atr_period: 14
- stop_mult: 2.0
- tp_mult: 3.0
