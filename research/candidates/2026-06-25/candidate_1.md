# Candidate 1: RiskAdjustedMomentum

**Source:** arXiv:2603.15848 "Algorithmic Trading Strategy Development and Optimisation"
**Date:** 2026-06-25
**Loop:** 8

## Core Idea

Risk-Adjusted Momentum: normalize historical returns by volatility rather than using raw price change. The paper's EDA found that momentum-to-volatility ratio deciles produce the strongest forward 21-day returns — outperforming raw momentum, raw volatility, and simple trend filters.

## Strategy Design (2 conditions)

1. **Entry Signal:** 63-bar return / 20-bar annualized volatility > threshold (suggest 1.0)
   - `momentum = close / close.shift(63) - 1`
   - `vol = std(log_return, 20) * sqrt(365*24)` (annualized)
   - `risk_adj_momentum = momentum / vol`
   - Long when risk_adj_momentum > 1.0, short when < -1.0
2. **Trend Filter:** close > EMA200 (long-only filter)

## Rationale

- Previous loop's "AdaptiveStopMomentum" (raw momentum threshold) failed because it picked up noise. Risk-adjusting the momentum signal should filter out high-volatility noise regimes.
- 2 conditions total — fits the proven template.
- Different from all prior strategies: breakout family, MACD/ADX, Stochastic, Aroon — none use volatility-normalized momentum.

## Parameters

- `momentum_period`: 63
- `vol_period`: 20
- `threshold`: 1.0
- `trend_period`: 200

## Expected Trade Count

~50-150 trades/year on 1h (momentum crossover with volatility normalization should fire on 1-3% of bars)
