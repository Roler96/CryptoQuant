# Candidate: DPO Trend (Detrended Price Oscillator)

## Source
QuantConnect strategy library + independent research
Date: 2026-06-27 (Saturday — quant blog rotation)

## Strategy Description
Uses Detrended Price Oscillator (DPO) as primary entry trigger. DPO removes the long-term trend component from price to isolate short-term cycles. Entry on DPO zero-cross with EMA200 trend filter.

## Entry Logic
- **Long:** DPO crosses above 0 AND close > EMA200
- **Short:** DPO crosses below 0 AND close < EMA200

## Exit Logic
- Exit on DPO reverse zero-cross (mirror of entry)

## Conditions
- 2 total AND conditions: DPO zero-cross + EMA200 trend filter
- DPO period = 20 (standard: DPO = close - SMA(close, period/2+1) shifted by period/2)

## Why This Is Promising
1. **Genuinely novel** — not tested in any of 24 previous loops
2. DPO is a cycle-based oscillator, fundamentally different from momentum oscillators (RSI, Stochastic, CCI)
3. The detrending removes the dominant trend, allowing the strategy to capture short-term cycles within the overall trend
4. 2-condition template, avoiding all known anti-patterns
5. DPO at period=20 should generate reasonable signal density (estimated 50-150 trades/year on 1h)

## Anti-Pattern Checks
- ✅ 2 conditions (not ≥3)
- ✅ Not consolidation-detection (no "wait then breakout")
- ✅ Not raw price-extreme on ETH (DPO uses close only)
- ✅ Not triple-smoothed (DPO uses single SMA)
- ✅ Entry is frequent signal generator (oscillator zero-cross), not rare event detector
- ✅ Not candle pattern, CLV, Heikin-Ashi, VWAP, or Ichimoku

## Parameters
```python
DEFAULT_PARAMS = {
    "dpo_period": 20,
    "trend_period": 200,
}
```

## Test Matrix
| Symbol | Timeframe | Expected trades |
|--------|-----------|-----------------|
| BTC/USDT | 1h | 80-150 |
| BTC/USDT | 4h | 30-50 |
| ETH/USDT | 1h | 80-150 |
| ETH/USDT | 4h | 25-40 |

## Notes
- DPO is technically a "centered" oscillator — the shift_back means recent bars have NaN. Implementation should handle NaN gracefully
- DPO zero-cross is equivalent to price crossing SMA — but the detrending interpretation may produce cleaner signals
- Expected Sharpe: 1.0-2.0 on BTC 1h, lower on ETH/4h based on cohort patterns
