# Candidate 1: TRIX Trend (trix_trend)

## Source
Sunday free search — TRIX triple-smoothed momentum oscillator, novel direction not tested in previous loops.

## Strategy Concept
**TRIX crossover + EMA200 trend filter (2 conditions)**

TRIX (Triple Exponential Average) is a momentum oscillator that applies triple exponential smoothing to the price series, then computes the rate of change. A signal line (EMA of TRIX) provides crossover signals. The triple smoothing removes high-frequency noise while preserving genuine trend changes — generating cleaner signals than MACD or single-EMA crossovers.

### Entry Logic
- **Long:** TRIX crosses above signal line AND close > EMA200
- **Short:** TRIX crosses below signal line AND close < EMA200

### Exit Logic
- TRIX crosses back through signal line (reverse signal)
- Stop-loss: 2× ATR(14) trailing
- Take-profit: 3× ATR(14)

### Default Parameters
```python
DEFAULT_PARAMS = {
    "trix_period": 15,
    "signal_period": 9,
    "trend_period": 200,
    "atr_period": 14,
    "stop_mult": 2.0,
    "take_profit_mult": 3.0,
}
```

## Why This Should Work
- 2 conditions exactly (fits the proven template — 78% pass rate across 50 combos)
- TRIX crossover is mechanical — rate-of-change of triple-smoothed price crosses its own EMA. Generates clean, infrequent signals
- Triple smoothing removes crypto microstructure noise better than MACD (single EMA) or Stochastic (no smoothing)
- Not acceleration-based (works differently from PSAR/SuperTrend) — may have different 4h behavior than previously tested indicators

## Anti-Pattern Check
- ✅ Not ≥3 AND conditions (exactly 2)
- ✅ Not mean reversion (trend filter + momentum oscillator = trend following)
- ✅ Not CLV-based or candle pattern recognition
- ✅ Not percentile-gated volume filter
- ✅ Not Ichimoku (no disguised AND gates)
- ⚠️ May be signal-sparse on 4h (triple smoothing compounds bar scarcity) — but TRIX period=15 is much shorter than KAMA's adaptive smoothing

## Distinction from Previous Strategies
- Not MACD (single EMA smoothing) — TRIX uses THREE layers of smoothing
- Not KAMA (adaptive smoothing) — TRIX uses fixed exponential smoothing
- Not PSAR/SuperTrend (acceleration-based) — TRIX is rate-of-change based
- Not Stochastic/RSI (%K/%D) — TRIX derives from triple-smoothed price, not price position in range
