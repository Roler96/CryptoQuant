# Strategy Candidate: CCI Trend

**Generated:** 2026-06-26
**Source:** GitHub Trending — AlphaForgeBench / je-suis-tm/quant-trading

## Strategy Concept

CCI (Commodity Channel Index) 是归一化动量震荡指标，测量价格偏离统计均值的程度。不同于 RSI 的固定 0-100 范围，CCI 自缩放（以 mean absolute deviation 为单位），天然跨时间段自适应。入场：CCI 穿越 +100（做多）/ -100（做空）。出场：CCI 反向穿越 ±100。加 EMA200 趋势过滤 — 恰好 2 个 AND 条件。CCI 的归一化特性使其类似 Loop 11 的 %B，理论上应能跨 1h/4h 工作。

## Pseudocode

```
# Entry (2 conditions, both must be true):
long_entry  = cci > +100 AND close > ema200
short_entry = cci < -100 AND close < ema200

# Exit (any of):
long_exit  = cci < +100  # CCI falls back below +100
short_exit = cci > -100  # CCI rises back above -100

# Exit priority: stop_loss > take_profit > time_exit > signal_reverse
```

## Expected Indicators

- [x] EMA200 (via `ema()` in signals.py)
- [ ] CCI — needs implementation in signals.py: `cci(df, period=20, constant=0.015)`

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| cci_period | 10-30 | 20 | CCI lookback period |
| cci_entry_long | 50-200 | 100 | CCI threshold for long entry |
| cci_entry_short | -200 to -50 | -100 | CCI threshold for short entry |
| trend_period | 100-300 | 200 | EMA trend filter period |
| trailing_stop_atr | 1.5-3.0 | 2.0 | ATR multiplier for trailing stop |
| atr_period | 10-20 | 14 | ATR period for stop |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.8 | CCI is normalized like %B (which got Sharpe 2.90), but simpler — threshold crossing vs band pierce |
| MaxDD | <40% | <25% | Normalized indicator self-adapts to volatility, reducing large drawdowns |
| Win Rate | >40% | >50% | CCI >100/< -100 filters noise — should have better win rate than raw momentum |
| Trades | 50-200 | 80-150 | Normalized indicator should generate consistent signal density across timeframes |

## References

- [AlphaForgeBench — Benchmarking Trading Strategy Design](https://arxiv.org/html/2602.18481v2)
- [CCI Indicator — TradingView](https://www.tradingview.com/scripts/commoditychannelindex/)
- [je-suis-tm/quant-trading — CCI Strategy](https://github.com/je-suis-tm/quant-trading)

## Implementation Notes

- Use `DEFAULT_PARAMS` dict, never hardcode
- Signal convention: 1=long, -1=short, 0=flat
- Return Series same length as input DataFrame
- Add `cci()` to `cryptoquant/strategy/signals.py`
- Use `self.preprocess(df)` for validation
- CCI formula: CCI = (TP - SMA(TP, N)) / (constant × mean_absolute_deviation(TP, N))
  where TP = (H + L + C) / 3, constant = 0.015 (standard)
- min_bars = max(cci_period, trend_period, atr_period) + 50 ≤ 300
