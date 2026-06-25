# Candidate: Dual EMA Crossover + ATR Volatility Filter

**Source:** arxiv 2511.00665 — EMA crossover strategy section + volatility filtering lessons from prior failures

**Type:** Trend-following with volatility gate

**Rationale:**
EMA crossover is one of the most studied technical strategies. The arxiv paper benchmarked it against ML models on Bitcoin post-ETF data, finding it generates frequent signals. The key failure mode is whipsaw in high-volatility regimes — adding an ATR-based volatility filter gates entries during extreme volatility, while using shorter EMA windows (8/21 instead of 50/200) ensures adequate trade frequency.

**Signal logic:**
- **Long:** Fast EMA(8) crosses above Slow EMA(21) AND ATR(14) < 2.0 * ATR(50)
- **Short:** Fast EMA(8) crosses below Slow EMA(21) AND ATR(14) < 2.0 * ATR(50)
- **Exit:** Reverse crossover (regardless of volatility filter)
- **Flat:** All other times

**Parameters:**
- `fast_period`: 8 (EMA window, adjustable 6-12)
- `slow_period`: 21 (EMA window, adjustable 18-34)
- `atr_period`: 14
- `atr_long_period`: 50
- `vol_threshold`: 2.0 (ATR(14) must be < 2.0 * ATR(50) to enter)

**Expected characteristics:**
- Generates ~80-150 signals/year on 1h data with relaxed EMA windows
- Volatility filter reduces ~30-40% of entries during turbulent markets
- Can hold positions for hours to days (medium-frequency)
- Both long and short signals → works in bull and bear markets
- Simple, well-understood strategy with minimal parameters

**Why it avoids prior anti-patterns:**
- Entry is a simple crossover check (not binomial voting on 7 channels)
- Fast/Slow windows are 8/21 bars (~8 hours / 21 hours on 1h) — far shorter than 720-bar Donchian
- Volatility filter is a ratio check, not a strict regime classifier
- No ADX or multi-condition regime gate → fewer false negatives

**Risk:** Whipsaw in sideways markets; the vol filter helps but won't eliminate all false signals. Add basic stop-loss at 2*ATR.
