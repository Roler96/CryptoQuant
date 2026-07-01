# ALMA Trend — Arnaud Legoux Moving Average Crossover + Trend Filter

**Date:** 2026-06-28
**Loop:** 35
**Status:** Candidate

## Strategy Concept

The Arnaud Legoux Moving Average (ALMA) uses a Gaussian (normal distribution) weighting function to eliminate lag while maintaining smoothness. Unlike EMAs (which lag ~period/2 bars) or HMAs (WMA-based with sqrt lookback), ALMA applies a Gaussian kernel with adjustable offset — allowing near-zero lag without introducing the whipsaw of standard zero-lag attempts.

**Formula:** ALMA[i] = Σ w[j] × price[i - (period-1) + j] for j in 0..period-1
where w[j] = exp(-((j - m)²) / (2 × σ²)), m = offset × (period-1), σ = period / sigma

Key difference from tested MAs:
- EMA: exponential decay (tested in Loop 1 — EMACrossATRFilter)
- HMA: WMA(2×WMA(n/2) - WMA(n)) (tested in Loop 12 — HMATrend, passed 8/8 main gate)
- KAMA: efficiency-ratio-adaptive (tested in Loop 10 — KamaTrend, 1h only)
- McGinley: self-correcting exponential (tested in Loop 32 — McGinleyDynamicTrend, 8/8 main gate)
- **ALMA: Gaussian-weighted, adjustable offset — NOT YET TESTED**

## Entry Conditions (EXACTLY 2)

1. **ALMA fast/slow crossover**: ALMA(9) crosses above ALMA(30) → long; crosses below → short
2. **EMA200 trend filter**: close > EMA200 for long; close < EMA200 for short

## Exit

- ALMA reverse crossover (ALMA fast crosses back below ALMA slow)
- Stop-loss: 2× ATR(14)
- Take-profit: 3× ATR(14)

## Parameters

| Parameter | Default | Notes |
|-----------|---------|-------|
| `alma_fast` | 9 | Fast ALMA period |
| `alma_slow` | 30 | Slow ALMA period |
| `alma_offset` | 0.85 | Gaussian offset (0=full lag, 1=zero lag but noisy) |
| `alma_sigma` | 6.0 | Gaussian width (higher = smoother, lower = more responsive) |
| `trend_period` | 200 | EMA trend filter |
| `atr_period` | 14 | ATR for stop/profit |
| `stop_mult` | 2.0 | Stop-loss ATR multiplier |
| `take_profit_mult` | 3.0 | Take-profit ATR multiplier |
| `min_bars` | 200 | Minimum bars for indicator warmup |

## Why This Should Work

1. **Genuinely new MA type**: Gaussian-weighted with adjustable offset — different smoothing architecture from EMAs, HMAs, KAMAs, and McGinley Dynamic tested in prior loops
2. **Proven 2-condition crossover template**: MA crossover + trend filter is the single most validated template (EMACrossATRFilter 4/4, HMATrend 8/8 main gate, McGinleyDynamic 8/8 main gate)
3. **Near-zero lag**: offset=0.85 puts 85% of Gaussian mass near current bar — faster than EMA, competitive with HMA
4. **Single smoothing stage**: The ALMA itself uses a fixed window (not infinite impulse response like EMA) — the crossover is between two ALMAs, each with a single smoothing
5. **Adjustable smoothness**: sigma=6 provides robust smoothing without the over-smoothing problem of triple-smoothed indicators (TRIX)

## Known Risks

- ALMA crossover frequency on 4h may be borderline (similar to HMA 4h which has ~30 trades)
- ETH OOS may still be hostile (same as all trend-following strategies)
- offset=0.85 is aggressive — may introduce some whipsaw on 1h that standard EMAs avoid

## Target Combos

- BTC/USDT × 1h (primary)
- BTC/USDT × 4h
- ETH/USDT × 1h
- ETH/USDT × 4h (stress test)

## Comparison with Prior MA Strategies

| Strategy | MA Type | Loop | Main Gate | 4h Trades | Notes |
|----------|---------|------|-----------|-----------|-------|
| EMACrossATRFilter | EMA | 1 | 4/4 | ~50 | ATR expansion filter |
| HMATrend | HMA | 12 | 8/8 | ~45 | WMA-based, OOS fail on 4h |
| KamaTrend | KAMA | 10 | 2/4 | 12 | Adaptive, 4h failure |
| McGinleyDynamic | MD | 32 | 8/8 | ~35 | Self-correcting exponential |
| **ALMATrend** | **ALMA** | **35** | **TBD** | **TBD** | **Gaussian-weighted, zero-lag** |
