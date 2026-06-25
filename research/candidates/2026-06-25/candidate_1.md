# Candidate: ElderRayTrend

## Source
Alexander Elder, "Trading for a Living" (1993). Elder Ray is the difference between price extremes and an EMA — a measure of buying/selling pressure relative to trend.

## Strategy Logic
**2 entry conditions:**
1. Bull Power (High - EMA(13)) > 0 → buying pressure above equilibrium
2. Close > EMA(200) → trend filter (only long in uptrend)

**Exit:** Bull Power crosses below 0 (buying pressure exhausted)

**Short side:** Bear Power (Low - EMA(13)) < 0 AND Close < EMA(200), exit on Bear Power > 0

## Why This Might Work
- Elder Ray is a raw pressure measure — no smoothing, no normalization. It's faster than RSI, Stochastic, or MACD.
- Counter-example to the "oscillator on ETH fails" pattern: Elder Ray uses High/Low extremes, not smoothed close-based metrics. The extremes capture genuine buying/selling pressure that smoothed oscillators miss.
- 2 conditions only. No AND-gates, no regime switching, no hysteresis.
- Single exit condition = reverse signal. Clean.
- Bull/Bear Power naturally works with trends — it measures whether bulls or bears are winning the bar, then EMA200 confirms direction.

## Anti-Pattern Check
- NOT mean reversion (avoided → no trend filter needed)
- NOT ≥3 conditions (2 only)
- NOT Ichimoku (no cloud spans)
- NOT ADX-based (no lag problem on 4h)
- NOT CLV/position-based (uses price extremes, not bar-location)
- NOT candle pattern (uses actual price levels, not bar-shape recognition)

## Parameters
- ema_period: 13 (standard Elder)
- trend_period: 200
- min_bars: 200

## Expected Behavior
- Fast oscillator: Bull Power zero-crosses frequently → 80-200 trades/year on 1h
- With EMA200 trend filter → likely 60-120 trades/year
- On 4h: fewer zero-crosses but power measure is scale-independent → 25-50 trades/year
- Both sides (long + short) should produce double the signal density
