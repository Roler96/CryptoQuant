# Candidate 2: EMVTrend

**Date:** 2026-06-27
**Source:** Cumulative/volume-normalized family — suggested in Loop 24 patterns.md
**Anti-pattern check:** PASS — 2 conditions, no retrospective gate, no smoothing >20 bars

## Strategy Concept

**Ease of Movement (EMV) crossover + EMA200 trend filter.**

EMV = (High - Low movement midpoint) / (Volume / (High - Low))
= ((High + Low)/2 - prev_high_low_midpoint) / Box Ratio

Where Box Ratio = Volume / (High - Low)

The EMV measures how much price moved relative to the volume required to move it. High EMV → price moves easily (low friction). Low EMV → price struggles (high friction/chop).

This is fundamentally different from OBV (which accumulates volume direction) and ADLine (which weights by close position). EMV directly measures market friction — a regime-sensitive signal that no previous strategy has tested.

## Entry Conditions (exactly 2)
1. EMV crosses above zero → long entry (price moving up with low friction)
2. Close > EMA200 → trend filter

## Exit
- EMV crosses below zero → exit
- Or trailing stop at 2× ATR(14)

## Why this should work
- Volume-normalized: naturally filters weak/noisy bars without gating
- Zero-cross is mechanical — no percentile, no retrospective minimum
- Unlike OBV/ADLine (cumulative), EMV is instantaneous-per-bar — different signal profile
- Low friction entries in uptrends = high-quality trend following
- 2 condition template, proven formula

## Expected signal density
- 1h: 100-180 trades/year (EMV zero-cross is more frequent than OBV SMA cross)
- 4h: 25-40 trades/year (may be borderline on 4h, need to verify)

## Parameters
- emv_smooth: 5 (short EMA to reduce noise)
- trend_period: 200
- atr_period: 14
- stop_mult: 2.0
- tp_mult: 3.0
