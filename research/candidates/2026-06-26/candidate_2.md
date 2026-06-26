# Strategy Candidate: UltimateOscillatorTrend

**Generated:** 2026-06-26
**Source:** Web Search — Ultimate Oscillator by Larry Williams (1985), multi-timeframe momentum composite designed to reduce false divergences

## Strategy Concept

Ultimate Oscillator (UO) combines three timeframes (7, 14, 28 periods) with weighted averaging (4× short + 2× medium + 1× long / 7). This multi-timeframe construction was designed specifically to solve the problem of false divergence signals in single-timeframe oscillators (RSI, Stochastic). The strategy enters long when UO crosses above 50 AND close > EMA200 (uptrend filter). Exit on reverse UO cross below 50. Two conditions total. Unlike CMO (sum-based) and Stochastic (smoothed %K/%D), UO's weighted multi-timeframe approach may provide more robust signals on both 1h and 4h.

## Pseudocode

```
uo = ultimate_oscillator(high, low, close, short=7, medium=14, long=28)
trend_filter = close > EMA(close, period=200)

signal = 0
if uo crosses_above 50 and trend_filter:
    signal = 1  # long
elif uo crosses_below 50 and not trend_filter:
    signal = -1  # short
```

## Expected Indicators

- [ ] UO — Ultimate Oscillator (new to signals.py)
- [x] EMA (already in signals.py)

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| uo_short | 5-10 | 7 | Short period (weight 4) |
| uo_medium | 10-20 | 14 | Medium period (weight 2) |
| uo_long | 20-35 | 28 | Long period (weight 1) |
| trend_period | 100-300 | 200 | EMA trend filter period |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.5 | Multi-timeframe weighted = fewer false signals than single-period oscillators |
| MaxDD | <40% | <30% | Trend filter prevents counter-trend entries |
| Win Rate | >40% | >50% | UO at 50 centerline = balanced entry threshold |

## References

- [Ultimate Oscillator — Larry Williams](https://www.investopedia.com/terms/u/ultimateoscillator.asp)
- [Ultimate Oscillator on StockCharts](https://school.stockcharts.com/doku.php?id=technical_indicators:ultimate_oscillator)

## Implementation Notes

- Use `DEFAULT_PARAMS` dict, never hardcode
- Signal convention: 1=long, -1=short, 0=flat
- Return Series same length as input DataFrame
- Add UO to `cryptoquant/strategy/signals.py` — formula: BP = close - min(low, prev_close); TR = max(high, prev_close) - min(low, prev_close); avg7 = sum(BP,7)/sum(TR,7); avg14 = ...; avg28 = ...; UO = 100 * (4*avg7 + 2*avg14 + avg28) / 7
- Use `self.preprocess(df)` for validation
- min_bars = uo_long + 2 ≈ 30
