# Candidate 2: CandleConvictionBreakout

**Source:** Original (derived from microstructure analysis)
**Date:** 2026-06-25
**Loop:** 8

## Core Idea

Candle body ratio |close-open|/|high-low| measures market conviction. Large bodies with small wicks indicate directional agreement between buyers and sellers. Averaging this ratio over a lookback window and comparing to a threshold captures periods of high-conviction directional movement.

## Strategy Design (2 conditions)

1. **Entry Signal:** Smoothed body ratio > threshold
   - `body_ratio = abs(close - open) / (high - low)`  [capped at 1.0]
   - `avg_body_ratio = SMA(body_ratio, lookback)`
   - Long when `avg_body_ratio > threshold AND close > open` (bullish conviction)
   - Short when `avg_body_ratio > threshold AND close < open` (bearish conviction)
2. **Trend Filter:** close > EMA200 (long) / close < EMA200 (short)

## Rationale

- Crypto markets have 24/7 trading with no defined open/close auctions — but candle body ratio still captures intra-bar conviction
- High body ratio + directional close = genuine momentum, not noise
- Unlike CLV (which failed in Loop 6), body ratio is a pure conviction measure independent of where close sits within the range
- Completely novel — zero overlap with any prior strategy in 7 loops

## Parameters

- `body_lookback`: 14
- `threshold`: 0.55
- `trend_period`: 200
- `min_bars`: 78 (= 63 + 14 + 1)

## Expected Trade Count

~60-180 trades/year on 1h (conviction spikes are common in crypto, EMA filter reduces noise)
