# Candidate: OBV Trend (On-Balance Volume Momentum)

**Date:** 2026-06-27
**Source:** Medium/FMZQuant - OBV Oscillator Crossover Strategy
**Status:** Candidate - DISCOVER phase

## Core Idea
Use On-Balance Volume (OBV) — a cumulative volume-flow indicator — as the primary entry trigger. OBV adds volume on up days and subtracts on down days. When OBV crosses above its SMA, it signals that volume is confirming price direction. Pair with EMA200 trend filter for 2-condition entry.

## Entry Conditions (2 total)
1. OBV crosses above OBV_SMA(Long) for long / below for short
2. Close > EMA200 (trend filter)

## Exit
- OBV crosses back below OBV_SMA(Short) for exit
- Stop-loss: 2× ATR(14)
- Take-profit: 3× ATR(14)

## Rationale
- OBV is fundamentally different from all previously tested oscillators — it measures cumulative volume flow, not price momentum
- Loops 10, 14 showed volume-weighted indicators (Force Index, MFI) outperform raw price indicators on ETH
- OBV crossover is a 2-condition entry — fits the proven template
- OBV is a cumulative line, not a bounded oscillator — signals are continuous and frequent
- Not tested in any of the 42+ strategies across 18 research loops

## Expected Trade Count
50-150/year (1h), 20-35 (4h) — OBV crossover frequency similar to MACD/EMA crossovers

## Parameters
- obv_sma_long: 20
- obv_sma_short: 5 (exit)
- trend_period: 200
- atr_period: 14
- stop_mult: 2.0
- tp_mult: 3.0
