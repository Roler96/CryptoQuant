# Candidate: Linear Regression Trend (linreg_trend)

**Date:** 2026-06-26
**Source:** Quantitative finance literature / Statistical methods
**Category:** Trend Following / Statistical Quality

## Strategy Description

Linear regression applied to price over a rolling window measures trend strength and direction statistically. Two metrics are used:

- **R² (coefficient of determination):** Measures how well price fits a linear trend (0-1). High R² = strong trend.
- **Slope:** Direction of the trend (positive = uptrend, negative = downtrend)

**Entry Conditions (exactly 2):**
1. R² > 0.7 (trend is statistically significant — price moves directionally, not randomly)
2. Close > EMA(100) (long) / Close < EMA(100) (short) — confirms trend direction

**Exit:** R² drops below 0.3 (trend weakens) OR trend reverses direction

## Parameters
- `linreg_period=30` — window for linear regression (30 bars)
- `r2_entry=0.7` — minimum R² to enter
- `r2_exit=0.3` — R² threshold for exit
- `trend_period=100` — EMA for directional filter

## Why This Might Work
- R² is a statistical measure of trend "quality" — directly measures what trend-followers want
- Unlike smoothed indicators (MACD, EMA crossover), R² responds to actual linearity, not moving-average lag
- 2 conditions — R² quality check + EMA direction
- Normalized metric (0-1) — works across timeframes without threshold tuning
- Similar to %B success pattern (normalized filter + directional filter)
- Generates signals on price structure, not oscillator extremes

## Risks / Concerns
- 4h: 30-bar linear regression = 5 days of data — R² may change slowly, reducing trade count
- ETH: R² may detect false trends from noise (ETH's microstructure)
- May produce fewer trades than price-action breakouts (30-50 vs 100+)
- R² at 0.7 might be too strict — could need relaxation to 0.5 for sufficient trade count

## Gate Thresholds
- min_bars = `linreg_period + 5 = 35`
