# Strategy Candidate: BBSqueezeBreakout — Bollinger Band Squeeze + Breakout

**Generated:** 2026-06-27
**Source:** Quant Blog — Bollinger Band Squeeze Pattern (John Bollinger)

## Strategy Concept

Bollinger Band "squeeze" occurs when BB width contracts to a multi-period minimum — signaling low volatility consolidation. When price subsequently breaks out of the contracting bands, it signals the start of a volatility expansion (new trend). Entry: BB width at N-period minimum AND price closes above upper BB (long) or below lower BB (short). No trend filter needed — the squeeze itself identifies regime transitions. Exit on BB middle band (SMA20) cross. 2 total conditions: (1) squeeze detected, (2) price breakout. BB width = (BB_upper - BB_lower) / BB_middle — normalized for cross-symbol consistency. This is fundamentally different from tested breakout strategies (DualThrust, BB% B, InsideBar) because it waits for quiet consolidation periods before entering, targeting the start of directional moves.

## Pseudocode

```
bb_width = (bb_upper - bb_lower) / bb_middle
squeeze_threshold = min(bb_width, squeeze_lookback)
is_squeeze = bb_width <= squeeze_threshold

signal_long  = is_squeeze AND (close > bb_upper)
signal_short = is_squeeze AND (close < bb_lower)
exit_long  = close < bb_middle
exit_short = close > bb_middle
```

## Expected Indicators

- [x] Bollinger Bands — already in signals.py (add squeeze detection helper)
- [x] BB Width calculation — add `bb_squeeze()` helper to signals.py

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| bb_period | 10-30 | 20 | BB moving average period |
| bb_std | 1.5-2.5 | 2.0 | BB standard deviation multiplier |
| squeeze_lookback | 50-200 | 125 | Bars for minimum BB width detection |
| min_bars | 100-200 | 150 | Minimum bars before signal generation |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.8 | Squeeze breakout should produce >30 trades on both 1h and 4h |
| MaxDD | <40% | <30% | Exits at SMA20 — mean-reverting, limiting drawdown duration |
| Win Rate | >40% | >50% | Volatility expansion after squeeze has directional persistence |

## References

- [Bollinger, John. "Bollinger on Bollinger Bands." 2001.](https://www.bollingerbands.com/)
- [Bollinger Band Squeeze — Investopedia](https://www.investopedia.com/terms/b/bollingerbands.asp)

## Implementation Notes

- Use `DEFAULT_PARAMS` dict, never hardcode
- Signal convention: 1=long, -1=short, 0=flat
- Return Series same length as input DataFrame
- Add `bb_squeeze()` to `cryptoquant/strategy/signals.py`:
  - Returns boolean Series indicating squeeze bars
  - bb_width = (bb_upper - bb_lower) / bb_middle (normalized)
  - squeeze = bb_width == bb_width.rolling(squeeze_lookback).min()
- No trend filter needed — BB squeeze itself selects regime transitions (keeps to 2 conditions)
- Uses close price relative to BB — compatible with ETH
- Exit at SMA20 ensures trades don't hang indefinitely
