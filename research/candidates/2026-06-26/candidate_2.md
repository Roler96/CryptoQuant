# KeltnerChannelTrend — Keltner Channel Breakout + EMA200 Trend Filter

**Discovered:** 2026-06-26 (Saturday — derived from research frontier analysis)
**Source:** Derived from Loop 2's KeltnerBreakoutADX failure analysis + research frontier meta-patterns
**Loop:** 20

## Core Idea

Keltner Channel (ATR-based envelope around EMA) breakout with EMA200 trend filter. Keltner Channels are mathematically distinct from Bollinger Bands (std-based) and Donchian Channels (fixed-lookback range):

- **Bollinger Bands:** Price ± k × std(price). Volatility measured by standard deviation. Wide in volatile periods.
- **Keltner Channels:** EMA(price) ± k × ATR. Volatility measured by ATR. Tighter in volatile periods (ATR is mean absolute, not squared).
- **Donchian Channels:** Max(high, N) / Min(low, N). Measures range extremes.

The Keltner Channel's ATR-based width means breakouts require genuine directional expansion (not just price noise that inflates std). This produces cleaner signals than BB breakouts while maintaining more trades than Donchian breakouts.

## Why This Differs from KeltnerBreakoutADX (Loop 2)

Loop 2's KeltnerBreakoutADX used 3 conditions:
1. KC breakout (close > KC_upper / close < KC_lower)
2. ADX > 25 (trend strength)
3. (effectively hidden 3rd condition from ADX smoothing lag on 4h)

This version drops ADX entirely — replaced by EMA200 trend direction filter. Result: 2 conditions, and ADX's catastrophic 4h lag problem is eliminated.

## Strategy Design

**Entry Conditions (2 total):**
1. Close > KC_upper → long signal; Close < KC_lower → short signal
2. Close > EMA(200) for long filter; Close < EMA(200) for short filter

**Exit:**
- Close < KC_middle (EMA) for longs; Close > KC_middle for shorts
- Or signal reverse

**Parameters:**
- `kc_period=20` — EMA period for channel center
- `kc_multiplier=2.0` — ATR multiplier for channel width
- `atr_period=14` — ATR lookback (standard)
- `trend_period=200` — EMA trend filter period
- `min_bars=200` — warmup period

**Expected Trade Count:**
- 1h: 50-120 trades (breakout events on 1h are frequent; KC is slightly tighter than BB)
- 4h: 25-40 trades (breakout-based, so 4h viable unlike oscillator strategies)

## Why It Should Work

1. **Breakout-based entry** — the only entry type proven to work on 4h across 19 loops. KC breakout generates more signals than BB breakout because ATR-based bands are tighter (ATR < std in most regimes).

2. **2 conditions exactly** — follows the proven template. No hidden gates.

3. **ATR normalization is faster than std normalization** — ATR responds to volatility changes in ~14 bars vs ~20 bars for std. This means KC bands tighten/widen faster, producing more timely breakout signals.

4. **Cleaner than KeltnerBreakoutADX** — ADX(14) > 25 on 4h means 56 hours of trend must develop before entry. KC breakout + EMA200 has zero additional lag beyond the channel calculation.

## Anti-Pattern Compliance

- ✅ 2 entry conditions (KC breakout + EMA200 trend)
- ✅ Breakout-based — 4h viable
- ✅ No ADX (removes the 4h lag problem from Loop 2)
- ✅ No smoothing beyond kc_period=20 (exactly at the 20-bar threshold — could reduce to 14 for cleaner 2-condition count)
- ✅ No hidden AND gates
- ✅ Not a raw price-extreme indicator on ETH (KC uses ATR-smoothed bands, not bar-specific high/low)
