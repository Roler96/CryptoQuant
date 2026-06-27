# Candidate 2: PPO Trend (PPOTrend)

**Date:** 2026-06-27
**Source:** Original synthesis — PPO (Percentage Price Oscillator) is the normalized MACD variant, not directly tested in 18 previous loops
**Status:** Proposed

## Strategy Concept

PPO (Percentage Price Oscillator) crossover with EMA200 trend filter. PPO is MACD expressed as a percentage of the slower EMA, making it scale-invariant and comparable across different price levels (BTC vs ETH, different time periods).

## Entry Logic (2 conditions)

1. **PPO crossover:** PPO line crosses above Signal line → long; crosses below → short
2. **Trend filter:** Close > EMA(200) for long; Close < EMA(200) for short

PPO formula:
```
PPO = (EMA(12) - EMA(26)) / EMA(26) × 100
Signal = EMA(PPO, 9)
```

## Exit Logic
- PPO crosses back through Signal line (reverse signal)

## Why This Should Work
- PPO is the percentage-based MACD — normalized, not absolute price-scale dependent
- MACD+ADX (Loop 5) passed 3/4 on 1h but ADX gate on 4h killed signal count. PPO uses EMA trend instead of ADX — eliminates the ADX latency problem
- The normalization (% of slow EMA) makes PPO directly comparable across BTC/ETH — same 0-level crossover works for both
- Not directly tested: MacdAdxTrend used raw MACD + ADX (effectively 3 conditions with ADX gate)
- 2 total AND conditions — conforms to proven template

## Anti-Patterns Avoided
- ✅ 2 conditions (PPO cross + EMA trend), not 3 (unlike MACD+ADX)
- ✅ Percentage-normalized (like %B, Stochastic) — should work on 4h unlike raw MACD
- ✅ No ADX latency on 4h (EMA200 direction changes faster than ADX>25)
- ✅ Not raw price-extreme (safe for ETH potential)
- ✅ Moderate lookback (26-bar slow EMA, not >34 like AO)

## Parameters
```
ppo_fast = 12
ppo_slow = 26
ppo_signal = 9
trend_period = 200
```

## Expected Backtest Combos
- BTC/USDT 1h, BTC/USDT 4h, ETH/USDT 1h, ETH/USDT 4h
- Target: 80-250 trades on 1h, 30-60 on 4h; Sharpe 1.0-2.5
