# PFE Trend — Polarized Fractal Efficiency Crossover + Trend Filter

**Date:** 2026-06-28
**Loop:** 35
**Status:** Candidate

## Strategy Concept

Polarized Fractal Efficiency (PFE) measures how efficiently price moves over N bars using fractal geometry. Unlike Kaufman's Efficiency Ratio (unsigned 0-1), PFE is signed (-100 to +100), making it a natural oscillator for trend-following entry.

**Formula:** PFE = 100 × sqrt((C - C[N])² + N²) / Σ sqrt((C[i] - C[i-1])² + 1) × sign(C - C[N])

- Positive PFE: price moved up efficiently (trend up)
- Negative PFE: price moved down efficiently (trend down)
- Near-zero PFE: choppy/inefficient movement

## Entry Conditions (EXACTLY 2)

1. **PFE zero-cross**: PFE(N) crosses above 0 → long; crosses below 0 → short
2. **EMA200 trend filter**: close > EMA200 for long; close < EMA200 for short

## Exit

- PFE crosses back to zero (reverse direction)
- Stop-loss: 2× ATR(14)
- Take-profit: 3× ATR(14)

## Parameters

| Parameter | Default | Notes |
|-----------|---------|-------|
| `pfe_period` | 10 | Period for PFE calculation. 10 = ~10h on 1h |
| `trend_period` | 200 | EMA trend filter |
| `atr_period` | 14 | ATR for stop/profit |
| `stop_mult` | 2.0 | Stop-loss ATR multiplier |
| `take_profit_mult` | 3.0 | Take-profit ATR multiplier |
| `min_bars` | 200 | Minimum bars for indicator warmup |

## Why This Should Work

1. **Genuinely new indicator family**: PFE uses fractal geometry — not tested in any of 34 prior loops
2. **Signed output = natural oscillator**: Unlike ER (unsigned 0-1, needs threshold), PFE's zero-cross is mechanical and unambiguous
3. **Single smoothing stage**: PFE uses a single rolling window (no EMA chain) — good for both 1h and 4h signal density
4. **2 conditions exactly**: follows the proven template
5. **Not a hidden 3-condition**: No pre-condition, no quality gate, no "wait-then-breakout"

## Known Risks

- PFE may be correlated with ER-based strategies (EfficiencyRatioTrend, which failed 0/4 on OOS). But PFE is signed (+/-), not unsigned threshold-based, so entry mechanics are fundamentally different
- On 4h, PFE(10) = 40h lookback — may reduce trade count vs 1h but should still exceed 30-trade minimum

## Target Combos

- BTC/USDT × 1h (primary)
- BTC/USDT × 4h
- ETH/USDT × 1h
- ETH/USDT × 4h (stress test)
