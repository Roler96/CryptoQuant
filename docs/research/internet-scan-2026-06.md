# Internet Strategy Scan — June 2026 v1

> **One-line summary:** 2026 quant landscape dominated by regime-aware ML, Agentic AI for strategy development, and microstructure-based crypto strategies. The frontier is shifting from "better signals" to "better regime filters and risk management."

---

## Hypothesis

The quant strategy landscape evolves rapidly. A systematic scan of academic (arXiv) and practitioner (QuantInsti, QuantConnect) sources in mid-2026 should reveal emerging themes applicable to our crypto trading system.

---

## Methodology

1. Browsed arXiv q-fin.TR, q-fin.ST, q-fin.PM recent listings (June 2026)
2. Extracted abstracts and key findings from relevant papers
3. Browsed QuantInsti blog homepage for 2025-2026 articles
4. Classified findings by strategy type and implementation feasibility
5. Cross-referenced with existing CryptoQuant strategies (Wick Inversion, Spring)

See `METHODOLOGY.md` for the full research workflow.

---

## Results

### Category 1: Regime Detection + ML (HOTTEST TREND)

#### Paper: Volatility Forecasting and Return Prediction under Market Regimes
- **arXiv:** 2606.09478
- **Authors:** Xinyue Fang, Robert Ślepaczuk
- **Date:** June 8, 2026
- **Core:** Markov-switching GJR-GARCH → HARQ volatility → XGBoost return prediction
- **Key Finding:** Naive ML return prediction fails after transaction costs. BUT: adding volatility scaling + low-volatility gating + threshold calibration + turnover controls transforms weak signals into robust defensive performance.
- **The Big Insight:** "The practical value of predictive systems may depend less on generating strong unconditional return forecasts and more on transforming weak state-dependent signals into economically robust portfolio allocation rules."
- **Applicability:** Directly validates our approach — Wick v4.3's TARGET_PCT tuning is exactly this philosophy. Next step: add explicit volatility gating.
- **Implementation Difficulty:** Medium (GARCH + XGBoost are well-supported in Python)

#### Article: Dynamic Capital Allocation using Market Breadth & Random Forest
- **Source:** QuantInsti EPAT Project, Feb 2026
- **Core:** Market breadth indicators + Random Forest for bull/bear/volatility regime classification
- **Key Finding:** Dynamic capital allocation based on detected regime outperforms static allocation
- **Applicability:** Could add a regime layer on top of Wick/Spring to size positions dynamically
- **Implementation Difficulty:** Easy (Random Forest + breadth indicators are straightforward)

---

### Category 2: Autonomous Crypto Trading Agents (EMERGING)

#### Paper: Hour-Aware Adaptive Risk Management for Autonomous Memecoin Trading
- **arXiv:** 2606.08232
- **Authors:** Arati Uday Kamat
- **Date:** June 6, 2026
- **Core:** Multi-layer intelligence framework for Solana DEX memecoin trading
- **Key Findings:**
  - 190 trades, 15 days, +117.7% cumulative, but only 40.5% win rate
  - Hour-of-day effects: directional but not statistically significant at n=190
  - Rejection filter stack avoided 17.9% of tokens that hit -50% drawdown within 24h
  - **CRITICAL:** Removing top 3 trades (1.6% of sample) flips cumulative return unprofitable — structurally fragile
- **Applicability:** The multi-layer filter approach is relevant. The fragility finding is a warning about memecoin strategies.
- **Implementation Difficulty:** Hard (requires DEX integration, real-time memecoin data)

#### Companion Paper: Post-Rejection Follow-up Sampling
- **arXiv:** 2606.08228
- **Core:** Counterfactual methodology — track what happens to rejected trades
- **Key Finding:** 26.0% of rejected tokens fell below half their reference price — rejection criteria are net-positive
- **Applicability:** This counterfactual tracking methodology should be added to our backtest framework. Track not just what we traded, but what we chose NOT to trade.
- **Implementation Difficulty:** Easy (add rejection logging to existing backtest)

---

### Category 3: Market Microstructure (EVERGREEN)

#### Paper: Realtime Price Impact Detection
- **arXiv:** 2606.13419
- **Author:** Ilija I Zovko
- **Date:** June 12, 2026
- **Core:** Real-time detection of price impact from order flow
- **Applicability:** Could enhance our Wick signal by distinguishing "seller exhaustion" from "genuine selling pressure"
- **Implementation Difficulty:** Hard (requires order book data)

#### Paper: Correlation Emergence and the Epps Effect in Two Coupled Limit Order Books
- **arXiv:** 2606.14182
- **Authors:** Chris Angstmann, Tim Gebbie
- **Date:** June 15, 2026
- **Core:** How correlations emerge between two coupled limit order books
- **Applicability:** Theoretical — relevant for cross-exchange arbitrage but not immediately actionable
- **Implementation Difficulty:** Hard

---

### Category 4: Portfolio Construction (EVOLVING)

#### Paper: Heuristic Portfolio Optimization (HPO)
- **arXiv:** 2606.12612
- **Author:** Miquel Noguer i Alonso
- **Date:** June 12, 2026
- **Core:** Mathematical framework for heuristic-based portfolio optimization as alternative to Markowitz
- **Applicability:** Could improve our multi-strategy capital allocation (Wick + Spring + VC15m)
- **Implementation Difficulty:** Medium

#### Paper: Asymmetric Nonlinear Return Extrapolation under Stochastic Volatility
- **arXiv:** 2606.10805
- **Authors:** Dong Yan, Wenrui Ye, Zhiyue Zong, Wenting Chen
- **Date:** June 10, 2026
- **Core:** Behavioral finance (asymmetric extrapolation) + stochastic volatility in portfolio choice
- **Applicability:** Novel factor source — behavioral biases as alpha
- **Implementation Difficulty:** Hard

---

### Category 5: Topological Data Analysis (NOVEL)

#### Paper: Cross-Sectional Topological Anomaly Scores and Intraday Return Predictability
- **arXiv:** 2606.08586
- **Author:** Krzysztof Ozimek
- **Date:** June 9, 2026
- **Core:** BallMapper + decoder-conditional VAE + Function-on-Function regression on S&P 500
- **Key Finding:** Topological anomaly scores predict intraday returns
- **Applicability:** Novel factor source — TDA is underexplored in crypto. Could be a differentiator.
- **Implementation Difficulty:** Hard (requires specialized TDA libraries)

---

### Category 6: Industry Trends (QuantInsti 2026)

#### Agentic AI for Trading
- QuantInsti launched "Agentic AI for Trading" in 2026
- AI AlgoTrader Bootcamp curriculum
- Trend: LLMs assisting strategy development, code generation, backtest analysis
- **Applicability:** We're already doing this with Hermes Agent. The industry is catching up.

#### LLM for Trading Course
- Quantra launched dedicated LLM course
- Focus: NLP signals from earnings calls, news, social media
- **Applicability:** Lower priority for us — we focus on price/microstructure signals

#### Reinforcement Learning in Trading
- Quantra added RL module to advanced curriculum
- Trend: RL moving from research to practitioner education
- **Applicability:** Worth monitoring but not immediate priority

---

## Synthesis: Top 5 Actionable Ideas

| Rank | Idea | Source | Effort | Expected Impact |
|------|------|--------|--------|-----------------|
| 1 | Volatility gating for Wick entries | 2606.09478 | Low | High — skip trades in high-vol regimes |
| 2 | Counterfactual rejection tracking in backtests | 2606.08228 | Low | Medium — measure what we're missing |
| 3 | Regime-based position sizing (RF + breadth) | QuantInsti EPAT | Medium | High — dynamic allocation |
| 4 | XGBoost signal fusion (combine Wick + regime + vol) | 2606.09478 | Medium | Medium — marginal improvement over rules |
| 5 | Topological anomaly scores as new factor | 2606.08586 | High | Unknown — exploratory |

---

## Conclusions

1. **The regime-aware paradigm is dominant.** Almost every high-quality paper in 2026 uses some form of regime detection + conditional strategy execution. Pure unconditional strategies are considered naive.

2. **Risk management > signal quality.** The Chinese equity paper explicitly concludes that weak signals + good allocation rules beat strong signals + naive execution. This validates our approach of spending time on exit optimization (Wick v4.3).

3. **Counterfactual analysis is the new standard.** The memecoin paper's rejection tracking methodology should become part of every backtest framework. Knowing what you didn't trade is as important as knowing what you did.

4. **Crypto-specific research is maturing.** The memecoin paper on arXiv q-fin.TR shows that crypto trading is now a legitimate academic research topic, not just a practitioner niche.

5. **Agentic AI is the industry buzzword of 2026.** QuantInsti's launch of Agentic AI for Trading signals that the industry sees AI-assisted strategy development as the next frontier. We're ahead of the curve with Hermes Agent.

---

## References

- arXiv:2606.09478 — Volatility Forecasting and Return Prediction under Market Regimes
- arXiv:2606.08232 — Hour-Aware Adaptive Risk Management for Autonomous Memecoin Trading
- arXiv:2606.08228 — Post-Rejection Follow-up Sampling (companion to above)
- arXiv:2606.13419 — Realtime Price Impact Detection
- arXiv:2606.14182 — Correlation Emergence and Epps Effect in Coupled LOBs
- arXiv:2606.08586 — Cross-Sectional Topological Anomaly Scores
- arXiv:2606.12612 — Heuristic Portfolio Optimization
- arXiv:2606.10805 — Asymmetric Nonlinear Return Extrapolation
- QuantInsti Blog — Dynamic Capital Allocation using Market Breadth & Random Forest (Feb 2026)
- QuantInsti Blog — Integrating AI and Quantitative Trading (Feb 2026)
- QuantInsti Blog — Statistical Arbitrage Using Cointegrated Stock Pairs (Mar 2026)
