# Quantitative Strategy Research Methodology v1

> **Purpose:** Standardized research workflow for discovering, evaluating, and documenting quantitative trading strategies from internet sources. Designed for AI agents to follow consistently.

---

## 1. Research Pipeline Overview

```
Discover → Filter → Deep-Dive → Synthesize → Apply
```

Each phase has specific data sources, tools, and output formats.

---

## 2. Phase 1: Discover (Broad Collection)

### 2.1 Primary Sources (ranked by signal-to-noise ratio)

| Priority | Source | URL | What to Extract |
|----------|--------|-----|-----------------|
| P0 | arXiv q-fin.TR | `arxiv.org/list/q-fin.TR/recent` | Latest trading/microstructure papers |
| P0 | arXiv q-fin.ST | `arxiv.org/list/q-fin.ST/recent` | Statistical finance papers |
| P0 | arXiv q-fin.PM | `arxiv.org/list/q-fin.PM/recent` | Portfolio management papers |
| P1 | arXiv q-fin.CP | `arxiv.org/list/q-fin.CP/recent` | Computational finance papers |
| P1 | QuantInsti Blog | `blog.quantinsti.com/` | Tutorial-style strategy articles, EPAT projects |
| P2 | QuantConnect Forum | `quantconnect.com/forum/` | Community strategy demos, discussions |
| P2 | TradingView Pine Script | `tradingview.com/pine-script-docs/` | Strategy concepts, community scripts |
| P3 | Medium (tag: quantitative-trading) | `medium.com/tag/quantitative-trading` | Practitioner articles (may be blocked by Cloudflare) |
| P3 | Reddit r/algotrading | `reddit.com/r/algotrading/` | Community discussion (may be blocked) |

### 2.2 Search Strategy on arXiv

**Step 1:** Browse recent listings by category (q-fin.TR, q-fin.ST, q-fin.PM)

```
https://arxiv.org/list/q-fin.TR/recent
https://arxiv.org/list/q-fin.ST/recent
https://arxiv.org/list/q-fin.PM/recent
```

**Step 2:** For targeted searches, use the advanced search with category filter:
- Navigate to `arxiv.org/search/advanced`
- Set "Quantitative Finance" as the primary archive
- Use specific sub-categories: q-fin.TR (Trading), q-fin.ST (Statistical), q-fin.PM (Portfolio)

**Step 3:** When using keyword search, always filter by q-fin category to avoid noise from CS/biology papers that mention "trading strategy" in passing.

### 2.3 Search Strategy on QuantInsti

- Browse the blog homepage for recent articles (sorted by date)
- Use the search box with specific strategy names: "statistical arbitrage", "momentum", "mean reversion", "machine learning"
- Focus on EPAT Trading Projects — these are full strategy implementations with backtests
- Key categories to scan: Machine Learning, Mean Reversion & Statistical Arbitrage, Momentum Trading, Options Trading

### 2.4 Browser Tool Usage Notes

- Google and DuckDuckGo often show CAPTCHAs — prefer direct source navigation
- Medium uses Cloudflare anti-bot — skip if blocked, use alternative sources
- Reddit may require JS challenge — skip if blocked
- arXiv and QuantInsti are reliably accessible without CAPTCHAs
- Always use `browser_navigate` with direct URLs rather than search engines when possible

---

## 3. Phase 2: Filter (Relevance Triage)

### 3.1 Filtering Criteria

For each discovered item, evaluate against these criteria:

1. **Actionability:** Can the strategy be implemented with available data (OHLCV, order book)?
2. **Timeframe match:** Does it target our trading timeframe (1h-1d)?
3. **Asset class match:** Crypto? Equities? FX? Cross-asset applicability?
4. **Complexity threshold:** Can we implement it in Python within reasonable effort?
5. **Evidence quality:** Does it have backtest results, out-of-sample validation, or live trading data?

### 3.2 Quick Rejection Rules

- Pure HFT / sub-second strategies → skip (infrastructure mismatch)
- Options-specific strategies → skip unless we trade options
- Requires alternative data (satellite imagery, credit card transactions) → skip
- Purely theoretical with no empirical validation → flag as "reference only"
- NLP/sentiment-only strategies → lower priority unless combined with price signals

---

## 4. Phase 3: Deep-Dive (Detailed Extraction)

### 4.1 For Academic Papers

Extract the following structured information:

```markdown
### Paper: [Title]
- **arXiv ID:** [ID]
- **Authors:** [names]
- **Date:** [submission date]
- **Core Idea:** [1-2 sentence summary]
- **Methodology:** [key techniques used]
- **Key Findings:** [3-5 bullet points of empirical results]
- **Caveats:** [limitations, overfitting risks, data snooping concerns]
- **Applicability to CryptoQuant:** [how this could be adapted]
- **Implementation Difficulty:** [Easy/Medium/Hard]
```

### 4.2 For Blog/Community Posts

```markdown
### Article: [Title]
- **Source:** [URL]
- **Date:** [publication date]
- **Strategy Type:** [momentum/mean-reversion/arbitrage/ML/etc.]
- **Core Logic:** [entry/exit rules in plain language]
- **Performance Claims:** [Sharpe, win rate, drawdown — with skepticism]
- **Red Flags:** [look-ahead bias, survivorship bias, overfitting signs]
```

### 4.3 How to Read arXiv Papers Efficiently

1. Read the abstract first — 80% of papers can be rejected here
2. Check the "Comments" field for page count and figures — short papers (<10 pages) are often more practical
3. Look for "Subjects" cross-listing — papers in q-fin.TR + cs.LG are ML-heavy
4. Check for companion papers (authors often publish methodology + results separately)
5. Look for data/code availability statements (Zenodo DOI, GitHub links)

---

## 5. Phase 4: Synthesize (Cross-Reference & Rank)

### 5.1 Trend Identification

Group findings into themes and identify:

- **Hot trends:** Topics appearing across multiple sources simultaneously
- **Evergreen strategies:** Classic approaches being refined (pairs trading, momentum)
- **Emerging techniques:** Novel methods with limited but promising evidence
- **Dead ends:** Approaches that papers show don't work

### 5.2 Strategy Classification Taxonomy

```
Strategy
├── Trend Following
│   ├── Moving average crosses
│   ├── Breakout (Donchian, Bollinger)
│   └── Time-series momentum
├── Mean Reversion
│   ├── Pairs trading / Statistical arbitrage
│   ├── Bollinger Band reversals
│   └── RSI-based
├── Market Microstructure
│   ├── Order flow imbalance
│   ├── Price impact
│   └── Wick/Shadow analysis ← our current focus
├── Machine Learning
│   ├── Regime detection (HMM, Random Forest)
│   ├── Return prediction (XGBoost, LSTM)
│   └── Reinforcement Learning
├── Sentiment/NLP
│   ├── News-based
│   ├── Social media
│   └── On-chain (crypto-specific)
└── Portfolio Construction
    ├── Risk parity
    ├── Mean-variance optimization
    └── Regime-based allocation
```

### 5.3 Ranking for Implementation Priority

Score each strategy on a 1-5 scale for:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Expected Edge | 30% | Theoretical and empirical support |
| Implementation Ease | 25% | Can we build it with our stack? |
| Data Availability | 20% | Do we have the required data? |
| Diversification | 15% | Does it correlate with existing strategies? |
| Capacity/Robustness | 10% | Will it scale? Survive different regimes? |

---

## 6. Phase 5: Apply (Adapt to Our Context)

### 6.1 Adaptation Framework

For each selected strategy, document:

1. **Original context:** What market, timeframe, assets was it designed for?
2. **Adaptation needed:** What changes for crypto/our timeframe/our data?
3. **Minimum viable test:** Simplest version to validate the core hypothesis
4. **Expected failure modes:** Where is it likely to break?
5. **Synergy with existing:** How does it complement our Wick/Spring strategies?

### 6.2 Documentation Template

Save to `docs/research/<strategy-name>/research_<topic>_v1.md`:

```markdown
# [Strategy Name] — [Topic] v1

> **One-line summary:** [single sentence capturing the key finding]

## Hypothesis
[What we believe and why]

## Source
[Where this idea came from — paper, blog, community]

## Methodology
[Step-by-step research approach]

## Results
[Empirical findings with tables]

## Conclusions
[What we learned, what to do next]

## References
[Links to source materials]
```

### 6.3 Anti-Patterns to Avoid

- **Overfitting to a single paper's results** without cross-validation
- **Implementing complex ML before simple baselines** — always test a naive version first
- **Ignoring transaction costs and slippage** — academic papers often do
- **Cherry-picking favorable time periods** — always walk-forward validate
- **Copying exact parameters** from equity markets to crypto — recalibrate everything

---

## 7. Tools & Commands Reference

### 7.1 Browser Navigation

```
# Navigate to arXiv category listing
browser_navigate("https://arxiv.org/list/q-fin.TR/recent")

# Navigate to specific paper
browser_navigate("https://arxiv.org/abs/XXXX.XXXXX")

# Navigate to QuantInsti blog
browser_navigate("https://blog.quantinsti.com/")

# Search QuantInsti
browser_navigate("https://blog.quantinsti.com/?s=<query>")
```

### 7.2 Page Inspection

```
# Get full page snapshot after navigation
browser_snapshot(full=true)

# Scroll for more content
browser_scroll(direction="down")

# Visual inspection for CAPTCHAs or rendering issues
browser_vision(question="What is blocking the page content?")
```

### 7.3 Data Extraction

```
# Extract structured data from page
browser_console(expression="document.querySelector('...').innerText")

# Get all links on page
browser_console(expression="Array.from(document.querySelectorAll('a')).map(a => ({href: a.href, text: a.textContent.trim()}))")
```

---

## 8. Session Workflow Checklist

When asked to "research the latest quant strategies":

- [ ] Browse arXiv q-fin.TR recent listings
- [ ] Browse arXiv q-fin.ST recent listings
- [ ] Browse arXiv q-fin.PM recent listings
- [ ] Browse QuantInsti blog homepage
- [ ] For each relevant paper: extract abstract, methodology, key findings
- [ ] Classify each finding into strategy taxonomy
- [ ] Score for implementation priority
- [ ] Identify top 3-5 most actionable ideas
- [ ] Cross-reference with existing CryptoQuant strategies
- [ ] Write synthesis report
- [ ] Save methodology improvements to this document

---

## 9. Lessons Learned

### 2026-06-15 Session

1. **Search engines are unreliable** — Google, DuckDuckGo, and Medium all blocked with CAPTCHAs. Direct source navigation (arXiv, QuantInsti) is the only reliable approach.

2. **arXiv category filtering is essential** — searching "trading strategy" across all fields returns 6,000+ results, mostly irrelevant CS/bio papers. Always filter by q-fin sub-categories.

3. **QuantInsti article URLs are not predictable** — individual article slugs don't match titles. Use the blog homepage and category pages for discovery, not direct URL guessing.

4. **The browser tool's snapshot is truncated at ~8000 chars** — for long pages, use `browser_scroll` + repeated `browser_snapshot` to capture full content.

5. **Papers with companion papers are gold** — authors often split methodology and results. The memecoin paper (2606.08232) had two companion papers with complementary insights.

6. **"Comments" field on arXiv is high-signal** — it often contains page counts, figure counts, companion paper links, and data availability statements.
