# Candidate: Dual Thrust Breakout

**Date:** 2026-06-26
**Source:** GitHub trending — je-suis-tm/quant-trading (Dual Thrust strategy)
**Type:** Breakout trend-following

## Rationale

Dual Thrust is a classic breakout strategy developed by Michael Chalek in the 1980s. It uses the N-day range (high-low) to set upper and lower breakout bounds. Unlike Donchian channels (which track rolling high/low), Dual Thrust uses a lookback range multiplied by coefficients to set the bounds — making it self-normalizing to recent volatility.

**Why now:** After 12 loops, the research frontier is:
1. 4h breakout strategies (only breakout-based entries work on 4h)
2. ETH-resistant strategies
3. Range-normalized indicators (like %B success in Loop 11)

Dual Thrust satisfies all three:
- It's a breakout strategy → should generate trades on 4h
- The range multiplier adapts to volatility → normalized entry
- 2 conditions: price > upper bound + EMA200 trend filter

## Strategy Design

```
Entry (Long):  close > Open + K1 × Range(N) AND close > EMA(200)
Entry (Short): close < Open - K2 × Range(N) AND close < EMA(200)
Exit:          price crosses opposite bound OR signal reverses
```

- **Range(N)** = Max(HH - LC, HC - LL) over N bars (Dual Thrust original)
- **K1 = 0.5** (upper coefficient), **K2 = 0.5** (lower coefficient)
- **N = 20** (lookback period)
- **EMA200** trend filter

## Anti-Pattern Check

- ✅ 2 conditions (breakout + trend filter) — not ≥3
- ✅ Breakout-based → viable on 4h (unlike oscillator crossovers)
- ✅ No CLV, candle patterns, volume percentiles, ADX, hysteresis
- ✅ Range-normalized → self-adapting to volatility
- ✅ Not tested before — different from Donchian, InsideBar, BB, Channel

## Expected Outcome

- Should generate 30-80 trades on 4h (breakout pattern), 80-200 on 1h
- BTC expected to perform better than ETH (consistent pattern)
- Risk: range normalization may be insufficient for ETH's fragmented liquidity
