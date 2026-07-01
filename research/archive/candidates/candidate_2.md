# Strategy Candidate: RainbowEMATrend

**Generated:** 2026-06-28
**Source:** Internal pattern transfer — dual EMA crossover template with EMA slope direction filter
**Anti-pattern check:** No divergence, no ADX, no CLV, no cumulative volume, no TMF zero-cross, no Z-score threshold. 2 true AND conditions (EMA crossover + EMA slope direction). No hidden gates.

## Strategy Concept

Dual EMA crossover (fast/slow) combined with an EMA slope confirmation filter.
Entry when fast EMA crosses above slow EMA AND slow EMA is sloping upward (current > N bars ago).
This is the classic "Golden Cross/Death Cross" with an additional momentum filter that prevents
entries during flat/choppy markets. The slope filter acts as a directional quality gate without
adding latency since it uses a simple bar-offset comparison (no smoothing).
2 true AND conditions. Instantaneous crossover trigger — should generate 100-200 trades/year on 1h.

## Pseudocode

```
ema_fast = EMA(close, fast_period)
ema_slow = EMA(close, slow_period)
ema_slow_prev = ema_slow.shift(slope_period)

# Long: fast crosses above slow AND slow EMA is rising
if ema_fast > ema_slow AND ema_fast.shift(1) <= ema_slow.shift(1):
    if ema_slow > ema_slow_prev:
        signal = 1

# Short: fast crosses below slow AND slow EMA is falling
elif ema_fast < ema_slow AND ema_fast.shift(1) >= ema_slow.shift(1):
    if ema_slow <= ema_slow_prev:
        signal = -1

# Exit on reverse crossover (regardless of slope)
elif position == 1 AND ema_fast < ema_slow:
    exit
elif position == -1 AND ema_fast > ema_slow:
    exit
else:
    signal = 0
```

## Expected Indicators

- [x] EMA (pandas ewm)

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| fast_period | 8-20 | 12 | Fast EMA period |
| slow_period | 24-50 | 26 | Slow EMA period |
| slope_period | 3-10 | 5 | Lookback bars for EMA slope direction |
| min_bars | 50-200 | 100 | Minimum bars (enough for EMA stabilization + slope lookback) |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.5 | EMA crossover strategies average Sharpe 1.5-2.5 on crypto 1h |
| MaxDD | <40% | <30% | Slope filter prevents entries during flat markets |
| Win Rate | >38% | >50% | EMA crossover win rates ~40-50% with trend filter |

## References

- [EMACrossATRFilter Loop 1 — 4/4 pass](patterns.md#successful-patterns-2026-06-25-loop-1)
- [Dual EMA crossover concept](https://www.investopedia.com/terms/g/goldencross.asp)

## Implementation Notes

- Use `DEFAULT_PARAMS` dict, never hardcode
- Signal convention: 1=long, -1=short, 0=flat
- Return Series same length as input DataFrame
- Crossover detection uses bar-shift comparison (SHOULD be shift(1) comparison, not a separate indicator)
- Exit condition triggers on reverse crossover regardless of slope filter — mechanical, no delay
- min_bars=100 to allow both EMAs + slope lookback to initialize
- All indicators computable from OHLCV using pandas .ewm()
- The slope filter effectively acts as a "trend strength" gate without requiring ADX
