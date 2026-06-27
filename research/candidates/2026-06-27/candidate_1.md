# Strategy Candidate: TSITrend — True Strength Index + Trend Filter

**Generated:** 2026-06-27
**Source:** Quant Blog (Medium/QuantConnect) — William Blau's True Strength Index

## Strategy Concept

TSI (True Strength Index) uses double-exponential smoothing on price momentum, normalized by double-smoothed absolute momentum. Unlike RSI (Wilder smoothing) or Stochastic (K/D crossover), TSI's formula 100 * EMA(EMA(Δp, short), long) / EMA(EMA(|Δp|, short), long) produces cleaner oscillators with sharper turning points. Long when TSI crosses above zero (momentum turns positive) AND price > EMA200 (uptrend). Short when TSI crosses below zero AND price < EMA200. Exit on reverse TSI zero-cross. 2 entry conditions total — follows the proven template.

## Pseudocode

```
tsi = 100 * EMA(EMA(close - close[1], short_period), long_period) / EMA(EMA(abs(close - close[1]), short_period), long_period)
ema200 = EMA(close, 200)

signal_long  = (tsi crosses above 0) AND (close > ema200)
signal_short = (tsi crosses below 0) AND (close < ema200)
exit_long  = tsi crosses below 0
exit_short = tsi crosses above 0
```

## Expected Indicators

- [x] TSI (True Strength Index) — NEW: add to signals.py
- [x] EMA200 — already in signals.py

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| tsi_short | 5-20 | 13 | Short EMA period for TSI momentum |
| tsi_long | 15-40 | 25 | Long EMA period for TSI normalization |
| trend_period | 100-300 | 200 | EMA trend filter period |
| min_bars | 50-200 | 150 | Minimum bars before signal generation |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.5 | Double-EMA normalization should reduce whipsaw vs single-smoothed oscillators |
| MaxDD | <40% | <30% | EMA200 trend filter anchors entries in trend direction |
| Win Rate | >40% | >50% | Similar to tested oscillator families (Stochastic, RSI, CCI) |

## References

- [Blau, William. "True Strength Index." Stocks & Commodities, 1991.](https://www.investopedia.com/terms/t/tsi.asp)
- [TSI Formula — Technical Analysis Library](https://technical-analysis-library-in-python.readthedocs.io/en/latest/ta.html#ta.momentum.TSIIndicator)

## Implementation Notes

- Use `DEFAULT_PARAMS` dict, never hardcode
- Signal convention: 1=long, -1=short, 0=flat
- Return Series same length as input DataFrame
- Add TSI to `cryptoquant/strategy/signals.py`:
  - `tsi(df['close'], short=13, long=25, signal_period=7)` → DataFrame with 'tsi', 'signal'
  - Zero-cross detection: sign(tsi_t) != sign(tsi_t-1) and tsi_t > 0 → long
- Uses close price only — compatible with ETH (avoids bar-extreme anti-pattern)
- Double smoothing inside indicator formula — only 2 explicit AND conditions on entry
