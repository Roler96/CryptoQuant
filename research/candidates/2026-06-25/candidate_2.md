# Candidate 2: VolSpikeReversal

**Date:** 2026-06-25
**Source:** BTC Mean Reversion Strategy (Adrian Keller, Medium Dec 2025) + anti-pattern lesson
**Type:** Mean reversion WITH trend/regime filter

## Hypothesis
Volatility spikes + Bollinger Band extremes + volume surges identify
mean-reversion opportunities — but ONLY in ranging markets (ADX < 20).
This directly addresses the RSIBBMeanReversion failure where no trend
filter caused negative Sharpe across all combos.

## Anti-Pattern Check
- ✅ NOT pure mean reversion (ADX ranging filter added)
- ✅ NOT signal-sparse (3 entry conditions + regime gate, reasonable)
- ✅ Directly addresses RSIBBMeanReversion anti-pattern (adds trend filter)
- ✅ Different from EMACrossATRFilter (mean reversion vs. trend-following)

## Strategy Logic

### Indicators
- Bollinger Bands: 20-period SMA ± 2.0 std
- Volatility spike: 20-period volatility / 100-period MA volatility > 1.5
- Volume ratio: current volume / 20-period SMA volume > 1.3
- ADX(14): < 20 = ranging market (our regime filter)
- Returns Z-score: (return - 100-period mean) / 100-period std

### Entry (Long) — ALL conditions required
1. BB position < 0.1 (price near lower Bollinger Band)
2. Volatility spike > 1.5 (elevated volatility)
3. Volume ratio > 1.3 (volume surge = capitulation)
4. Returns Z-score < -2.0 (extreme negative move)
5. ADX < 20 (RANGING MARKET — key anti-pattern fix)

### Entry (Short) — ALL conditions required
1. BB position > 0.9 (price near upper Bollinger Band)
2. Volatility spike > 1.5
3. Volume ratio > 1.3
4. Returns Z-score > 2.0 (extreme positive move)
5. ADX < 20 (ranging market)

### Exit
- Target: Price returns to BB middle band (50% retracement)
- Stop-loss: 3% from entry (tight, mean reversion is short-term)
- Max hold: 48 bars (time-based exit for stalled reversals)

### Signal Convention
- 1 = long, -1 = short, 0 = flat

## Parameters (Default)
```python
{
    "bb_period": 20,         # Bollinger Band period
    "bb_std": 2.0,           # BB standard deviation multiplier
    "vol_short": 20,         # Short volatility lookback
    "vol_long": 100,         # Long volatility lookback
    "vol_spike_threshold": 1.5,  # Min volatility ratio for "spike"
    "vol_ratio_period": 20,  # Volume SMA period
    "vol_ratio_threshold": 1.3,  # Min volume ratio
    "zscore_period": 100,    # Returns Z-score lookback
    "zscore_threshold": 2.0, # Z-score entry threshold
    "adx_period": 14,        # ADX lookback
    "adx_max": 20,           # Max ADX for ranging market entry
    "stop_loss_pct": 0.03,   # 3% stop loss
    "max_hold_bars": 48,     # Max bars to hold
}
```

## Expected Characteristics
- **Target trades/year:** 50-150 (limited to ranging markets, ~30-40% of time)
- **Market regime:** Ranging/consolidating markets only (ADX < 20)
- **Risk:** Mean reversion fails in strong trends — ADX filter eliminates these

## Lesson from Anti-Pattern
RSIBBMeanReversion failed because it traded mean reversion in ALL regimes,
including strong 2025-2026 trends. This strategy gates entries to ranging
markets only (ADX < 20), which should eliminate the worst drawdowns.
