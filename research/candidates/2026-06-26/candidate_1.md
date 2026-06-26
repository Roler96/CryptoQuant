# ZScoreMomentumTrend — Z-Score Normalized Momentum Trend Following

**Discovered:** 2026-06-26 (Saturday — QuantConnect/Medium search)
**Source:** Medium article "Systematic Crypto Trading Strategies" by Brian Plotnik (Jun 2025)
**Loop:** 20

## Core Idea

Normalize price momentum using Z-score (how many standard deviations current return is from historical mean). This is mathematically distinct from all previously tested momentum normalizations:
- **CMO:** sum-based normalization (sum_up - sum_down)/(sum_up + sum_down)
- **RiskAdjustedMomentum:** return / annualized_volatility (ratio-based)
- **Fisher:** Gaussian distribution transformation via hyperbolic arctangent
- **Z-score:** (return - mean_return) / std_return — probability-based normalization

Z-score measures statistical unusualness: a Z-score of +1.5 means current returns are 1.5 standard deviations above the mean. This naturally filters out noise (small Z-scores) while capturing genuine momentum regime shifts (large Z-scores).

## Strategy Design

**Entry Conditions (2 total):**
1. Z-score(close returns, period=20) > 0.5 → long signal; < -0.5 → short signal
2. Close > EMA(200) for long filter; Close < EMA(200) for short filter

**Exit:**
- Z-score crosses 0 (return to mean) — or signal reverse

**Parameters:**
- `zscore_period=20` — rolling window for mean/std calculation
- `entry_threshold=0.5` — minimum Z-score for entry (0.5 = 0.5σ above mean)
- `trend_period=200` — EMA trend filter period
- `min_bars=200` — warmup period

**Expected Trade Count:**
- 1h: 80-200 trades (crypto returns are volatile, Z-scores cross threshold frequently)
- 4h: 20-40 trades (Z-score is less reliant on crossovers than oscillator-based entries)

## Why It Should Work

1. **Z-score normalizes for volatility regimes automatically.** When volatility spikes, the denominator (std) increases, preventing false signals from noisy large moves. When volatility is low, smaller absolute moves can still trigger if they're statistically unusual.

2. **The 0.5σ threshold is a soft gate** — not a hard AND condition like "volume > 95th percentile". Many bars cross 0.5σ, preserving trade count.

3. **Z-score is dimensionless and timeframe-agnostic.** Unlike indicators with fixed period effects (ADX threshold must scale with timeframe), Z-score's statistical meaning is the same on 1h and 4h.

4. **Different from CMO:** CMO uses sum of positive vs negative returns → smoothed by Wilder. Z-score uses raw statistical normalization → faster response to regime changes.

## Anti-Pattern Compliance

- ✅ 2 entry conditions (Z-score threshold + EMA200 trend)
- ✅ No smoothing beyond zscore_period (20 is reasonable, < 20-bar effective condition threshold)
- ✅ No hidden AND gates (threshold > 0.5 is permissive, not eliminating 70%+ of signals)
- ✅ Not a raw price-extreme indicator (uses statistical normalization)
- ✅ Not candle-pattern based (uses returns, not bar structure)
- ✅ Not CLV/ER-based (doesn't measure market efficiency or bar position)
