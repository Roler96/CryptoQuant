# Candidate 2: Inside Bar Breakout (inside_bar_breakout)

**Source:** Price action / market profile theory. Inside bars represent compression/indecision. The breakout direction after compression often defines the next short-term trend. Widely used by discretionary traders but rarely formalized for systematic strategies.

**Date:** 2026-06-25
**Loop:** 6

## Strategy Concept

An inside bar (IB) is a bar completely contained within the previous bar's range:
```
is_inside_bar[i] = (high[i] < high[i-1]) AND (low[i] > low[i-1])
```

When the NEXT bar breaks out of the inside bar's range with decent expansion, it signals the resolution of the compression with directional conviction.

## Entry Conditions (2 conditions)

**Long:**
1. Previous bar was an inside bar: `is_inside_bar[i-1]`
2. Current bar breaks out upward with mild expansion: `high[i] > high[i-1]` AND `range[i] > ATR(14) * 0.8`

**Short:**
1. Previous bar was an inside bar: `is_inside_bar[i-1]`
2. Current bar breaks out downward with mild expansion: `low[i] < low[i-1]` AND `range[i] > ATR(14) * 0.8`

Note: The "inside bar + breakout" is treated as a single compound pattern, effectively 2 main conditions: (1) IB pattern present, (2) range expansion confirmation. The expansion multiplier is mild (0.8× ATR) because IB breakout bars often have average-to-slightly-above-average ranges — the signal is the compression resolution, not the volatility spike.

## Exit

Trailing stop at `2.0 * ATR(14)` from entry price.

## Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| atr_period | 14 | Standard |
| expansion_mult | 0.8 | Mild; IB breakouts are about pattern, not volatility regime |
| trailing_stop_mult | 2.0 | Proven across all successful strategies |
| min_bars | 30 | Short |
| max_inside_bars_lookback | 1 | Only look at immediate previous bar for IB pattern |

## Expected Trade Count

Inside bars occur ~10-15% of bars in crypto. Breakouts with expansion fire on ~30-50% of those.
Expected: ~60-100 trades/year on 1h, ~15-30 trades/year on 4h.

⚠️ 4h risk: May fall below 30-trade gate threshold. Need to watch the backtest results closely on 4h timeframes.

## Why This Should Work

1. **Price action pattern with theoretical basis:** Compression → expansion is a market microstructure phenomenon documented across all asset classes. Inside bars represent temporary equilibrium; breakdown signals new directional conviction.
2. **ATR expansion confirmation:** Even the mild 0.8× filter uses our proven ATR approach — it ensures the breakout has SOME energy behind it, not just a 1-tick breach.
3. **2 conditions only:** IB pattern + mild range filter. No complex gating.
4. **Different from all previous:** No indicators needed (ATR only for confirmation, not as primary signal). Pure price action pattern.

## Anti-Pattern Check

- ❌ Pure mean reversion? No — this is breakout/continuation.
- ❌ Signal-sparse? Possibly on 4h (watch). On 1h should have enough trades.
- ❌ >2 conditions? No.
- ❌ Long lookbacks? No — ATR(14), 1-bar IB lookback.
- ❌ Volume percentile gate? No.
- ❌ Regime switching / hysteresis? No.
- ❌ Momentum-only with no filter? No — requires IB pattern + expansion filter.
