# Candidate 1: SqueezeMomentum

**Date:** 2026-06-27
**Source:** TTM Squeeze (John Carter) adaptation + StratBase ATR research
**Type:** Volatility Contraction → Expansion (Breakout-adjacent)

## Strategy Description

The TTM Squeeze detects periods of low volatility (compression) followed by expansion breakouts. Core mechanics:

1. **Squeeze Detection:** Bollinger Band(20, 2.0) width < Keltner Channel(20, 1.5) width → market is "squeezed" (compressing)
2. **Squeeze Fire:** When BB width expands back above KC width (squeeze releases), volatility expansion is confirmed
3. **Entry:** Squeeze fires + close is above EMA(200) (bullish trend) → go long. Squeeze fires + close below EMA(200) → go short.
4. **Exit:** Opposite squeeze fire OR trailing stop at 2× ATR(14)

## Why This Is Novel

- BB and KC have been tested INDIVIDUALLY (BBPercentBVolatility Loop 11, KeltnerBreakoutADX Loop 2)
- Their INTERACTION (BB inside KC = squeeze) has NEVER been tested
- Squeeze detection is fundamentally different from either BB %B threshold or KC breakout — it measures volatility compression, not price level

## Signal Density Expectation

- Squeeze fires occur 50-150 times/year on 1h BTC (BB width cycles between inside/outside KC ~every 10-30 bars)
- On 4h: 15-30 fires/year — borderline but combined with trailing stop exits on extended squeezes, may still pass 30-trade gate

## Parameters

- bb_period=20, bb_std=2.0
- kc_period=20, kc_multiplier=1.5
- trend_period=200
- trailing_stop_atr=14, trailing_stop_mult=2.0

## Risk Factors

- In strong trending markets (2025-2026), squeeze fires may be rare as BB stays outside KC continuously
- 4h trade count may approach 30-trade minimum
- Need to verify: do we enter on the FIRST bar of squeeze fire, or on a confirmation bar?

## Relation to Anti-Patterns

- ✅ 2 conditions (squeeze fire + trend direction)
- ✅ Not a price-extreme indicator (safe for ETH)
- ✅ Not a smoothed oscillator crossover
- ⚠️ May generate fewer 4h trades — monitor closely
