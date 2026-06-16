# Filter Rationale Documentation

> **Purpose:** Explain every filter in `WickInversion` and `SpringReversal` — why it exists, what noise it removes, the empirical evidence, and when (if ever) to turn it off.
>
> **Last updated:** 2026-06-16

---

## WickInversion Filters

### 1. Volatility Gating (ATR ratio > 1.0 median)

**Why it exists**
Research on BTC/USDT 1h (OKX, 2019-2026) shows that WickInversion signals fired in very-low-volatility regimes are toxic. The idea is drawn from microstructure literature (Ślepaczuk 2026, Kang 2025): seller-exhaustion patterns require *sufficient* volatility to be meaningful — a calm market with small wicks produces noise, not signal.

**What it removes**
- Chop and low-volatility grind where wicks are tiny and meaningless
- "Fake" seller pressure in sideways markets
- Signals during holiday/weekend low-liquidity periods

**Backtest evidence**
```
Very Low vol  (<0.6x median ATR):  Sharpe -0.76
Low vol     (0.6-0.8x):           Sharpe +0.37
Normal vol  (0.8-1.2x):           Sharpe +1.44
High vol    (1.2-1.5x):           Sharpe +1.62
Very High   (>1.5x):              Sharpe positive

Filter vol_ratio > 1.0:
  Baseline (no filters):  Sharpe -0.19, Cmpd -50.9%, MaxDD -60.6%, 2574 trades
  Vol gate only:          Sharpe +0.38, Cmpd +55.0%, MaxDD -40.5%, 1318 trades
```

**When to disable**
- Never in standard deployment. The filter is the single most robust improvement (6/6 walk-forward splits profitable, mean OOS Sharpe +0.82).
- *Exception:* If you are explicitly running a "low-vol mean-reversion" sub-strategy, you could relax the threshold to 0.8x, but this is not the default configuration.

---

### 2. SMA200 Trend Filter (price > SMA200)

**Why it exists**
WickInversion is a long-only mean-reversion pattern. In sustained downtrends, every bounce looks like a Spring but is actually a "falling knife." The SMA200 filter removes the toxic zone where 71% of unfiltered signals occur.

**What it removes**
- Entries during macro bear markets
- Counter-trend catches in strong downward momentum
- Signals below the 200-period moving average

**Backtest evidence**
```
Above SMA200:  Sharpe +2.50, PF 1.17
Below SMA200:  Sharpe -1.13, PF 0.89

Filter applied:
  SMA200 only:  Sharpe +0.01, Cmpd -15.8%, MaxDD -51.0%, 1563 trades
  Vol+SMA200:   Sharpe +0.55, Cmpd +77.3%, MaxDD -23.3%, 821 trades
```

**When to disable**
- If you are running a *short-biased* variant of WickInversion (not implemented).
- In strong mean-reversion regimes where you want to catch deep dips; however, walk-forward shows SMA200 alone is only 4/6 profitable, so disabling increases variance.

---

## SpringReversal Filters

### 1. SMA200 Trend Filter (price > SMA200)

**Why it exists**
SpringReversal detects Wyckoff Spring patterns — failed breakdowns below support that trap sellers. In a sustained downtrend, breakdowns are *real*, not traps. The SMA200 filter ensures we only trade Springs in the context of a larger uptrend or neutral regime.

**What it removes**
- Genuine breakdowns during bear markets (not failed ones)
- Springs that occur too early in a downtrend before capitulation
- 71% of unfiltered signals, which are concentrated in the below-SMA200 zone

**Backtest evidence**
```
Above SMA200:  Sharpe +0.15, Cmpd -0.1%, MaxDD -21.1%, 156 trades
Below SMA200:  Sharpe -0.93, Cmpd -46.0%, MaxDD -55.0%, 543 trades

Filter applied:
  Baseline (no filters):    Sharpe -0.71, Cmpd -46.0%, MaxDD -55.0%, 543 trades
  SMA200 only:              Sharpe +0.15, Cmpd  -0.1%, MaxDD -21.1%, 156 trades
  SMA200 + BB 0.2-0.6:      Sharpe +1.53, Cmpd +26.0%, MaxDD  -5.5%,  78 trades
```

**When to disable**
- Never for the long-only default. Unlike WickInversion, SMA200 is *essential* for SpringReversal — without it the strategy is deeply unprofitable.
- *Exception:* If you have a separate regime-detection layer (e.g., HMM) that explicitly identifies "accumulation" phases, you could substitute SMA200 with that model.

---

### 2. BB %B Zone Filter [0.12, 0.65)

**Why it exists**
A genuine Spring happens in the *lower Bollinger Band bounce zone* — price has pushed below support but is not in free-fall. The %B metric (position within the Bollinger Bands) quantifies this. %B < 0.12 means price is extremely compressed (rare but high-quality); %B ≥ 0.65 means price has already bounced too far and the entry is late.

**What it removes**
- Late entries after the Spring has already played out (%B > 0.65)
- Entries in the middle/upper Bollinger zone where the pattern is not a Spring
- "Falling knife" signals that occur below the lower band without reversal confirmation

**Backtest evidence**
```
BB %B zone analysis (with SMA200 already applied):
  [0.12, 0.20):  Sharpe +1.68, 73% WR, 15 trades added in v1.2.0
  [0.20, 0.65):  Sharpe +1.53, PF 1.17, core zone
  %B > 0.5:      Sharpe -1.31, toxic late-entry zone

Filter evolution:
  v1.0.0 [0.20, 0.60):  78 trades, Sharpe +1.53
  v1.1.0 [0.15, 0.65):  91 trades, Sharpe +1.76
  v1.2.0 [0.12, 0.65):  99 trades, Sharpe +1.38
```

**When to disable**
- Never in production. The BB filter is the second-most important filter for SpringReversal.
- *Exception:* If you are running a *breakout* sub-strategy (buying strength, not weakness), you would invert the logic to %B > 0.65 — but that is a different strategy entirely.

---

## Summary Table

| Strategy | Filter | Sharpe Without | Sharpe With | Disable? |
|----------|--------|----------------|-------------|----------|
| WickInversion | Vol gate (>1.0x ATR) | -0.19 | +0.38 | No |
| WickInversion | SMA200 | -0.19 | +0.01 | No (optional) |
| SpringReversal | SMA200 | -0.71 | +0.15 | **Never** |
| SpringReversal | BB %B [0.12, 0.65) | -0.71 | +1.53 | **Never** |

---

## References

- `docs/research/wick/STRATEGY.md` — Full WickInversion research history
- `docs/research/wick/research_vol_gate_target_v1.md` — Volatility gating sweep (336 combos)
- `docs/research/spring/research_bb_filter_expansion_v1.md` — BB lower-bound expansion study
- `docs/research/spring/research_vol_adaptive_exits_v1.md` — Vol-adaptive exit parameters
- `strategies/wick.py` — `WickInversion` implementation
- `strategies/spring.py` — `SpringReversal` implementation
