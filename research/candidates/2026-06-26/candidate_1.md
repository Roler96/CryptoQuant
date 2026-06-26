# Candidate 1: Williams %R Trend (Loop 19)

**Date:** 2026-06-26
**Source:** GitHub trending — oscillator-based strategies
**Loop:** 19

## Concept

Williams %R is a normalized momentum oscillator (-100 to 0) measuring where close sits relative to high-low range over N periods. Unlike Stochastic (which uses %K/%D smoothing with Wilders), %R gives a raw, unsmoothed reading — faster than Stochastic, closer to CCI in responsiveness.

## Entry Logic

1. **%R midline crossover**: %R(14) crosses above -50 = bullish; crosses below -50 = bearish
   - Midline cross generates more signals than extreme thresholds (-20/-80)
   - Normalized -100 to 0 scale → works identically across timeframes
2. **EMA200 trend filter**: close > EMA200 = long only; close < EMA200 = short only
   - Exactly 2 AND conditions
   - Trend filter ensures we trade with the prevailing direction

## Exit Logic

- Reverse %R midline cross (bullish→bearish closes long; bearish→bullish closes short)
- Mechanical, no complexity

## Why This Should Work

- **Normalized indicator**: %R is inherently 0-100 scale → same pattern as successful BB %B (4/4 pass)
- **Fast oscillator**: Midline cross fires more frequently than Stochastic's slow %K/%D → more trades
- **Not yet tested**: Unlike RSI, Stochastic, CCI, CMO — Williams %R has never been tried in 18 loops
- **2 conditions**: Clean template, no hidden gates, no smoothing above 20 bars

## Expected Trade Count

- BTC 1h: 120-200 trades (faster than Stochastic at 198)
- BTC 4h: 35-50 trades (faster midline cross vs Stochastic extreme thresholds)
- ETH 1h: 100-180 trades
- ETH 4h: 30-40 trades

## Parameters

- `wr_period=14` (standard Williams)
- `trend_period=200` (EMA200, standard)
- `entry_threshold=-50` (midline)

## Risk Assessment

- Medium — midline cross may be whippy on 1h. Consider adding ATR expansion or testing period=20 for stability.
- ETH 1h OOS risk (standard for all momentum strategies) — but faster oscillator may adapt better than smoothed ones.
