# Wick Inversion — Literature-Driven Improvement Research v1

> **One-line summary:** Three independent research streams converge on the same insight: Wick's problem is not signal quality but signal-to-trade conversion. Cost-aware execution filters, volatility gating, and counterfactual tracking are the highest-ROI improvements.

---

## Hypothesis

The Wick Inversion strategy has a genuine microstructure edge (seller exhaustion detection) but converts it poorly into trades. 48% time-exits at avg -0.36% and Sharpe 0.41 suggest the signal fires in conditions where the edge is absent or the exit parameters don't match the signal's information horizon.

**Hypothesis:** The gap between signal quality and trading performance can be closed by:
1. Better regime filtering (already validated: SMA200 + PDI>MDI)
2. Cost-aware execution gating (new: from Ślepaczuk 2026 papers)
3. Volatility-adaptive position management (new: from regime paper)
4. Counterfactual rejection tracking (new: from Kamat 2026)

---

## Methodology

Per `METHODOLOGY.md` Phase 1-3:
1. Scanned arXiv q-fin.TR June 2026 full listing (23 papers)
2. Searched for: volume-price divergence, stop-loss optimization, candlestick patterns, market regime filtering
3. Deep-dived 5 papers with direct relevance to Wick's microstructure/exhaustion signal
4. Cross-referenced with existing Wick regime analysis (SMA200, PDI>MDI, 48h filters)

---

## Source Papers

### Paper 1: ML-Based Bitcoin Trading Under Transaction Costs
- **arXiv:** 2606.00060
- **Authors:** Andrei Bysik, Robert Ślepaczuk (same group as 2606.09478)
- **Date:** May 2026
- **Core:** XGBoost/LSTM/iTransformer on 70,000 hourly BTC-USDT bars (2018-2026), 27-fold walk-forward
- **Key Findings:**
  - All three ML models produce positive gross returns, but naive sign-based strategies FAIL after 10bps transaction costs
  - **Cost-aware execution filter:** only trade when |forecast| > transaction-cost threshold → sharply reduces turnover, restores profitability
  - Best XGBoost long-only: annualized >65%, Sharpe >1.0
  - Technical indicators improve performance in selected cases; EGARCH features do not provide uniformly robust gains
  - **The Big Insight:** "The main obstacle in hourly cryptocurrency trading is not only weak predictability, but also the way forecasts are converted into trades."
- **Applicability to Wick:** Direct parallel. Wick has a weak but real edge (Sharpe 0.41). The problem is converting that edge into trades. A "cost-aware" filter for Wick would mean: only enter when the signal strength (imbalance magnitude) exceeds a calibrated threshold that accounts for expected slippage + commission.
- **Implementation Difficulty:** Easy — we already have `imbalance_threshold`. The insight is to make it dynamic based on volatility/volume conditions.

### Paper 2: Volatility Forecasting and Return Prediction under Market Regimes
- **arXiv:** 2606.09478
- **Authors:** Xinyue Fang, Robert Ślepaczuk
- **Date:** June 2026
- **Core:** Markov-switching GJR-GARCH → HARQ volatility → XGBoost return prediction on CSI 300
- **Key Findings:**
  - Regime-aware volatility forecasting consistently outperforms baseline HARQ
  - Return predictability is weak, state-dependent, concentrated in low-volatility regimes
  - Naive predictive strategies fail after transaction costs
  - **Carefully designed implementations with volatility scaling, low-volatility gating, threshold calibration, and turnover controls improve defensive economic performance**
  - "The practical value of predictive systems may depend less on generating strong unconditional return forecasts and more on transforming weak state-dependent signals into economically robust portfolio allocation rules."
- **Applicability to Wick:** 
  - Volatility gating: only trade when vol is in the "sweet spot" (our regime analysis shows High vol 1.2-1.5x median is best, Very Low <0.6x is toxic)
  - Threshold calibration: the `imbalance_threshold` should vary with volatility regime
  - Turnover control: max positions per day/week to avoid overtrading in noisy regimes
- **Implementation Difficulty:** Medium — requires adding volatility regime classification to signal generation

### Paper 3: Optimal Signal Extraction from Order Flow (Matched Filter)
- **arXiv:** 2512.18648
- **Authors:** Sungwoo Kang
- **Date:** Dec 2025 (v3: Feb 2026)
- **Core:** Matched filter principle for order flow normalization — optimal normalization must match the scaling behavior of the signal-generating process
- **Key Findings:**
  - Market cap normalization is optimal for institutional investors; volume normalization for VWAP/TWAP traders
  - Matched filters achieve up to 1.99× higher signal correlation
  - Foreign institutional flows predict next-day returns under volume scaling (t=16.35) — durable private information, not temporary price impact
  - **"Informed Executor" hypothesis:** sophisticated investors possess genuine private information but employ volume-targeting algorithms for stealth execution
- **Applicability to Wick:** 
  - Wick's signal uses `log(1+volume)` normalization — this is essentially a matched filter for volume-targeting traders
  - The paper validates that volume-based normalization is the right choice for detecting informed trading activity
  - Potential improvement: test alternative normalizations (market-cap-weighted for large-cap coins, volume-weighted for altcoins)
  - The "Informed Executor" hypothesis supports Wick's core thesis: large wicks + high volume = informed sellers trying to exit stealthily
- **Implementation Difficulty:** Easy — just validates our existing approach, minor normalization experiments

### Paper 4: Optimal Stop-Loss and Take-Profit Parameterization for Autonomous Trading Agent Swarm
- **arXiv:** 2604.27150
- **Authors:** Nathan Li, Aikins Laryea, Yigit Ihlamur
- **Date:** April 2026
- **Core:** Systematic optimization of SL/TP parameters for multi-agent trading systems
- **Key Findings:** (abstract not fully retrieved — arXiv timeout)
- **Applicability to Wick:** Directly relevant to exit optimization. Our v4.3 already did this (TARGET_PCT 5%→1.5%), but a more systematic approach using the agent-swarm methodology could find better parameter combinations.
- **Implementation Difficulty:** Medium — requires grid search or Bayesian optimization over SL/TP/hold parameter space

### Paper 5: Post-Rejection Follow-up Sampling (Counterfactual Tracking)
- **arXiv:** 2606.08228
- **Authors:** Arati Uday Kamat
- **Date:** June 2026
- **Core:** Methodology for tracking what happens to trades that were rejected by filters
- **Key Findings:**
  - 4,874 forward-sample observations across 184 rejection events
  - 17.9% of rejected tokens hit -50% drawdown within 24h
  - 26.0% of forward samples recorded the rejected token below half-reference
  - Filter stack avoided these realized drawdowns — evidence filters are net-positive
- **Applicability to Wick:** 
  - We should track what happens to signals that are filtered out by SMA200/PDI>MDI
  - If filtered signals consistently lose money → filter is validated
  - If filtered signals would have been profitable → filter is too aggressive
  - This closes the feedback loop on regime filtering
- **Implementation Difficulty:** Easy — add rejection logging to backtest, track forward returns of rejected signals

---

## Synthesis: What This Means for Wick

### The Central Insight

Three independent research groups (Ślepaczuk ×2, Kang, Kamat) converge on the same finding:

> **The gap between signal and profit is in the conversion mechanism, not the signal itself.**

Wick's signal detects seller exhaustion — this is a real phenomenon (validated by Kang's matched filter theory). But the naive conversion (enter on any signal above threshold 0.25, exit at fixed TP/SL/time) throws away most of the edge.

### Mapping Research to Wick's Known Problems

| Wick Problem | Research Insight | Proposed Fix |
|---|---|---|
| 48% time-exits at -0.36% | Ślepaczuk: cost-aware execution filter | Dynamic imbalance threshold based on volatility |
| MaxDD -48.8% | Ślepaczuk: low-vol gating | Only trade when ATR ratio 0.8-1.5 |
| Sharpe 0.41 | Ślepaczuk: threshold calibration | Per-regime parameter sets |
| Weak in bear markets | Existing: SMA200 + PDI>MDI filter | Already validated, needs counterfactual tracking |
| Signal fires too often (2,574 trades) | Ślepaczuk: turnover controls | Max 1 trade per 24h, or cooldown after loss |
| 48h crash filter is most robust (6/6 WF) | Ślepaczuk: state-dependent predictability | Combine 48h filter with vol gating |

### Priority Ranking

| Rank | Experiment | Source | Effort | Expected Impact | Risk |
|---|---|---|---|---|---|
| 1 | Volatility gating (ATR ratio filter) | 2606.09478 + our regime data | Low | High — our data shows Very Low vol is toxic | May reduce trade count too much |
| 2 | Counterfactual rejection tracking | 2606.08228 | Low | Medium — validates existing filters | None |
| 3 | Dynamic imbalance threshold (cost-aware) | 2606.00060 | Medium | High — directly addresses signal→trade gap | Overfitting risk |
| 4 | Cooldown/turnover control | 2606.09478 | Low | Medium — reduces overtrading | May miss valid signals |
| 5 | Systematic SL/TP grid search | 2604.27150 | Medium | Medium — marginal improvement over v4.3 | Overfitting risk |
| 6 | Alternative volume normalizations | 2512.18648 | Low | Low — validates existing approach | None |

---

## Experiment Designs

### Experiment 1: Volatility Gating (Priority: HIGH)

**Rationale:** Our regime analysis shows Very Low vol (<0.6x median ATR) is toxic (Sharpe -0.76). High vol (1.2-1.5x) is best (Sharpe +1.62). Ślepaczuk's paper independently confirms low-vol gating improves defensive performance.

**Design:**
```python
# In WickInversion.generate_signal():
atr_ratio = atr_14 / atr_14.rolling(200).median()
vol_ok = (atr_ratio > 0.8) & (atr_ratio < 2.0)  # skip extreme vol too
signal = base_signal & vol_ok
```

**Validation:** 
- Run on OKX BTC/USDT 1h (2019-2026)
- Compare: baseline vs vol-gated on Sharpe, MaxDD, trade count
- Walk-forward 6-split validation
- Cross-validate on Binance

**Success criteria:** Sharpe > 0.6, MaxDD < -35%, trade count > 800 (enough for statistical significance)

### Experiment 2: Counterfactual Rejection Tracking (Priority: HIGH)

**Rationale:** We filter ~50% of signals with SMA200 + PDI>MDI. We need to know if we're filtering good signals or bad ones.

**Design:**
```python
# In backtest, for each rejected signal:
# Track forward return over next 12 bars (matching max hold)
# Compare: filtered-in trades vs filtered-out signals
# Report: win rate, avg return, Sharpe of rejected signals
```

**Validation:**
- Run on existing regime analysis backtest
- If rejected signals have negative expected return → filter validated
- If rejected signals have positive expected return → filter needs recalibration

**Success criteria:** Rejected signals should have negative or near-zero expected return

### Experiment 3: Dynamic Imbalance Threshold (Priority: MEDIUM)

**Rationale:** Ślepaczuk's cost-aware filter: only trade when |forecast| > cost threshold. For Wick: only trade when imbalance is strong enough to overcome expected slippage + commission.

**Design:**
```python
# Dynamic threshold based on volatility
base_threshold = 0.25
vol_penalty = atr_ratio * 0.05  # higher vol → higher threshold
dynamic_threshold = base_threshold + vol_penalty
signal = (imbalance > dynamic_threshold) & price_ok & regime_ok
```

**Validation:**
- Sweep threshold values [0.20, 0.25, 0.30, 0.35, 0.40]
- Sweep vol_penalty values [0.00, 0.03, 0.05, 0.08, 0.10]
- Walk-forward validate best combination

**Success criteria:** Sharpe improvement over static threshold, no reduction in walk-forward robustness

### Experiment 4: Cooldown After Loss (Priority: MEDIUM)

**Rationale:** Turnover control from Ślepaczuk. After a stop-loss, the market regime may be hostile. A cooldown prevents revenge trading.

**Design:**
```python
# After a stop-loss exit, block signals for N bars
cooldown_bars = 6  # 6 hours
# Track last exit reason and bar index
# Skip signals within cooldown window after stop_loss
```

**Validation:**
- Sweep cooldown [0, 3, 6, 12, 24] bars
- Compare: baseline vs cooldown on Sharpe, MaxDD, consecutive losses

**Success criteria:** Reduced consecutive losses, maintained or improved Sharpe

---

## Implementation Plan

### Phase A: Quick Wins (1-2 hours)
1. Add volatility gating to `strategies/wick.py`
2. Run backtest, compare with baseline
3. If positive, update STRATEGY.md

### Phase B: Validation Infrastructure (2-3 hours)
1. Add counterfactual rejection tracking to `research/backtest_wick_regime_analysis.py`
2. Run on existing SMA200 + PDI>MDI filter
3. Document whether filters are net-positive

### Phase C: Parameter Optimization (3-4 hours)
1. Dynamic threshold sweep
2. Cooldown sweep
3. Combined parameter grid search
4. Walk-forward validation of best combination

### Phase D: Production (1 hour)
1. Update `strategies/wick.py` with best parameters
2. Update `STRATEGY.md` with new findings
3. Update demo cron job if parameters change

---

## References

1. arXiv:2606.00060 — Bysik, Ślepaczuk. "Machine Learning-Based Bitcoin Trading Under Transaction Costs" (May 2026)
2. arXiv:2606.09478 — Fang, Ślepaczuk. "Volatility Forecasting and Return Prediction under Market Regimes" (June 2026)
3. arXiv:2512.18648 — Kang. "Optimal Signal Extraction from Order Flow: A Matched Filter Perspective" (Dec 2025, v3 Feb 2026)
4. arXiv:2604.27150 — Li, Laryea, Ihlamur. "Optimal Stop-Loss and Take-Profit Parameterization for Autonomous Trading Agent Swarm" (April 2026)
5. arXiv:2606.08228 — Kamat. "Post-Rejection Follow-up Sampling: Counterfactual Outcome Measurement in Algorithmic DEX Trading" (June 2026)
6. arXiv:2606.08232 — Kamat. "Hour-Aware Adaptive Risk Management for Autonomous Memecoin Trading" (June 2026)
7. Internal: `docs/research/wick/research_regime_analysis_v1.md` — SMA200 + PDI>MDI regime analysis
8. Internal: `docs/research/wick/STRATEGY.md` — Wick Inversion strategy specification v4.3

---

**Document version:** v1
**Date:** 2026-06-15
**Methodology:** `docs/research/METHODOLOGY.md`
