# Candidate 2: OBVTrend

**Date:** 2026-06-27
**Source:** On-Balance Volume (Joe Granville, 1963) — classic volume indicator adaptation
**Type:** Volume-Weighted Breakout (Volume family)

## Strategy Description

On-Balance Volume (OBV) is a cumulative volume indicator that adds volume on up-close bars and subtracts volume on down-close bars. It measures whether volume is flowing into or out of an asset.

1. **OBV Calculation:** OBV[t] = OBV[t-1] + volume[t] if close > prev close; OBV[t] = OBV[t-1] - volume[t] if close < prev close; unchanged if close == prev close
2. **Entry Signal:** OBV breaks above its 20-bar highest high → bullish volume pressure. OBV breaks below its 20-bar lowest low → bearish volume pressure.
3. **Trend Filter:** Close above EMA(200) for longs; close below EMA(200) for shorts
4. **Exit:** OBV breaks opposite 20-bar extreme (OBV < 20-bar lowest low for long exit; OBV > 20-bar highest high for short exit)

## Why This Is Novel

- **OBV has NEVER been tested** across 18 research loops
- Force Index (Loop 10), CMF (Loop 14), MFI (Loop 14) were tested — but these all use rate-of-change or ratio calculations
- OBV is **cumulative** — it accumulates volume direction over the entire price history, making it fundamentally different from windowed indicators
- OBV breakout captures shifts in volume regime that windowed indicators miss

## Signal Density Expectation

- OBV breaks 20-bar highs/lows 50-100 times/year on 1h BTC
- On 4h: 15-25 times/year — borderline, but OBV's cumulative nature means breakouts are more significant when they occur
- The trend filter reduces false signals (OBV breakout against trend is ignored)

## Parameters

- obv_lookback=20 (for high/low extremes)
- trend_period=200

## Risk Factors

- OBV is unbounded — the absolute value grows over time, but we only care about relative breakouts
- During strong trends, OBV continuously makes new 20-bar highs → may generate too many/frequent entries on 1h
- 4h trade count may be insufficient (15-25 range)
- OBV divergence (price makes higher high, OBV makes lower high) is a classic signal but NOT used in this strategy — we use simple breakout only

## Relation to Anti-Patterns

- ✅ 2 conditions (OBV breakout + trend filter)
- ✅ Volume acts as signal MULTIPLIER (preserves trade count), not as gate (cf. Volume > percentile anti-pattern)
- ✅ Not a raw price-extreme indicator (OBV is volume-based, safe for ETH)
- ⚠️ 4h trade count is the primary risk — OBV extremes on 4h take ~80 hours to form
- ℹ️ OBV's cumulative nature means earlier data influences current values — ensure backtest uses full history

## References

- Granville, J. (1963). "Granville's New Key to Stock Market Profits"
- Confirms Force Index / MFI pattern: volume-weighted > raw price for ETH robustness (Loop 10, 14)
