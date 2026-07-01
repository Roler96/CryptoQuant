# Candidate 2: VWAPTrend — Anchored VWAP Momentum

**Date:** 2026-06-26
**Source:** GitHub trending quant topics + classical market microstructure
**Search day:** Friday (GitHub trending)

## Strategy Overview

VWAP (Volume-Weighted Average Price) is the gold standard for institutional order
execution. In crypto, it's underutilized. We use anchored VWAP from a rolling N-bar
window — price above VWAP = bullish momentum (buyers in control), price below VWAP =
bearish momentum (sellers in control).

VWAP is naturally volume-weighted — it **multiplies** signal strength by volume without
gating entry. This follows the proven Force Index / MFI pattern: volume as signal
multiplier > volume as gate.

## Entry Logic (2 conditions)

1. **VWAP cross:** Close > VWAP(period) — volume-weighted price above average = bullish pressure
2. **Volume confirmation:** Volume > SMA(volume, 20) — confirms the move is on genuine interest, not noise

## Exit Logic

- Close < VWAP(period) — reverse signal

## Why This Should Work

1. **2-condition template** — exactly 2
2. **Volume-weighted** — joins Force Index, MFI as proven volume-multiplier family
3. **ETH-robust** — volume weighting naturally downweights noisy ETH bars (cf. MFI passing ETH OOS)
4. **VWAP is institutional standard** — if it works for market makers, it should work for trend following
5. **Normalized (always anchored)** — VWAP adapts to volatility regimes without parameter switching
6. **Untested in CryptoQuant** — new indicator, new family

## Anti-Patterns Avoided

- ✅ Not ≥3 AND conditions (2)
- ✅ Not percentile volume gate (SMA-based, not percentile)
- ✅ Not raw price extreme
- ✅ Not extreme smoothing (VWAP period ≤ 20)

## Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| vwap_period | 20 | Rolling 20-bar VWAP — anchors to recent session, faster signal than 50+ |
| vol_period | 20 | Standard volume MA period |
| min_bars | 50 | VWAP + vol SMA warmup |

## Expected Trade Count

~80-180 trades/year on 1h. VWAP cross is a frequent event — especially in crypto's
volatile microstructures. The volume filter eliminates ~30-40% of false crosses.
Expected ~80+ trades on 1h BTC, ~60+ on ETH 1h. On 4h, ~20-40 trades (may fall below 
30 — typical oscillator/scarcity pattern).

## Risk Consideration

VWAP is designed for session-based trading (equities). On 24/7 crypto, the "anchoring"
is arbitrary (rolling window). This could introduce regime-dependent performance.
Mitigation: anchored VWAP is a well-studied extension — the rolling window is equivalent
to "lookback-anchored VWAP" used in algorithmic trading.
