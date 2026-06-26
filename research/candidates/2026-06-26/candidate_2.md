# Strategy Candidate: Elder Ray Trend

**Generated:** 2026-06-26
**Source:** GitHub Trending — Dr. Alexander Elder "Trading for a Living" / stratbase.ai

## Strategy Concept

Elder Ray Index 由 Bull Power (High - EMA13) 和 Bear Power (Low - EMA13) 组成，直接测量多空双方推动价格远离共识值的能力。入场：Bull Power 从负转正（多头掌控）AND 价格 > EMA200（趋势向上）；反之亦然。仅 2 个 AND 条件。不同于 Force Index（volume × price_change），Elder Ray 使用裸价格高/低点 vs EMA，信号频率应高于 Force Index（Loop 10: 79-81 trades）且无需成交量数据。

## Pseudocode

```
# Indicators:
bull_power = high - ema(close, 13)
bear_power = low - ema(close, 13)
trend_ema = ema(close, 200)

# Entry (2 conditions):
long_entry  = (bull_power > 0) AND (bull_power.shift(1) <= 0) AND (close > trend_ema)
short_entry = (bear_power < 0) AND (bear_power.shift(1) >= 0) AND (close < trend_ema)

# Exit:
long_exit  = bull_power < 0  # Bulls lose control
short_exit = bear_power > 0  # Bears lose control

# Exit priority: stop_loss > take_profit > time_exit > signal_reverse
```

## Expected Indicators

- [x] EMA (via `ema()` in signals.py)
- [ ] Elder Ray Bull/Bear Power — needs implementation in signals.py: `elder_ray(df, period=13)`

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| elder_period | 8-21 | 13 | EMA period for Bull/Bear Power baseline |
| trend_period | 100-300 | 200 | EMA trend filter period |
| trailing_stop_atr | 1.5-3.0 | 2.0 | ATR multiplier for trailing stop |
| atr_period | 10-20 | 14 | ATR period for stop |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >1.0 | Similar to Force Index (Sharpe 1.40-2.40) but uses raw price not volume-weighted |
| MaxDD | <40% | <25% | Zero-cross entry on raw price wicks — may be whippy on 1h ETH |
| Win Rate | >40% | >45% | Bull/Bear Power zero-cross is fast — expect moderate win rate compensated by favorable win/loss ratio |
| Trades | 60-250 | 100-180 | Raw price vs EMA generates more signals than smoothed indicators |

## References

- [Elder Ray Guide: Bull & Bear Power Indicator Explained — StratBase.ai](https://stratbase.ai/en/blog/elder-ray-bull-bear-power)
- [Elder-Ray Indicator: Bull Power & Bear Power Strategy — GoCharting](https://gocharting.com/docs/charting/technical-indicator/momentum/elder-ray-indicator)
- [Elder Ray Index Bull and Bear Power Strategy — TrendsAndBreakouts](https://trendsandbreakouts.com/elder-ray-index)

## Implementation Notes

- Use `DEFAULT_PARAMS` dict, never hardcode
- Signal convention: 1=long, -1=short, 0=flat
- Return Series same length as input DataFrame
- Add `elder_ray()` to `cryptoquant/strategy/signals.py` returning DataFrame with [bull_power, bear_power]
- Use `self.preprocess(df)` for validation
- min_bars = max(elder_period, trend_period, atr_period) + 50 ≤ 300
- Bull Power = High - EMA(close, period); Bear Power = Low - EMA(close, period)
- Entry is NOT just Bull Power > 0 — must be a CROSS from negative to positive to avoid being always-in
