# Strategy Candidate: MamaFamaTrend

**Generated:** 2026-06-28
**Source:** Paper — John Ehlers, "MAMA – The Mother of Adaptive Moving Averages" (MESA Software)

## Strategy Concept

MAMA (MESA Adaptive Moving Average) uses the Hilbert Transform to measure the rate of phase change in price cycles, then adapts the EMA alpha accordingly. This creates a "fast attack, slow decay" ratcheting behavior — MAMA rushes toward price at cycle turning points, then holds its level during trend continuation. FAMA (Following Adaptive Moving Average) is MAMA applied to MAMA with half the alpha, creating a slower companion. MAMA/FAMA crossover produces a trading system "virtually free of whipsaw trades" (Ehlers). Combined with EMA200 trend filter for directional confirmation = exactly 2 conditions. This is an adaptive/acceleration-based entry that is fundamentally different from standard EMAs because the adaptation is driven by cycle phase measurement, not volatility or efficiency ratio.

## Pseudocode

```
1. Compute Hilbert Transform on median price (H+L)/2:
   - Smooth price with 4-bar WMA
   - Detrend with bandpass filter
   - Compute InPhase (I) and Quadrature (Q) components
   - Compute phase = arctan(Q/I)
   - Compute delta_phase = phase - phase[1]
   - Limit negative delta_phase to minimum 1

2. Adaptive alpha = FastLimit / max(delta_phase, 1)
   - Clamp alpha to [SlowLimit, FastLimit]

3. MAMA = alpha * price + (1 - alpha) * MAMA[1]
4. FAMA = 0.5*alpha * MAMA + (1 - 0.5*alpha) * FAMA[1]
5. ENTRY: MAMA crosses above FAMA AND close > EMA200 → LONG=1
6. ENTRY: MAMA crosses below FAMA AND close < EMA200 → SHORT=-1
7. EXIT: MAMA crosses back below/above FAMA (reverse signal)
```

## Expected Indicators

- [x] EMA — already in signals.py
- [ ] Hilbert Transform components (smooth, detrender, I/Q, phase) — need to add to cryptoquant/strategy/signals.py
- [ ] MAMA/FAMA computation — new in signals.py

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| fast_limit | 0.3-0.7 | 0.5 | Maximum alpha for fast attack |
| slow_limit | 0.01-0.10 | 0.05 | Minimum alpha for slow decay |
| trend_period | 100-300 | 200 | EMA period for trend direction filter |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.5 | Adaptive crossover reduces whipsaw; 2-condition template has 80% pass rate |
| MaxDD | <40% | <30% | MAMA ratcheting holds value during trends, limiting drawdown |
| Win Rate | >35% | >45% | Ehlers' original test showed 37.5% win rate on equities |

## References

- [MAMA – The Mother of Adaptive Moving Averages (Ehlers)](https://www.mesasoftware.com/papers/MAMA.pdf)
- [Ehlers MESA Adaptive Moving Average Trading Strategy (FMZ)](https://www.fmz.com/lang/en/strategy/428090)

## Implementation Notes

- Hilbert Transform requires 7-bar warmup (min_bars=50 for safety)
- Phase computation via arctan2(Q, I) with delta_phase normalization
- Negative delta_phase limited to 1 (not 0) to prevent division issues
- MAMA/FAMA seeded with first price for initial bars
- Add hilbert_transform() and mama_fama() to cryptoquant/strategy/signals.py
- Signal convention: 1=long, -1=short, 0=flat
- Use DEFAULT_PARAMS dict, never hardcode
