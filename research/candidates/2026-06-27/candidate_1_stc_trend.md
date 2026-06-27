# Candidate: STC Trend (Schaff Trend Cycle)

**Date:** 2026-06-27
**Loop:** 27
**Source:** QuantifiedStrategies.com / Investopedia (STC indicator research)

## Strategy Overview

Schaff Trend Cycle (STC) + EMA200 trend filter — a 2-condition composite oscillator strategy.

STC combines MACD and Stochastic into a single 0-100 oscillator with faster turning points than either individually. It applies Stochastic %K formula to the MACD line, producing a double-smoothed but accelerated signal.

## Entry Logic (2 conditions)

1. **STC crossover**: STC(23,50,10) crosses above 25 → long entry signal; crosses below 75 → short entry signal
2. **EMA200 trend filter**: Only enter long when close > EMA200; only short when close < EMA200

## Exit Logic

- Exit when STC crosses below 25 (from long) or above 75 (from short)
- Stop loss: 2× ATR(14)
- Take profit: 3× ATR(14) (optional)

## Why This Might Work

1. **Composite oscillator**: Like Connors RSI (best ETH OOS performer, Loop 21), STC combines multiple dimensions into a single 0-100 reading — neutralizing noise through aggregation rather than smoothing
2. **Faster than MACD**: The Stochastic wrapping on MACD accelerates turning points — should generate more signals on 4h where MACD-family strategies typically fail trade count
3. **2 conditions only**: Crosses above threshold (1) + trend direction (2) — exactly the proven template
4. **Normalized 0-100 scale**: Self-adapting across volatility regimes, should work on both 1h and 4h

## Expected Trade Count

- BTC 1h: 150-250 trades
- BTC 4h: 35-55 trades
- ETH 1h: 120-200 trades  
- ETH 4h: 30-45 trades

## Risks

- Double-smoothing (STC = Stochastic(MACD)) could amplify ETH noise (cf. TRIX failure, Loop 22)
- STC's MACD component (23,50) has 23/50 bar lookback — borderline for 4h trade scarcity
- Not previously tested on crypto sub-daily data

## Parameters

```python
DEFAULT_PARAMS = {
    "stc_ma_fast": 23,      # MACD fast period
    "stc_ma_slow": 50,      # MACD slow period
    "stc_cycle": 10,        # Stochastic %K period
    "stc_threshold_long": 25,   # Entry above 25
    "stc_threshold_short": 75,  # Entry below 75
    "trend_period": 200,    # EMA trend filter
    "atr_period": 14,       # Stop loss ATR
    "stop_mult": 2.0,       # Stop loss multiplier
    "tp_mult": 3.0,         # Take profit multiplier
    "min_bars": 200,        # Minimum bars for warmup
}
```

## Anti-Pattern Check

- ✅ 2 AND conditions (STC threshold + EMA trend)
- ✅ No consolidation detection
- ✅ No candle pattern recognition
- ✅ No CLV/position-gating
- ⚠️ Double-smoothing (STC = Stochastic of MACD) — monitor ETH 1h closely
- ✅ Normalized 0-100 scale — should work on 4h
- ⚠️ 50-bar slow period may cause 4h trade scarcity
