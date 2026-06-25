# Research Patterns & Anti-Patterns

## Successful Patterns

### 2026-06-25: Simple Trend Following + Volatility Filter
**Strategy:** EMACrossATRFilter
**Results:** 4/4 combos passed main gate. Best: BTC 1h Sharpe=3.09, Trades=422.
**Key Ingredients:**
1. Two moving average crossover (fast/slow EMA) — simple, proven
2. ATR expansion filter (current ATR > 80% percentile) — avoids choppy markets
3. Simple entry: just one cross + one volatility condition (vs Donchian's 7-channel voting)
4. Short lookbacks (fast=12, slow=26, atr=14) — enough signal in 365-day window
**Transferable Pattern:** For trend-following strategies, use ≤2 entry conditions with volatility filter.

## Anti-Patterns (avoid these directions)

### 2026-06-25: Pure Mean Reversion Without Trend Filter
**Problem:** RSI + Bollinger Band mean reversion produced negative Sharpe on ALL 4 combos
(Range: -2.90 to -0.26). 2025-2026 is a strong trending year — price keeps breaking
BB upper band and RSI stays overbought in uptrends.
**Root cause:** No trend direction filter. In a bull market, RSI<30 + price<BB lower
means the asset is genuinely weak, not "oversold."
**Lesson:** Mean reversion strategies MUST include a trend filter (e.g. only go long
when price > EMA200, or use ADX to detect ranging markets).

### 2026-06-25: Signal-sparse trend-following strategies
**Problem:** All 3 strategies (DonchianEnsemble, SupertrendRegime, VolContractionRSI)
produced ≤5 trades in a full year of 1h data. Gate requires ≥30 trades.
**Root causes:**
1. Entry conditions too strict (binomial voting with 7 channels, ADX regime gate, BB squeeze + RSI)
2. Once in a losing trade, never re-entered — exit condition too conservative
3. Lookback periods too long (720 bars = 30 days for Donchian) relative to 365-day window
**Lesson:** Relax entry conditions. Target 50-200 trades/year for statistical significance.
Shorten lookbacks for 365-day window (max 168 = 7 days).

### 2026-06-25: OOS Overfitting on ETH 1h
**Problem:** EMACrossATRFilter ETH 1h: IS Sharpe=2.49 → OOS Sharpe=0.06 (97.6% degradation).
Same strategy works perfectly on BTC 1h (Sharpe=3.09, OOS=2.56) and ETH 4h (OOS=2.08).
**Root cause:** ETH 1h microstructure noise + parameter overfit to IS period.
**Lesson:** When strategy degrades on one timeframe/symbol combo but not others,
check for data-specific overfitting rather than abandoning the strategy entirely.

### 2026-06-25 Loop 2: Volume Spike Reversal (Complete Failure)
**Problem:** VolSpikeReversal produced 0-3 trades across ALL 4 combos (BTC 1h/4h, ETH 1h/4h).
**Root cause:** Volume spike detection at 95th percentile threshold is far too strict for crypto.
When trades did fire (3 on BTC 1h), Sharpe was -1.22 — volume spikes signal continuation, not reversal.
**Lesson:** Volume-based reversal strategies need a lower percentile threshold (e.g. 80th) OR a trend
confirmation filter. On 4h timeframes, volume spike patterns are basically nonexistent.

### 2026-06-25 Loop 2: Keltner/ADX on 4h Timeframe (Too Few Trades)
**Problem:** KeltnerBreakoutADX produced only 9-11 trades on 4h (vs 31-34 on 1h). ADX takes longer
to cross threshold on higher timeframes, and Keltner Channel breakouts are rarer.
**Lesson:** Keltner Channel + ADX breakout strategies should use 1h or lower timeframes.
For 4h+, either lower ADX threshold or widen KC multiplier.

### 2026-06-25 Loop 2: OOS Sharpe >> IS Sharpe = Regime Luck
**Problem:** KeltnerBreakoutADX BTC 1h: IS Sharpe=0.04, OOS Sharpe=2.42. The OOS period (last ~4 months)
was exceptionally favorable (strong trend continuation). This is the OPPOSITE of overfitting (IS good,
OOS bad) — it means the recent regime masked strategy weakness.
**Lesson:** When OOS Sharpe is dramatically higher than IS Sharpe, treat it as regime-shift luck, not
skill. Test across multiple disjoint time periods before deploying. IS Sharpe of 0.04 is the real
baseline — expect similar performance in a neutral regime.

## Parameter Sensitivities
- DonchianEnsemble: `lookbacks` dominated — needs shorter max lookback (168 instead of 720)
- SupertrendRegime: `factor=3.0` too wide — consider 2.0
- VolContractionRSI: `squeeze_pct=10` too strict — only traded 3 times
- RSIBBMeanReversion: `rsi_oversold=30, rsi_overbought=70` standard but useless in trending market
- EMACrossATRFilter: `fast=12, slow=26, atr_period=14, atr_percentile=80` — robust across all combos
- KeltnerBreakoutADX: `kc_period=20, kc_multiplier=2.0, adx_period=14, adx_threshold=25` — works on 1h, fails on 4h
- VolSpikeReversal: `vol_percentile=95` — way too strict, 0-3 trades/year. Try 80th percentile.
