# Strategy Candidate: BBPercentBVolatility

**Generated:** 2026-06-25
**Source:** John Bollinger's %B + MFI strategy (StockCharts), VolatilityBox BB squeeze research

## Strategy Concept

Bollinger %B measures price position within Bollinger Bands: %B = (close - lower_band) / (upper_band - lower_band). Values > 1 indicate price above upper band (breakout); values < 0 indicate price below lower band (breakdown). Unlike Loop 4's BBandBreakoutVolume (which used price pierce of band + volume > SMA confirmation), this strategy uses %B threshold crossing + ATR expansion as the confirmation filter. Entry: %B > 0.8 (strong push above upper band area, bullish momentum) AND ATR(14) > ATR(50).rolling_mean() (volatility expansion confirming breakout validity). This is 2 total conditions. Exit: %B crosses below 0.5 (price retreats below band midline). ATR expansion confirmation is proven superior to volume confirmation (Loop 5's meta-analysis: ATR > RSI > Volume for breakout confirmation). The %B approach is more nuanced than raw price pierce — it measures HOW FAR price is through the band, filtering marginal pierces.

## Pseudocode

```
for each bar:
    bb_upper, bb_mid, bb_lower = bollinger_bands(close, period, std_dev)
    percent_b = (close - bb_lower) / (bb_upper - bb_lower)
    atr_expanding = atr(14) > sma(atr(14), 50)
    
    if no_position:
        if percent_b > 0.8 AND atr_expanding:
            enter_long()
        elif percent_b < 0.2 AND atr_expanding:
            enter_short()
    
    if position_open:
        if (is_long AND percent_b < 0.5) OR (is_short AND percent_b > 0.5):
            exit_position()
```

## Expected Indicators

- [x] Bollinger Bands — check if in signals.py; if not, `bb_upper = sma + std*close.rolling.std`, `bb_lower = sma - std*close.rolling.std`
- [x] ATR — already exists in signals.py
- [x] SMA — already exists in signals.py

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| bb_period | 10-30 | 20 | Bollinger Band SMA period |
| bb_std | 1.5-2.5 | 2.0 | Standard deviation multiplier |
| percent_b_entry | 0.7-0.9 | 0.8 | %B threshold for long entry (above = bullish breakout) |
| percent_b_exit | 0.3-0.7 | 0.5 | %B threshold for exit (below midline = momentum fading) |
| atr_period | 10-20 | 14 | ATR period for expansion check |
| atr_ma_period | 30-100 | 50 | SMA period for ATR baseline |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.5 | >1.5 | ATR expansion confirmation is the strongest single filter (Loop 5: RangeExpansionBreakout Sharpe=3.19) |
| MaxDD | <30% | <5% | Volatility expansion filter avoids false breakout entries in low-vol chop |
| Win Rate | >40% | >50% | Breakout strategies with ATR confirmation average 45-55% win rate |
| Trades | >30 | 50-100 | %B threshold filter should produce fewer false entries than raw price pierce but still 50+ trades/year |

## References

- [Percent B Money Flow — StockCharts](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/percent-b-money-flow)
- [Bollinger Bands and Volatility — VolatilityBox](https://volatilitybox.com/research/bollinger-bands-volatility/)
- [Bollinger Bands Strategy Backtest — StratBase](https://stratbase.ai/en/blog/bollinger-bands-strategy-guide)

## Implementation Notes

- BB %B already exists conceptually; implement as `close - bb_lower / (bb_upper - bb_lower)`
- ATR expansion uses rolling mean of ATR values — this is different from ATR percentile (Loop 5 used 80th percentile). Rolling mean is simpler and produces continuous signals.
- Exit at %B = 0.5 (midline) means exiting when momentum fades to neutral, not waiting for full reversal
- Use `DEFAULT_PARAMS` dict, never hardcode
- Signal convention: 1=long, -1=short, 0=flat
- Return Series same length as input DataFrame
- min_bars = max(bb_period, atr_ma_period) + 50 ≈ 100
