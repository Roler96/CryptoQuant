# Candidate: KST Trend (Know Sure Thing Multi-Timeframe Momentum)

**Date:** 2026-06-27
**Source:** Original research — KST is a well-known but underexplored indicator in crypto backtesting
**Status:** Candidate - DISCOVER phase

## Core Idea
KST (Know Sure Thing) by Martin Pring combines 4 different ROC (Rate of Change) periods into a single momentum oscillator. Unlike UO (Ultimate Oscillator, Loop 12) which weights 7/14/28 periods with 4:2:1, KST uses ROC(10,15,20,30) with weighted SMA smoothing. This captures multi-timeframe momentum more effectively than single-period oscillators.

## Entry Conditions (2 total)
1. KST crosses above signal line (9-bar SMA of KST) for long / below for short
2. Close > EMA200 (trend filter)

## Exit
- KST crosses back below signal line
- Stop-loss: 2× ATR(14)
- Take-profit: 3× ATR(14)

## Rationale
- KST combines 4 ROC periods → better noise reduction than single-period oscillators without extra smoothing gates
- Different from UO (Loop 12): UO uses 7/14/28 with 4:2:1 weighting; KST uses 10/15/20/30 with equal ROC weighting
- Loop 12 showed multi-timeframe composites (UO) achieved 4/4 main gate pass — KST should have similar robustness
- 2-condition template: KST cross + EMA200
- Not tested in any of the 42+ strategies across 18 research loops

## Expected Trade Count
80-200/year (1h), 20-40 (4h) — KST crossover frequency similar to Stochastic/CCI

## Parameters
- roc_periods: [10, 15, 20, 30]
- sma_periods: [10, 10, 10, 15] (smoothing per ROC)
- signal_period: 9
- trend_period: 200
- atr_period: 14
- stop_mult: 2.0
- tp_mult: 3.0
