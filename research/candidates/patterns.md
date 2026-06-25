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

## Parameter Sensitivities
- DonchianEnsemble: `lookbacks` dominated — needs shorter max lookback (168 instead of 720)
- SupertrendRegime: `factor=3.0` too wide — consider 2.0
- VolContractionRSI: `squeeze_pct=10` too strict — only traded 3 times
- RSIBBMeanReversion: `rsi_oversold=30, rsi_overbought=70` standard but useless in trending market
- EMACrossATRFilter: `fast=12, slow=26, atr_period=14, atr_percentile=80` — robust across all combos
