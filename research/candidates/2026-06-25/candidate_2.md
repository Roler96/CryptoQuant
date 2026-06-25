# Candidate 2: ForceIndexTrend — Volume-Weighted Momentum Trend Following

**Date:** 2026-06-25
**Source:** Elder's Force Index (Alexander Elder, "Trading for a Living")
**Type:** Trend-following, volume-weighted momentum

## Rationale

Elder's Force Index combines price direction with volume conviction: `FI = (Close_t - Close_t-1) × Volume_t`, then smoothed with an EMA. The volume multiplication amplifies signals on high-conviction directional moves and mutes noise on low-volume drift. The smoothed FI crossing above zero signals sustained bullish pressure.

**Why this could work:**
- Volume is used as a signal *amplifier* (weight multiplier), not as a gate (percentile threshold) or confirmation (above/below MA). This is a third, untested volume paradigm.
- Crypto's 24/7 trading means volume signals are continuous (unlike equity markets with session boundaries).
- Loop 9's PsarTrend used 100% pure price-action (PSAR + EMA). Force Index adds volume conviction to differentiate genuine directional moves from noise-driven price swings.
- Only 2 AND conditions — obeys the 2-condition rule.

## Entry Conditions (exactly 2 AND conditions)
1. Force Index (smoothed, 13-period) crosses ABOVE zero
2. Close > EMA(200) (trend direction filter)

## Exit Conditions
- Force Index crosses BELOW zero

## Parameters
- `fi_period`: 13 (Elder's recommended default — short enough to be responsive)
- `trend_period`: 200 (EMA trend filter)
- `min_bars`: 200

## Expected Trade Count
- 1h: 80-250 trades/year (FI oscillates frequently, generating many crosses)
- 4h: 30-80 trades/year (crossovers less frequent on higher timeframe)

## Volume Paradigm Classification
| Paradigm | Example | Result |
|----------|---------|--------|
| Volume as gate (%ile threshold) | VolSpikeReversal | Failed (0-3 trades) |
| Volume as confirmation (> SMA) | BBandBreakoutVolume | Passed 2/4 |
| Volume as signal amplifier (multiplier) | ForceIndexTrend | **Untested** |

The key difference: Force Index's volume multiplication makes the signal *proportional* to volume rather than binary (gate/confirmation). Large-volume bars contribute more to the smoothed FI, promoting cleaner zero-cross edges.

## Anti-Patterns Avoided
- ✓ 2 conditions (not ≥3)
- ✓ Volume as amplifier, not gate (not a percentile)
- ✓ No ADX, no CLV, no candle patterns, no Ichimoku
- ✓ Not mean reversion without trend filter
- ✓ Momentum-based but volume-weighted — different from pure momentum (CMO, RSI, Stochastic)

## Risk / Concern
- OKX volume data may not represent total market volume. Single-exchange volume could produce misleading FI signals if large trades occur off-exchange.
- On high-volume outlier bars (liquidation cascades), FI may spike and trigger false entries. The 13-period smoothing partially mitigates this.

## Transferable Hypothesis
If volume-weighted momentum captures genuine conviction better than pure price-action momentum, ForceIndexTrend should produce higher win rates than equivalent pure-price strategies (e.g., MACD-based) with comparable trade counts.
