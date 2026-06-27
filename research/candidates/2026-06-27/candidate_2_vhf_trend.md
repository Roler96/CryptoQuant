# Strategy Candidate: VHF Directional Trend (VHFTrend)

**Generated:** 2026-06-27
**Source:** Research synthesis — Vertical Horizontal Filter (Adam White, 1991), adapted for crypto trend-following with directional price filter

## Strategy Concept

The Vertical Horizontal Filter (VHF) measures trendiness: high VHF = the market is trending directionally; low VHF = the market is choppy/mean-reverting. VHF = |close - close(N ago)| / sum(|close - close_prev|, N periods). When VHF crosses above a threshold, the market has entered a trending regime. Combined with a simple directional filter (price vs SMA), this creates a 2-condition entry: VHF > threshold AND price > SMA(50) → long; VHF > threshold AND price < SMA(50) → short. Exit when VHF drops below a lower threshold (trend ending) or when the directional filter reverses. This is fundamentally different from all previous strategies — it filters on market REGIME (trending vs choppy) rather than signal quality. The core insight: any directional entry works in a trending market; the skill is knowing when you're in one.

## Pseudocode

```
# Indicators
vhf = abs(close - close.shift(N)) / rolling_sum(abs(close - close.shift(1)), N)  # 0 to 1
sma = sma(close, sma_period)

# Entry (2 conditions)
long_entry = (vhf > vhf_entry_threshold) AND (close > sma)
short_entry = (vhf > vhf_entry_threshold) AND (close < sma)

# Exit
long_exit = (vhf < vhf_exit_threshold) OR (close < sma)
short_exit = (vhf < vhf_exit_threshold) OR (close > sma)

# Signal: 1=long, -1=short, 0=flat
```

## Expected Indicators

- [x] VHF — needs new implementation in signals.py
- [x] SMA — already in signals.py

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| vhf_period | 14-30 | 20 | VHF lookback period |
| vhf_entry | 0.30-0.50 | 0.40 | Entry threshold (trending) |
| vhf_exit | 0.15-0.30 | 0.25 | Exit threshold (trend ending) |
| sma_period | 30-100 | 50 | Directional filter period |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.5 | Regime filter prevents entries in chop — should improve win rate vs simple trend filters. Fewer trades but higher quality |
| MaxDD | <40% | <30% | VHF exit threshold gets you out when trend ends, not when price reverses against position |
| Win Rate | >40% | >50% | Regime filter should boost win rate above raw directional strategies |

## References

- [Vertical Horizontal Filter — Incredible Charts](https://www.incrediblecharts.com/indicators/vertical_horizontal_filter.php)
- [VHF Indicator — Trend Following Mentor](https://www.trendfollowingmentor.com/blog/vertical-horizontal-filter)

## Implementation Notes

- Signal convention: 1=long, -1=short, 0=flat
- VHF ranges 0 to 1. Higher = more trending. 
- VHF_PERIOD=20 means ~4 weeks of 1h bars to measure trendiness — enough to capture regime shifts
- This is a REGIME-FIRST strategy: filter for trendiness before applying any directional rule
- Unlike ATR expansion (measures short-term volatility burst), VHF measures sustained directional movement
- Add `vhf()` function to `cryptoquant/strategy/signals.py`
- min_bars should include vhf_period + sma_period = 70 bars
