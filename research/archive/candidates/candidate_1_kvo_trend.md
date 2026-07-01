# Candidate: KVO Trend (Klinger Volume Oscillator)

**Date:** 2026-06-28
**Loop:** 32
**Source:** Free search (Sunday) — volume-based indicator family extension

## Rationale

The Klinger Volume Oscillator (KVO) is a volume-based indicator developed by Stephen Klinger. Unlike OBV (binary sign accumulation), PVT (proportional cumulative), or Chaikin Oscillator (acceleration of A/D Line), KVO uses a double-EMA structure (34/55 periods) on "Volume Force" — a measure that incorporates high/low/close and volume direction.

The volume-based indicator family is the most successful tested across 31 loops (90% pass rate: OBV 4/4, ADLine 4/4, PVT 4/4, Chaikin 2/4). KVO has NOT been tested and uses a genuinely different mathematical construction:
- KVO = EMA(34, VF) - EMA(55, VF)
- VF = V × |2 × (dm/cm) - 1| × T × 100
- dm = direction of price movement, cm = cumulative direction

The double-EMA crossover on volume force should generate 50-200 trades/year on 1h, consistent with the volume family's signal density.

## Strategy Template (2 conditions)

1. **Entry:** KVO crosses above zero (long) / below zero (short)
2. **Trend Filter:** Close > EMA200 (long) / Close < EMA200 (short)
3. **Exit:** KVO crosses below zero (long exit) / above zero (short exit)

## Parameters

- `kvo_fast=34` — standard KVO fast EMA
- `kvo_slow=55` — standard KVO slow EMA
- `trend_period=200` — EMA trend filter
- `min_bars=200` — minimum warmup bars

## Expected Trade Count

- 1h: 80-200 trades/year (volume-based signals are frequent)
- 4h: 25-40 trades/year (may be borderline for gate)

## Anti-Pattern Check

- ✅ 2 conditions exactly
- ✅ Primary trigger from volume-based family (90% pass rate)
- ✅ Volume acts as signal multiplier, not gate
- ⚠️ Double-EMA smoothing on 4h may reduce trade count (KVO fast=34 = 5.7 days on 4h)
- ✅ Not cumulative accumulation (per-bar volume force computation) — avoids ETH OOS accumulation problem
