# Strategy Candidate: HMATrend

**Generated:** 2026-06-26
**Source:** Web Search — Hull Moving Average by Alan Hull (2005), designed to eliminate lag while preserving smoothness

## Strategy Concept

Hull Moving Average (HMA) uses weighted moving averages with a square-root smoothing period to achieve near-zero lag compared to traditional EMAs. The strategy enters long when HMA(20) crosses above HMA(50) AND bar range exceeds 1.5× ATR(14) (expansion confirmation). Exit on reverse crossover. Same ATR expansion filter proven across Loops 5, 6, 11 — but paired with a super-fast MA that avoids the lag problem documented with AO (34-bar smoothing killed signal timeliness in Loop 13).

## Pseudocode

```
fast_hma = HMA(close, period=20)
slow_hma = HMA(close, period=50)
bar_range = high - low
atr_expansion = bar_range > 1.5 * ATR(14)

signal = 0
if fast_hma > slow_hma and atr_expansion:
    signal = 1  # long
elif fast_hma < slow_hma and atr_expansion:
    signal = -1  # short
```

## Expected Indicators

- [x] ATR (already in signals.py)
- [ ] HMA — Hull Moving Average (new to signals.py)

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| hma_fast | 10-30 | 20 | Fast HMA period |
| hma_slow | 30-80 | 50 | Slow HMA period |
| atr_period | 10-20 | 14 | ATR period |
| expansion_mult | 1.0-2.5 | 1.5 | ATR expansion multiplier |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.5 | HMA near-zero lag + proven ATR expansion = high probability |
| MaxDD | <40% | <30% | ATR expansion filters whipsaw chop |
| Win Rate | >40% | >50% | Fast MA crossover with volatility filter |

## References

- [Hull Moving Average — Alan Hull](https://alanhull.com/hull-moving-average)
- [HMA vs EMA: Zero-Lag Comparison](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/hull-moving-average)

## Implementation Notes

- Use `DEFAULT_PARAMS` dict, never hardcode
- Signal convention: 1=long, -1=short, 0=flat
- Return Series same length as input DataFrame
- Add HMA to `cryptoquant/strategy/signals.py` — formula: WMA(2*WMA(n/2) - WMA(n), sqrt(n))
- Use `self.preprocess(df)` for validation
- min_bars = max(hma_slow, atr_period) + 5 ≈ 55
