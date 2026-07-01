# Strategy Candidate: Volatility Contraction RSI Reversal

**Generated:** 2026-06-25
**Source:** Composite quant pattern — Bollinger Band squeeze + RSI reversal (common in momentum-reversal literature)

## Strategy Concept

Combines two well-established signals: (1) Bollinger Band squeeze (volatility contraction) as a setup condition, and (2) RSI reversal as the trigger. When the Bollinger Band width contracts below a percentile threshold (indicating compression before expansion), and RSI moves from oversold toward neutral (for longs) or overbought toward neutral (for shorts), enter the trade.

Long entry: BB width < Nth percentile AND RSI crosses above oversold threshold (e.g., 30).
Short entry: BB width < Nth percentile AND RSI crosses below overbought threshold (e.g., 70).
Exit: RSI crosses back to neutral (50) OR BB width expands beyond exit threshold.

This captures the "compression → expansion" dynamic popularized by Bollinger himself, with RSI providing directional bias.

## Pseudocode

```
bb = bollinger_bands(df, period=bb_period, std=bb_std)
bb_width = bb["width"]
bb_width_percentile = bb_width.rolling(100).apply(lambda x: percentile_rank(x, x[-1]))

# Volatility contraction setup
squeeze = bb_width_percentile < squeeze_threshold

# RSI signals
rsi_val = rsi(df["close"], period=rsi_period)
rsi_oversold_exit = crossover(rsi_val, oversold_threshold)
rsi_overbought_exit = crossunder(rsi_val, overbought_threshold)

# Entry
long_signal = squeeze & rsi_oversold_exit
short_signal = squeeze & rsi_overbought_exit

# Exit
exit_long = rsi_val > exit_threshold  # RSI back to neutral
exit_short = rsi_val < exit_threshold

signal = hold long until exit_long, hold short until exit_short
```

## Expected Indicators

- [x] bollinger_bands() — in signals.py
- [x] rsi() — in signals.py
- [x] crossover() / crossunder() — in signals.py
- [ ] percentile_rank helper — trivial, can be inline

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| bb_period | 10–30 | 20 | Bollinger Band period |
| bb_std | 1.5–3.0 | 2.0 | BB standard deviation multiplier |
| rsi_period | 7–21 | 14 | RSI calculation period |
| oversold_threshold | 20–35 | 30 | RSI oversold entry level |
| overbought_threshold | 65–80 | 70 | RSI overbought entry level |
| exit_threshold | 45–55 | 50 | RSI neutral exit level |
| squeeze_pct | 5–25 | 10 | BB width percentile threshold for squeeze |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h
- min_bars = max(bb_period, squeeze_lookback=100, rsi_period) * 3 = ~300

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.7 | Compression-expansion patterns have strong statistical edge |
| MaxDD | <40% | <30% | RSI + squeeze provides two confirmations |
| Win Rate | >40% | >55% | BB squeeze-RSI combo is higher probability than pure RSI |

## References

- Bollinger, J. (2001). "Bollinger on Bollinger Bands"
- RSI: Wilder, J.W. (1978). "New Concepts in Technical Trading Systems"

## Implementation Notes

- Use `DEFAULT_PARAMS` dict, never hardcode
- Signal convention: 1=long, -1=short, 0=flat
- Return Series same length as input DataFrame
- Squeeze detection: need to compute rolling percentile of BB width over ~100 bars
- Position tracking: once in a trade, hold until exit condition (RSI crosses neutral)
- Both long AND short signals — first strategy to use short side in this batch
- The percentile_rank function can be implemented inline with `.rolling().apply()` using scipy or numpy
- For simplicity, use `bb_width.rolling(lookback).rank(pct=True)` which is available in pandas
