# DMI Crossover + EMA200 Trend (DMITrend)

**Source:** Saturday quant blog research (June 27, 2026) — Medium + QuantConnect
**Inspired by:** VortexTrend (Loop 17, 3/4 pass) + Elder's DMI system
**Date:** 2026-06-27

## Strategy Concept

Directional Movement Index (DMI) crossover with EMA200 trend filter. Enter when +DI crosses above -DI (bullish) or -DI crosses above +DI (bearish), filtered by close vs EMA200 for trend direction.

## Why This Should Work

- **Vortex** (Loop 17, 3/4 pass, BTC 1h Sharpe=1.98) uses VI+/VI- which are normalized +DM/-DM. Raw DMI crossover is simpler — no True Range normalization, just smoothed +DM vs -DM comparison.
- DMI crossover fires on genuine directional shifts, not smoothed trend strength (ADX is the smoothed average of |+DI - -DI|).
- Unlike Vortex (which normalizes, softening signals), raw DMI crossover may generate cleaner entry timing.
- EMA200 trend filter is the universal proven confirmation (used in 15+ successful strategies).

## Entry Conditions (2 total)
1. **DMI crossover:** +DI(14) > -DI(14) for long, -DI(14) > +DI(14) for short
2. **EMA200 trend filter:** close > EMA(200) for long bias, close < EMA(200) for short bias

## Exit
- Reverse DMI crossover (opposite direction signal)
- Uses next-bar-open entry (no lookahead)

## Parameters
- `di_period=14` — standard Wilder DMI period
- `trend_period=200` — EMA200 trend filter
- `min_bars=200` — warmup: 200 bars for EMA200 + 14 for DMI

## Known Risks
- Wilder smoothing (alpha=1/14) creates ~13-bar effective lag on DMI lines
- On 4h: 14 bars × 4h = 56 hours lag — may reduce trade count (mitigated by DMI crossover being inherently more frequent than ADX threshold)
- ETH: DMI uses bar extremes (+DM = high-prev_high, -DM = prev_low-low) — may be vulnerable to ETH's wick-driven microstructure (like Elder Ray, Aroon)
- Expected: BTC 1h/4h should pass; ETH 1h/4h uncertain

## Anti-Pattern Check
- ✅ 2 AND conditions (DMI cross + EMA200 trend)
- ✅ Not a raw price-extreme indicator (DMI is Wilder-smoothed)
- ✅ Not triple-smoothed (single Wilder smoothing)
- ✅ Not candle pattern detection
- ⚠️ DMI uses bar extremes — ETH-specific risk per Loops 7, 17
- ⚠️ Wilder smoothing on 4h — trade count risk per Loops 5-22
