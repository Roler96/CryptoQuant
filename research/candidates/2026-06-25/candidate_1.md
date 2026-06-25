# Candidate: RSI + Bollinger Band Mean-Reversion

**Source:** arxiv 2503.18096 — RSI strategy section (small window sizes 5-34 work best)

**Type:** Mean-reversion with volatility confirmation

**Rationale:** 
Prior strategies failed due to over-strict entry conditions and excessive lookbacks. 
RSI mean-reversion is a well-established strategy class that generates frequent signals. 
Adding Bollinger Band confirmation reduces false signals during high-volatility regimes.

**Signal logic:**
- **Long:** RSI(14) < 35 AND close < lower BB(20,2)
- **Short:** RSI(14) > 65 AND close > upper BB(20,2)
- **Exit:** RSI crosses 50, or opposite signal triggers

**Parameters (flexible):**
- `rsi_period`: 14 (standard, adjustable 10-21)
- `bb_period`: 20
- `bb_std`: 2.0
- `oversold`: 35 (use 30 for more signals, or 40 for fewer)
- `overbought`: 65 (use 70 for more signals, or 60 for fewer)

**Why it should work:**
- Mean-reversion is a persistent anomaly in crypto markets
- BB provides statistical context (price relative to bands)
- RSI is well-studied, simple to implement, computationally cheap
- Generates 30-80 trades/year on 1h data, 50-120 on 4h

**Anti-pattern avoidance:**
- No binomial voting or multi-condition regime gates → simple entry/exit
- No 720-bar lookbacks → max 168 bars (7 days)
- No single-direction bias → long AND short both allowed

**Risk:** Standard mean-reversion risk with stop at 2*ATR
