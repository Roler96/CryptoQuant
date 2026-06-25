# Strategy Candidate: SuperTrendTrend

**Generated:** 2026-06-25
**Source:** arXiv — 2602.11708 (H6 adaptive trend), BoringEdge SuperTrend backtest 2017-2026

## Strategy Concept

SuperTrend is an acceleration-based indicator (like PSAR) that plots a trailing stop line above/below price using ATR. When price closes above the SuperTrend line, the trend is bullish; below is bearish. PSAR went 4/4 gate pass (Loop 9); SuperTrend is its closest analog but with ATR-based stop distance instead of acceleration factor — potentially more adaptive to crypto's variable volatility. Entry: SuperTrend flips bullish AND close > EMA200 (trend direction filter, 2 total conditions). Exit: SuperTrend flips bearish. The ATR multiplier determines sensitivity — higher multiplier = fewer signals.

## Pseudocode

```
for each bar:
    supertrend = compute_supertrend(high, low, close, atr_period, multiplier)
    trend = close > ema(close, trend_period)
    
    if no_position:
        if supertrend == 1 AND trend == 1:
            enter_long()
        elif supertrend == -1 AND trend == 0:
            enter_short()
    
    if position_open:
        if (is_long AND supertrend == -1) OR (is_short AND supertrend == 1):
            exit_position()
```

## Expected Indicators

- [x] SuperTrend — NOT in signals.py; must add `compute_supertrend()` using ATR
- [x] EMA — already exists in signals.py
- [x] ATR — already exists in signals.py (needed for SuperTrend)

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| atr_period | 7-20 | 10 | ATR period for SuperTrend calculation |
| multiplier | 1.5-3.5 | 2.5 | ATR multiplier — higher = fewer signals, lower = more noise |
| trend_period | 100-300 | 200 | EMA period for trend direction filter |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.5 | >1.5 | PSAR (analog) hit Sharpe 2.76 on BTC 1h; SuperTrend should be similar |
| MaxDD | <30% | <5% | Acceleration-based stops adapt to volatility, limiting drawdowns |
| Win Rate | >40% | >50% | Trend-following with dynamic stops typically 40-50% win rate |

## References

- [Systematic Trend-Following with Adaptive Portfolio Construction (arXiv:2602.11708)](https://arxiv.org/abs/2602.11708)
- [Bitcoin Supertrend Strategy Backtest — Boring Edge](https://boringedge.com/bitcoin-supertrend-strategy-backtest/)
- [Supertrend Indicator Backtested — Quantified Strategies](https://quantifiedstrategies.substack.com/p/supertrend-indicator)

## Implementation Notes

- Must add `compute_supertrend()` to `cryptoquant/strategy/signals.py`
- SuperTrend formula: Upper = hl2 + multiplier*ATR, Lower = hl2 - multiplier*ATR, with trailing logic (upper never decreases, lower never increases within a trend)
- Signal: 1 when close > final_upper_band (bullish flip), -1 when close < final_lower_band (bearish flip)
- Use `DEFAULT_PARAMS` dict, never hardcode
- Signal convention: 1=long, -1=short, 0=flat
- Return Series same length as input DataFrame
