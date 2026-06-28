# Candidate: Qstick Trend (QstickTrend)

**Discovered:** 2026-06-28 (Sunday — free search)
**Source:** Research synthesis — Qstick (Chande's quantitative candlestick oscillator)
**Status:** Candidate (not yet implemented)

## Motivation

Qstick = SMA(close - open, N). It measures the running average of the candle's directional bias — whether buyers or sellers are dominating bar-by-bar. Unlike oscillators that process only the end state (close vs close[t-N]), Qstick captures per-bar conviction.

Qstick belongs to a completely untested indicator family in this project:
- NOT volume-weighted (ForceIndex, MFI, CMF, KVO, Chaikin — all tested)
- NOT smoothed oscillator (RSI, Stochastic, CCI, CMO, Williams %R — all tested)
- NOT price-extreme (Elder Ray, Aroon, AO — all tested)
- NOT breakout (Dual Thrust, BB %B, RangeExpansion — all tested)
- NOT acceleration-based (PSAR, SuperTrend, Vortex — all tested)

Qstick measures **per-bar directional dominance** (not smoothed momentum, not cumulative volume, not structural levels). A rising Qstick means the average candle is closing above its open — buying pressure. A falling Qstick means selling pressure.

## Strategy Design

**Entry (LONG):**  Qstick crosses above 0 AND Close > EMA200
**Entry (SHORT):** Qstick crosses below 0 AND Close < EMA200
**Exit:**          Qstick crosses opposite zero OR trailing stop at 2× ATR(14)

## Condition Analysis

- **2 AND conditions:** Qstick zero-cross + EMA200 trend filter
- **Smoothing:** Qstick = SMA(close-open, N) — 1× SMA layer. Effective conditions = 2.
- **Qstick zero-cross frequency:** Open-close difference changes sign frequently (~30-40% of bars). SMA(14) smooths this to ~50-100 zero-crosses per year on 1h, ~15-30 on 4h. Should generate 80-200 trades on 1h, 30-50 on 4h.

## Comparison to Similar Strategies

| Strategy | Indicator | Smoothing | Tested? |
|----------|-----------|-----------|---------|
| **QstickTrend** | SMA(close-open) | 1× SMA | **NO** |
| CandleConvictionBreakout | body_ratio > 0.6 | 10-bar avg | Yes — 1-6 trades (too strict) |
| ElderRayTrend | High-EMA / Low-EMA | 1× EMA | Yes — ETH failure |
| CMOTrend | sum_up - sum_down | None | Yes — 1h success |

Key difference from CandleConvictionBreakout: Qstick uses the **raw magnitude** of close-open as a weighted signal, not a boolean "body ratio > 0.6". This preserves trade count. A candle with close-open=+1 on a $100 asset still contributes positively to Qstick, whereas body_ratio=0.01 < 0.6 would be filtered out.

## Expected Performance

| Combo | Est. Trades | Est. Sharpe | Notes |
|-------|-------------|-------------|-------|
| BTC 1h | 100-200 | 0.8-2.0 | Qstick zero-cross is frequent on 1h |
| BTC 4h | 30-50 | 0.5-1.5 | Close to 30-trade minimum |
| ETH 1h | 80-180 | 0.3-1.2 | ETH open-close noise may reduce signal quality |
| ETH 4h | 20-35 | 0.2-1.0 | ETH 4h marginal — known hard combo |

## Anti-Pattern Check

- ✅ Not raw price-extreme on ETH (Qstick uses close-open, not high/low)
- ✅ Not ≥3 conditions (exactly 2)
- ✅ Not candle-pattern with strict boolean gates (uses weighted SMA, not threshold)
- ✅ Not deeply smoothed (1× SMA layer)
- ✅ Signal generator is reasonably frequent
- ⚠️ 4h trade count may be marginal (Qstick SMA crossover on 4h = ~30 trades)
- ⚠️ Qstick is close-based — does NOT use high/low, so should be ETH-immune unlike ElderRay/Aroon

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| qstick_period | 14 | SMA period for Qstick (standard Chande) |
| trend_period | 200 | EMA trend filter |
| trailing_mult | 2.0 | ATR multiplier for trailing stop |

## References

- Chande, Tushar. "Beyond Technical Analysis" (1997) — Qstick original definition
- Loop 6: CandleConvictionBreakout failed because body_ratio > 0.6 is too strict. Qstick avoids boolean gating.
- Loop 7: Aroon failed on ETH because high/low are noise. Qstick uses close-open, not high/low.
