# Candidate: ADX Slope Trend (ADXSlopeTrend)

**Discovered:** 2026-06-28 (Sunday — free search)
**Source:** Research synthesis — ADX derivative as entry signal
**Status:** Candidate (not yet implemented)

## Motivation

ADX has been tested twice in this project:
- **MacdAdxTrend (Loop 5):** ADX > 25 as threshold gate + MACD crossover. Works on 1h, catastrophic on 4h (Sharpe=-0.15 on BTC 4h).
- **KeltnerBreakoutADX (Loop 2):** ADX > 25 as threshold gate + Keltner breakout. Only 9-11 trades on 4h.

Both used ADX as a **static threshold gate** (ADX > 25), which is the standard but flawed approach. ADX(14) on 4h requires 56 hours (2.3 days) to cross 25 — by which time the trend is mature and near exhaustion.

**Novel approach:** Use the **ADX slope** (ADX[t] - ADX[t-1] > 0) as the entry trigger. Instead of waiting for a specific strength level, enter when trend strength is **increasing** — detecting trend intensification early, not trend existence late. This should solve the 4h lag problem entirely.

## Strategy Design

**Entry (LONG):**  ADX slope > 0 AND Close > EMA200
**Entry (SHORT):** ADX slope < 0 AND Close < EMA200
**Exit:**          ADX slope reverses direction OR trailing stop at 2× ATR(14)

## Condition Analysis

- **2 AND conditions:** ADX slope check + EMA200 trend filter
- **No hidden smoothing gate:** ADX(14) has standard Wilder smoothing (1× EMA layer), not ≥2 layers. Effective conditions = 2.
- **ADX slope zero-cross frequency:** ADX oscillates around its moving average, slope crosses zero ~2-3× more often than ADX crosses 25. Should generate 80-200 trades on 1h and 25-50 on 4h.

## Expected Performance

| Combo | Est. Trades | Est. Sharpe | Notes |
|-------|-------------|-------------|-------|
| BTC 1h | 120-200 | 1.0-2.5 | ADX slope fires frequently on 1h |
| BTC 4h | 30-50 | 0.8-2.0 | Slope approach should solve 4h lag |
| ETH 1h | 100-180 | 0.3-1.5 | ADX is not raw price-extreme — may handle ETH better than ElderRay/Aroon |
| ETH 4h | 25-40 | 0.3-1.2 | ETH 4h is always marginal; close to 30-trade gate |

## Anti-Pattern Check

- ✅ Not raw price-extreme on ETH (ADX uses True Range + smoothed directional movement)
- ✅ Not ≥3 conditions (exactly 2)
- ✅ Not candle-pattern based
- ✅ Not deeply smoothed (ADX = Wilder EMA, 1 layer)
- ✅ Signal generator is frequent enough (ADX slope oscillates, unlike ADX>25 threshold)
- ⚠️ May suffer 4h OOS trade count if <43 trades/year — monitor

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| adx_period | 14 | Standard Wilder ADX period |
| trend_period | 200 | EMA trend filter |
| trailing_mult | 2.0 | ATR multiplier for trailing stop |

## References

- Wilder, J. Welles. "New Concepts in Technical Trading Systems" (1978) — ADX/DMI original
- Loop 5 anti-pattern: ADX threshold > 25 kills 4h viability (56-hour lag)
- Loop 17: Vortex (+DM/-DM) works on 4h because it measures raw directional movement, not smoothed strength
