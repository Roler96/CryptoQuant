# Candidate: Linear Regression Channel Breakout

**Date:** 2026-06-26
**Source:** GitHub trending — QuantConnect/Lean indicators (LinearRegressionChannel), statistical trading literature
**Type:** Statistical breakout trend-following

## Rationale

Linear Regression Channel builds a linear regression line over N bars with standard error bands. Unlike Bollinger Bands (horizontal SMA ± 2σ) or Keltner Channels (horizontal EMA ± ATR), the LinReg channel's centerline slopes with the trend. This makes it:
1. **Trend-aware** — the channel tilts with the prevailing trend, unlike horizontal bands that get breached purely by trend drift
2. **Statistically grounded** — standard error bands have known probability interpretation (unlike arbitrary multipliers in Donchian/Keltner)
3. **R² as filter** — the coefficient of determination measures how well the linear trend fits. R² > 0.3 removes random-walk noise without AND-gating price action

**Why now:** After 13 loops, we know breakout-based entries are the ONLY viable 4h entry type. But all tested breakouts use either:
- Fixed horizontal bounds (Donchian, Dual Thrust N-bar range)
- Horizontal SMA-based bounds (Bollinger %B, Keltner)
None have used a trend-sloping channel. LinReg channel breakouts should generate FEWER false signals in trending periods (because the band slopes with trend), while preserving genuine regime-change signals (breakout above a sloped channel = acceleration).

**Key differentiator:** The channel's slope adapts to the trend, so in a strong uptrend, the upper band rises with price — reducing false breakout signals that horizontal bands generate. In consolidation, the channel flattens and functions like BB/Keltner.

## Strategy Design

```
1. Compute linear regression line over N bars:
   - slope, intercept, residuals
   - centerline = intercept + slope × bar_index
   - std_error = std(residuals)
   - upper_band = centerline + K × std_error
   - lower_band = centerline - K × std_error
   - R² = 1 - (SS_residual / SS_total)

2. Entry (Long):  close > upper_band AND R² > 0.3 AND close > EMA(200)
3. Entry (Short): close < lower_band AND R² > 0.3 AND close < EMA(200)

4. Exit: close crosses back inside channel (close < centerline for longs)
```

Wait — this is 3 conditions (breakout + R² + EMA200). That violates the 2-condition rule!

**Fix:** Drop EMA200 and use R² as the sole filter:
```
Entry (Long):  close > upper_band AND R² > 0.3
Entry (Short): close < lower_band AND R² > 0.3
Exit:          close crosses centerline
```

This gives exactly 2 conditions. R² serves double duty: trend quality filter (like EMA200) AND noise filter. The channel itself provides direction (upper band = bullish, lower band = bearish).

**Parameters:**
- **N = 20** (regression lookback — matches BB period standard)
- **K = 2.0** (standard error multiplier — matches BB 2σ convention)
- **R² threshold = 0.3** (minimum trend quality — below this = random walk, no entry)
- **min_bars = 200** (regression needs 20 bars minimum)

## Anti-Pattern Check

- ✅ 2 conditions (breakout + R² > 0.3) — not ≥3
- ✅ Breakout-based → viable on 4h (breaks the 4h oscillator curse)
- ✅ Statistical, not smoothed — regression is a direct fit, no recursive smoothing
- ✅ No ADX, CLV, candle patterns, volume percentiles, hysteresis
- ✅ Not tested before — new indicator category (regression-based vs all previous band/oscillator families)
- ✅ R² is normalized 0-1 → should work across timeframes like %B (Loop 11 success)
- ⚠️ R² > 0.3 may be too high on 4h choppy periods, causing trade scarcity
- ⚠️ Regression on volatile crypto may produce wide bands → fewer breakouts

## Expected Outcome

- Should generate 30-80 trades on 4h (breakout-based + sloping channel reduces false signals)
- 1h: 60-150 trades (R² filter removes ~50% of noise entries)
- BTC expected to outperform ETH (consistent pattern)
- R² filter may be the key to ETH robustness — ETH's choppy periods have low R² and would be filtered out
- If this works, LinReg channel becomes the 4th proven 4h breakout template (joining Dual Thrust, BB %B, Range Expansion)
