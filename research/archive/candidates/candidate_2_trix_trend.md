# Candidate 2: TRIX Trend (Triple Exponential Average)

**Date:** 2026-06-26
**Source:** QuantConnect/Medium — Jack Hutson's TRIX + modern adaptations
**Strategy Type:** Triple-smoothed rate-of-change oscillator, derivative-based

## Rationale

TRIX (Triple Exponential Average) by Jack Hutson is a triple-smoothed rate-of-change indicator. It applies EMA smoothing three times before computing the 1-bar rate of change, creating an extremely smooth oscillator that nonetheless measures pure momentum (first derivative).

Key structural differences from tested indicators:
- **vs EMA Slope (Loop 14):** EMA Slope = diff(EMA_fast, EMA_slow) → raw derivative of two EMAs. TRIX = ROC(EMA(EMA(EMA(close)))) → triple-smoothed derivative of raw price. TRIX eliminates more noise.
- **vs MACD (Loop 5):** MACD = EMA_fast - EMA_slow → one level of smoothing. TRIX = 3 levels of smoothing + ROC → more noise rejection.
- **vs Fisher Transform (Loop 18):** Fisher = Gaussian transform of normalized price → mathematical transformation. TRIX = pure smoothing + momentum → simpler, more direct.

**Key advantage:** TRIX is a "leading indicator" in the same vein as Fisher Transform — it produces signals earlier in the cycle than standard oscillators because the derivative captures the inflection point, not the absolute level. Combined with strong noise rejection from triple smoothing, this may produce high-quality signals on noisy crypto data.

## Entry Logic (2 conditions)

1. **TRIX > TRIX signal line** — TRIX crosses above its signal SMA (bullish); crosses below (bearish)
2. **Close > EMA200** (long) / **Close < EMA200** (short) — trend direction filter

## Exit Logic

TRIX crosses below signal line (long) / crosses above signal line (short)

## Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| trix_period | 15 | Standard TRIX period (Hutson default) |
| trix_signal | 9 | Signal line SMA period |
| trend_period | 200 | EMA trend filter period |

## Anti-Pattern Compliance

- ✅ 2 AND conditions (TRIX cross + EMA200 trend)
- ✅ Derivative-based entry (ROC of triple-EMA is first derivative)
- ✅ No hidden smoothing gates (trix_period=15, well under 20-bar rule)
- ✅ No raw price-extreme (TRIX is heavily smoothed, immune to ETH wick artifacts)
- ✅ The triple EMA smoothing may help with ETH's fragmented liquidity problem (noise gets smoothed out before ROC is computed)

## Expected Trade Profile

- 1h: 50-120 trades/year (triple smoothing reduces signal frequency vs raw oscillators)
- 4h: 20-35 trades/year (triple smoothing on 4h compounds lag; may push below 30-trade gate)
- Pairs: BTC/USDT, ETH/USDT on 1h and 4h

## Risk: 4h Trade Scarcity

TRIX(15) with triple EMA smoothing on 4h = 15×3 = 45 bars × 4h = 180 hours (7.5 days) of lookback. This compounds the 4h trade scarcity problem documented across 7 oscillator families. TRIX crossover events on 4h may be too sparse (<30/year). Mitigation: if TRIX 4h fails trade count, reduce trix_period to 10 or switch to TRIX threshold-based entry (TRIX > 0 instead of crossover).
