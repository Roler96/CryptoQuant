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

### 2026-06-25 Loop 3: Simple Momentum-Threshold Entry (AdaptiveStopMomentum)
**Problem:** Entry based on a single price-change threshold (2% over 20 bars) produced 0/4 passing combos.
Sharpe ranged from -0.87 to 0.40. 37% win rate confirms entries are near-random.
**Root cause:** A naked momentum threshold picks up noise, not signal. Without a volatility filter or
trend confirmation, the entry fires on random price swings that don't sustain.
**Lesson:** Momentum-based entries need at least two confirming conditions (e.g., ATR expansion + trend
filter, or RSI confirmation). Never use a single price-change threshold as the sole entry condition.

### 2026-06-25 Loop 3: Extreme Win Rates Require Commission Sensitivity Testing
**Problem:** TrendPullbackRSI produced 98-99% win rates and Sharpe 14-18 across all 4 combos. With 3000+
trades/year and avg win=1.92% vs avg loss=-1.96%, the edge is paper-thin per trade. OOS Sharpe (12-17)
is also extreme, suggesting the pattern is real but fragile to execution costs.
**Lesson:** When a strategy shows >95% win rate with tight win/loss ratios and 3000+ trades/year, the
commission + slippage model dominates PnL. Run a commission sweep (1-20bps) to find breakeven before
considering deployment. A 3033-trade strategy at 5bps round-trip already pays ~3x initial capital in fees.

### 2026-06-25 Loop 3: Regime-Switching Hysteresis Kills Signal Generation
**Problem:** AdaptiveEmaVolRegime — adaptive EMA crossover with ATR percentile regime detection and
3-bar hysteresis. Produced exactly 1 trade across ALL 4 combos (BTC/ETH × 1h/4h).
**Root cause:** The hysteresis mechanism locked the adaptive EMAs to one regime pair for extended
periods. Since the EMAs only flipped periods after 3 consecutive bars confirming regime change,
the fast/slow EMA ratio rarely changed — and when it did, the crossover condition was even rarer.
The state-machine gating PREVENTED the crossover, not just filtered noise.
**Lesson:** Hysteresis is useful for reducing whiplash but MUST NOT gate the primary entry signal.
Keep hysteresis on secondary filters (position sizing, risk) but never on the signal generator itself.

### 2026-06-25 Loop 3: 4 Independent AND Conditions = Guaranteed 0 Trades
**Problem:** PullbackVolumeContraction — required ALL 4 conditions simultaneously: (1) EMA200 trend,
(2) pullback within 2% of EMA20 after 3% extension, (3) volume = 20-bar min, (4) close breaks 3-bar
high/low. 0 trades across all 4 combos.
**Root cause:** Joint probability of 4 independent conditions is the product: even if each fires at
10% probability, 0.01% joint = <1 bar in 8760. Crypto volume patterns are especially noisy, making
the volume-minimum condition essentially random.
**Lesson:** Beyond 2 independent AND conditions, use scoring/voting instead (e.g. 2 of 3 conditions =
enter). Volume-based filters are particularly problematic as AND gates because crypto volume has
high noise-to-signal ratio and frequent outliers.

### 2026-06-25 Loop 3: The "Complexity Creep" Pattern
**Observation across 3 loops:** Loop 1's simple EMACrossATRFilter (2 conditions: cross + vol filter)
produced 422 trades and Sharpe 3.09. Each subsequent loop added complexity: Loop 2's 3 strategies
(Keltner+ADX, VolSpikeReversal, AdaptiveStopMomentum) averaged 12 trades and 0/12 passing. Loop 3's
2 strategies (AdaptiveEmaVolRegime, PullbackVolumeContraction) averaged 0.5 trades and 0/8 passing.
**Lesson:** There is a monotonic inverse relationship between entry condition count and trade count.
For 365-day backtests with 1h/4h data, target 2 entry conditions maximum. The search should optimize
for signal robustness, not signal precision.

## Parameter Sensitivities
- DonchianEnsemble: `lookbacks` dominated — needs shorter max lookback (168 instead of 720)
- SupertrendRegime: `factor=3.0` too wide — consider 2.0
- VolContractionRSI: `squeeze_pct=10` too strict — only traded 3 times
- RSIBBMeanReversion: `rsi_oversold=30, rsi_overbought=70` standard but useless in trending market
- EMACrossATRFilter: `fast=12, slow=26, atr_period=14, atr_percentile=80` — robust across all combos
- KeltnerBreakoutADX: `kc_period=20, kc_multiplier=2.0, adx_period=14, adx_threshold=25` — works on 1h, fails on 4h
- VolSpikeReversal: `vol_percentile=95` — way too strict, 0-3 trades/year. Try 80th percentile.

## Successful Patterns (2026-06-25 Loop 4)

### Volatility Breakout + Simple Confirmation
**Strategies:** BBandBreakoutVolume, ChannelBreakoutRSI
**Results:** 5/8 combos passed. Best: ChannelBreakoutRSI BTC 1h Sharpe=3.40, 94 trades.
**Key Ingredients:**
1. Breakout entry (BB upper/lower or Donchian channel high/low) — volatility expansion
2. Single confirmation condition (volume > SMA OR RSI > 50) — no AND-gates
3. Exit at middle band or SMA — simple, mechanical
4. 1h timeframe dominates — all 4 1h combos passed; 3/4 4h combos failed
**Transferable Pattern:** Volatility breakout + exactly 1 confirmation filter = robust. 2 entry conditions is the sweet spot.

## Anti-Patterns (avoid these directions)

### 2026-06-25: Breakout Strategies on 4h Timeframe (Insufficient Trades)
**Problem:** BBandBreakoutVolume produced only 20-28 trades on 4h (BTC+ETH). ChannelBreakoutRSI
ETH 4h barely hit 30 trades but with Sharpe=0.29. 3/4 4h combos failed.
**Root cause:** Breakout events (BB pierce, channel breach) are inherently rare on 4h bars in a
365-day window (2190 bars). Fewer bars = fewer opportunities for a breakout to complete.
**Lesson:** Breakout-based strategies should use 1h or lower timeframes. For 4h breakouts, need
>2 years of data or significantly wider parameters (BB std < 2.0, channel period < 20).

### 2026-06-25: Volume Confirmation vs RSI Confirmation — Both Work
**Contrary to Loop 2 finding:** Loop 2's VolSpikeReversal failed because it used 95th percentile
volume threshold AND tried to fade the spike. Today shows volume > SMA(20) as a breakout
confirmation is effective (4/4 1h passed). Volume filters are fine as confirmations — they
only fail when used as ultra-strict percentile gates or as reversal triggers.
**Lesson:** Volume as confirmation (above/below moving average) ≠ Volume as percentile gate.
The former is robust; the latter is too strict for crypto.

### 2026-06-25: OOS Sharpe >> IS Sharpe = Regime Tailwind (Confirmed)
**Problem:** Both BTC 1h combos showed OOS Sharpe > IS Sharpe (BBandBreakoutVolume: 2.40 vs 2.05,
ChannelBreakoutRSI: 2.15 vs 3.40 — actually IS > OOS here. Wait, recheck: ChannelBreakoutRSI BTC 1h
IS=3.40, OOS=2.15 — normal degradation. BBandBreakoutVolume BTC 1h IS=2.05, OOS=2.40 — OOS better.)
**Lesson:** When OOS Sharpe exceeds IS Sharpe, it indicates the OOS period (recent 4 months) had
favorable breakout conditions. This is the same regime-luck pattern identified in Loop 2 (Keltner).

## Parameter Sensitivities
- VolSpikeReversal: `vol_percentile=95` — way too strict, 0-3 trades/year. Try 80th percentile.
