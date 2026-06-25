# Candidate: CMOTrend

## Source
Tushar Chande, "The New Technical Trader" (1994). Chande Momentum Oscillator (CMO) is an improvement over RSI — it uses sum of up/down moves rather than smoothed average gains/losses, making it faster and more responsive to regime changes.

arXiv 2602.18481 (AlphaForgeBench) lists CMO among the 120+ pre-computed technical indicators used for strategy generation.

## Strategy Logic
**2 entry conditions:**
1. CMO(20) crosses above signal line SMA(CMO, 10) → momentum shift positive
2. Close > EMA(200) → trend filter (only long in uptrend)

**Exit:** CMO crosses below signal line (momentum exhausted)

**Short side:** CMO crosses below signal line AND close < EMA(200)

## Why This Might Work
- CMO formula: CMO = 100 × (sum_up - sum_down) / (sum_up + sum_down). Unlike RSI (which uses Wilder smoothing), CMO uses a raw sum over the lookback period — no smoothing distortion, faster response.
- CMO + SMA signal line creates a MACD-like crossover but with normalized 0-100 scale → works across timeframes without parameter tuning (like %B and Stochastic).
- Normalized oscillator (0-100) → should work on 4h where smoothed crossovers fail (per Loop 9-10 findings).
- 2 conditions only. CMO crossover + trend filter.
- Known from traditional finance literature as superior to RSI for trend following (RSI designed for ranging markets, CMO designed for trending markets).

## Anti-Pattern Check
- NOT mean reversion (trend filter prevents counter-trend entries)
- NOT ≥3 conditions (2 only)
- NOT Ichimoku (no nested AND gates)
- NOT ADX-based (no lag)
- NOT CLV/position-based
- NOT candle pattern
- NOT another RSI variant (CMO is structurally different — sum-based vs average-based)

## Differentiation from Previous Oscillator Strategies
- vs StochRSITrend (Loop 7): CMO is raw momentum, not position-in-range. Less whipsaw.
- vs ChannelBreakoutRSI (Loop 4): CMO crossover is mechanical, not threshold-gated. More signals.
- vs MACD+ADX (Loop 5): CMO is normalized 0-100, works on 4h unlike ADX.
- vs BBPercentBVolatility (Loop 11): Similar normalization advantage, but CMO is a crossover (more signals) vs threshold (fewer signals).

## Parameters
- cmo_period: 20 (standard Chande)
- signal_period: 10 (SMA of CMO)
- trend_period: 200
- min_bars: 200

## Expected Behavior
- CMO is faster than RSI → 100-250 trades/year on 1h
- Normalized scale → 30-60 trades/year on 4h (beats ADX/EMA crossovers which produce 5-15)
- Crossover entry generates more signals than threshold-gated entry (%B at 0.8)
- Risk: CMO can be noisy in ranging/choppy markets → EMA200 filter should mitigate
