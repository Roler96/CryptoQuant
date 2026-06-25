# Candidate: AdaptiveStopMomentum

**Date:** 2026-06-25
**Source:** arxiv:2602.11708 — "Systematic Trend-Following with Adaptive Portfolio Construction" (Nguyen, 2026)
**Status:** candidate

## Core Idea

Simple momentum entry combined with a **dynamic ATR trailing stop** that ratchets up with price and adapts to volatility. The stop widens in high-volatility regimes and tightens in low-volatility — avoiding premature exits while protecting profits.

This is the **signal-generation component** of the AdaptiveTrend framework, simplified to single-asset application.

## Why It's Different From What We've Tried

- **Not signal-sparse:** Entry condition is a simple momentum threshold (e.g., price up 2% over lookback), so it should fire 50-200 trades/year.
- **Not mean reversion:** Pure trend-following — goes WITH the prevailing move.
- **Exit is the innovation:** Dynamic trailing stop (ATR-scaled) vs. fixed SL/TP or signal reverse used in prior strategies.

## Implementation Plan

**Entry (Long):** `(close - close.shift(lookback)) / close.shift(lookback) > entry_threshold` (e.g., 0.02 = 2%)
**Entry (Short):** Same but negative threshold
**Exit:** Trailing stop level = `max(previous_stop, close - alpha * ATR)`. Position exits when `low < stop_level` (longs) or `high > stop_level` (shorts).

### Parameters (initial)
- `momentum_lookback`: 20 bars (~20h on 1h candles)
- `entry_threshold`: 0.02 (2% price change)
- `atr_period`: 14
- `atr_multiplier`: 2.5 (from paper's optimal)
- `min_bars`: 50 (~100 for ATR to warm up + lookback)

### Signal Convention
- `1` = long, `-1` = short, `0` = flat
- When in a position, trailing stop exit takes priority (signal stays in position until stop hit)
- Stop checked against bar low (longs) / bar high (shorts) — no look-ahead

### Expected Trade Count
Target: 50-200 trades/year. Entry threshold of 2% on 1h should fire ~1-3 times/week per asset.

## Risks & Mitigations

- **Whipsaw in sideways markets:** The trailing stop will be tight because ATR contracts. Quick entries/exits with small losses.
- **Gap risk:** Crypto trades 24/7 so gaps are rare on 1h, but possible on higher timeframes around exchange maintenance.
- **Parameter sensitivity:** ATR multiplier has the biggest impact — paper suggests 2.0-3.0 range.

## Test Plan

Test on BTC/USDT and ETH/USDT, 1h and 4h timeframes. 365-day lookback.
Gate thresholds: ≥30 trades, Sharpe >0.5, MaxDD <30%.
