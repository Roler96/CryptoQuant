# Candidate 2: Swing Pivot Breakout (Loop 19)

**Date:** 2026-06-26
**Source:** GitHub trending — fractal/ZigZag pattern detection
**Loop:** 19

## Concept

Price action-based swing pivot detection — the simplest form of market structure analysis. A swing high occurs when a bar's high is the highest of the surrounding N bars; a swing low when a bar's low is the lowest. Price breaking above a swing high or below a swing low signals a structural shift — the market is making new extremes, indicating trend continuation or reversal.

This is breakout-based (not oscillator/crossover) → should work on 4h (proven family of entries).

## Entry Logic

1. **Swing pivot breakout**: Price high > previous N-bar swing high (long) OR price low < previous N-bar swing low (short)
   - Pivot detection: peak = bar i is highest high in [i-N, i+N]; trough = bar i is lowest low in [i-N, i+N]
   - No look-ahead bias — pivot identified only after N bars confirm it (i-N...i+N window, entry at next bar after confirmation)
2. **Close direction confirmation**: close > previous close (long) OR close < previous close (short)
   - Simple direction filter — not an AND gate, selects direction of the bar that breached
   - Exactly 2 AND conditions total

## Exit Logic

- Opposite direction signal (bearish breakout closes long; bullish breakout closes short)
- OR trailing stop at 2× ATR(14) for risk management

## Why This Should Work

- **Breakout-based**: Proven family for 4h viability (Dual Thrust: 4/4 pass, BB %B: 4/4 pass, Range Expansion: 4/4 pass)
- **Pure price action**: No smoothing, no adaptive delay, no mathematical transformation — just structural price levels
- **Novel direction**: Swing pivot detection has never been tested in 18 loops. All previous breakouts used channels (Donchian, BB, Keltner) or 1-bar ranges (InsideBar). Structural pivot levels are fundamentally different — they represent market-agreed support/resistance.
- **2 conditions**: Clean template, fast signal generation

## Expected Trade Count

- BTC 1h: 80-150 trades (pivot breakouts fire on structural breaks)
- BTC 4h: 35-60 trades (breakout-based, proven 4h viability)
- ETH 1h: 70-130 trades
- ETH 4h: 30-50 trades (breakout entry avoids 4h oscillator scarcity)

## Parameters

- `pivot_window=5` (N bars on each side for pivot detection → 11 bar window total)
- `use_trailing_stop=true`
- `trailing_stop_atr=14`
- `trailing_stop_mult=2.0`

## Risk Assessment

- Low-moderate — breakout-based. Risk is pivot_window sensitivity: too small = noise pivots, too large = too few pivots.
- ETH risk is lower than oscillator strategies (breakout entries don't suffer the same OOS regime problem).
- 4h should work — structural levels are arguably more meaningful on higher timeframes.
