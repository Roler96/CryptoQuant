# Candidate: Vortex Trend (vortex_trend)

**Date:** 2026-06-26
**Source:** GitHub trending / Well-known indicator (Etzkorn, 2010)
**Category:** Trend Following / Directional Movement

## Strategy Description

The Vortex Indicator (VI) measures trend direction by comparing current price extremes to previous bar extremes, weighted by true range. It consists of two oscillators:

- **VI+** = |Current High - Previous Low| / ATR(N)
- **VI-** = |Current Low - Previous High| / ATR(N)

When VI+ > VI- (bullish crossover), trend is up. When VI- > VI+ (bearish crossover), trend is down.

**Entry Conditions (exactly 2):**
1. VI+ crosses above VI- (long) / VI- crosses above VI+ (short)
2. Close > EMA(200) (long) / Close < EMA(200) (short)

**Exit:** VI reverse crossover

## Parameters
- `vi_period=14` — standard Vortex period
- `trend_period=200` — EMA trend filter

## Why This Might Work
- VI is price-action based, not heavily smoothed — generates 50-200 signals/year
- Uses true range normalization (ATR denominator) — self-adapts to volatility
- Unlike Elder Ray/Aroon, VI measures cross-bar movement (directional), not within-bar extremes
- 2 conditions exactly, follows the proven template
- Similar to ADX/DMI but with faster signal response (VI has no smoothing beyond period average)

## Risks / Concerns
- May fail on ETH if cross-bar price extremes are artifacts of fragmented liquidity (like Aroon/CLV/Elder Ray)
- 4h trade count may be borderline (crossover-based indicator on 4h)
- VI hasn't been tested in this research pipeline before — unknown parameter sensitivity

## Gate Thresholds
- min_bars = `vi_period + trend_period + 1 = 215`
