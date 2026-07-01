# Candidate: Money Flow Index Trend (MFITrend)

**Date:** 2026-06-26
**Source:** Research synthesis — MFI indicator by Gene Quong & Avrum Soudack (1989), adapted for crypto
**Loop:** 10

## Concept

Money Flow Index (MFI) is a volume-weighted RSI — it incorporates both price change direction AND volume magnitude into a normalized 0-100 oscillator. Unlike raw RSI (price-only), MFI gives more weight to high-volume price moves.

Entry: MFI(14) crosses above 50 (bullish) or below 50 (bearish)
Filter: EMA200 trend direction (price > EMA200 = long only)
2 conditions total.

## Rationale

1. Normalized 0-100 scale — proven universal across all timeframes (Loop 11 BB %B lesson)
2. Volume is a signal-weight multiplier in MFI's internal formula (not an AND gate) — preserves trade count
3. Crosses 50 is a midline threshold, not a smoothed crossover — better for 4h than Stochastic %K/%D cross
4. Combines two proven patterns: RSI confirmation (Loop 4) + volume weighting (Loop 10 Force Index)
5. 14-period lookback is at the boundary of safe smoothing (floor(14/20)=0 effective hidden conditions)

## Anti-Pattern Checks

- ✅ 2 conditions (not ≥3)
- ✅ No Ichimoku disguised gates
- ✅ Not candle pattern-based
- ✅ Raw price-extreme only in MFI's internal RSI calculation (uses close, not high/low)
- ✅ Volume is multiplier, not gate (MFI internally weights by volume, no external volume filter)
- ✅ Midline threshold entry (50 is the natural center)
- ⚠️ MFI is an oscillator — 4h will still be sparse compared to 1h (all oscillators suffer this)
- ⚠️ 14-period = safe smoothing. Fast enough for 1h signal generation

## Expected Performance

- 1h: Should generate 80-200 trades (comparable to Stochastic at 198 trades, but with volume weighting)
- 4h: Expect 20-40 trades (oscillator on 4h is inherently sparse — Loop 12 CMO lesson)
- ETH risk: Moderate. MFI is close-based (not high/low based) so ETH liquidity fragmentation shouldn't directly impact. But all ETH strategies face OOS degradation risk.
- BTC: Should be the strongest performer (like all volume-weighted indicators)

## Parameters

```python
DEFAULT_PARAMS = {
    "mfi_period": 14,
    "trend_period": 200,
}
```
