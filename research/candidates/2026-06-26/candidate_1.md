# DonchianATRBreakout — Turtle Channel Breakout + ATR Expansion

## Source
Classic trend-following literature (Richard Donchian, Turtle Traders).
Adapted from the breakout template proven in Loops 5/6/13/18.

## Hypothesis
20-bar Donchian Channel breakout + ATR expansion confirmation = high signal density (50-150 trades/year) with strong trend-following performance. Previous Donchian test (DonchianEnsemble, Loop 1) failed because 7-channel binomial voting created 3+ effective AND conditions. Standalone 20-bar channel with single ATR filter = 2 conditions exactly.

## Entry Conditions (exactly 2 AND gates)
1. **Breakout**: Close > highest(high, lookback) for long / Close < lowest(low, lookback) for short
2. **ATR Expansion**: ATR(14) > SMA(ATR(14), 50) — volatility expansion confirms genuine breakout

## Exit
Reverse breakout: Close < lowest(low, lookback) for long / Close > highest(high, lookback) for short

## Parameters
- `lookback`: 20 (standard Turtle)
- `atr_period`: 14
- `atr_ma_period`: 50 (same as proven in BBPercentBVolatility, Loop 11)
- `min_bars`: 60

## Expected
- BTC 1h: 80-150 trades, Sharpe 2.0-3.5
- ETH 1h: 70-120 trades, Sharpe 1.5-2.5
- BTC 4h: 30-50 trades, Sharpe 1.5-2.5
- ETH 4h: 25-40 trades, Sharpe 0.5-1.5 (OOS risk)

## Anti-patterns avoided
- 2 conditions only (no hidden gates)
- Breakout-based entry (viable on 4h)
- ATR expansion filter (strongest single confirmation, proven in 3+ loops)
- No smoothing/adaptive delay
- Not previously tested as standalone entry

## Relation to prior work
- DonchianEnsemble (Loop 1): 7-channel binomial vote → 0/4 passed. Root cause was too many conditions, not indicator failure.
- RangeExpansionBreakout (Loop 5): 20-bar channel + ATR expansion, 4/4 passed. Donchian channel is the same mechanic with different boundary definition (highest/lowest vs channel middle).
- BBPercentBVolatility (Loop 11): Normalized channel + ATR expansion, 4/4 passed. Donchian removes the normalization step for cleaner breakout detection.
