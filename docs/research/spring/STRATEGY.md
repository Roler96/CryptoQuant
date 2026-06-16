# Spring Reversal — Wyckoff Spring Pattern with Regime Filters

> **TL;DR:** The unfiltered Spring signal is broken (Sharpe -0.45, MaxDD -61.8%). With SMA200 + BB %B [0.15, 0.60) filters and optimized exits (s3.0/t2.75/h32), it becomes profitable: 88 trades, Sharpe +0.56 (daily), MaxDD -7.4%, 6/7 walk-forward splits positive on OKX. Low trade count (~12/year) is the main limitation.

---

## 1. Strategy Insight

### Core Hypothesis

The Wyckoff Spring is a failed breakdown pattern: price makes a new low below recent support, but closes bullish with high volume — trapping sellers who shorted the breakdown. This is a reversal signal.

The pattern requires 4 conditions:
1. **New low**: current bar's low < lowest low of previous 20 bars (a breakdown)
2. **Bullish close**: close > open (buyers stepped in and reversed the bar)
3. **Close near high**: close is in the upper 50% of the bar's range
4. **High volume**: volume > 150% of 20-bar average (confirms the trap)

### Why the Baseline Fails

Without filters, the Spring signal is deeply unprofitable (Sharpe -0.45, MaxDD -61.8%). The problem: 71% of signals fire below SMA200 — in downtrends, "breakdowns" are genuine continuations, not traps. The signal is buying into falling knives.

### Why the Filters Work

1. **SMA200 filter** (price > SMA200): Ensures Springs occur in the context of an uptrend. Below SMA200, the signal has negative expectancy (Sharpe +0.04 without SMA200 vs +0.56 with it). **Never disable.**

2. **BB %B [0.15, 0.60) filter**: Restricts entries to the Bollinger Band bounce zone. Springs in this zone are genuine reversals from support. Below 0.15 is crash territory (falling knife). Above 0.60 is too extended from support.

3. **Lower target (2.75% vs 5.0%)**: 100% of time-exits were profitable at some point (mean MFE +2.02%), but the original 5% target was unreachable. Lowering to 2.75% captures the typical Spring bounce — take-profit rate goes from 10.9% to 38.6%.

### Signal Type

Spring Reversal is a **counter-trend reversal signal that only works in uptrends**. It buys pullbacks within a larger uptrend. This makes it complementary to momentum/continuation strategies like BB Upper Breakout.

---

## 2. Signal Calculation

```
For each 1h bar:

1. rolling_low = min(low[-20:]) shifted by 1 (previous 20 bars)
2. new_low = current low < rolling_low              # breakdown

3. bullish_close = close > open                     # buyers stepped in
4. close_near_high = (close - low) / (high - low) > 0.5

5. avg_vol = mean(volume[-20:]) shifted by 1
6. high_volume = current volume > 1.5 × avg_vol    # trap confirmed

Spring signal: new_low AND bullish_close AND close_near_high AND high_volume

Filters applied:
  close > SMA(200)                                  # uptrend context
  BB %B in [0.15, 0.60)                             # bounce zone

Entry: next bar open
Exit priority: stop_loss > take_profit > time_exit > signal_reverse
```

---

## 3. Strategy Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| lookback | 20 | Bars for support level and volume average |
| vol_mult | 1.5 | Volume > 150% of average confirms the trap |
| close_pct | 0.5 | Close must be in upper half of bar range |
| sma200_filter | True | **Essential.** Eliminates 71% of toxic signals |
| bb_filter | True | **Essential.** Restricts to bounce zone |
| bb_low | 0.15 | Lower bound tightened from 0.12 in v1.3.0 |
| bb_high | 0.60 | Upper bound tightened from 0.65 in v1.3.0 |
| stop_pct | 3.0% | Lows-based. Pattern needs room to breathe |
| target_pct | 2.75% | Lowered from 5.0% — captures typical bounce |
| hold_hours | 32 | Extended from 16h — bounce can take 24-32h |
| commission | 5 bps | Round-trip estimate |

**Parameter sensitivity**: The exit parameter landscape is smooth — small changes in stop/target/hold produce small changes in Sharpe. No isolated peaks, suggesting low overfitting risk.

---

## 4. Backtest Results

### Full Backtest (OKX BTC/USDT 1h, 2019-2026)

```
Initial Capital:    10,000 USDT
Commission:         5 bps (round-trip)
Slippage:           5 bps

Total Trades:       88
Compound Return:    +34.7%
Annualized Return:  +4.1%
Sharpe Ratio:       +0.56  (daily, from monthly returns)
Sortino Ratio:      +0.21
Max Drawdown:       -7.4%
Max DD Duration:    516 days
Win Rate:           61.4%
Avg Win:            +1.94%
Avg Loss:           -2.13%
Profit Factor:      1.44
Max Consec Losses:  3
Avg Hold Hours:     22.4h

Exit Breakdown:
  take_profit:   34 (38.6%)  avg=+2.65%  total=+90.1%
  stop_loss:     17 (19.3%)  avg=-3.10%  total=-52.7%
  time_exit:     37 (42.0%)  avg=-0.14%  total= -5.3%

MFE Analysis:
  Mean MFE:   +2.02%
  Median MFE: +1.84%
  Max MFE:    +7.88%

Time-exit profitable at some point: 37/37 (100.0%)
```

### Walk-Forward Validation (OKX, 7 splits)

| Split | Period | Trades | Return | Sharpe | DD |
|-------|--------|--------|--------|--------|-----|
| 1 | 2019-10→2020-08 | 12 | +12.7% | +1.70 | -3.1% ✅ |
| 2 | 2020-08→2021-06 | 6 | -1.7% | -0.30 | -6.1% ❌ |
| 3 | 2021-06→2022-04 | 10 | +3.2% | +0.50 | -6.0% ✅ |
| 4 | 2022-04→2023-02 | 8 | +1.7% | +0.38 | -4.4% ✅ |
| 5 | 2023-02→2023-12 | 13 | +0.4% | +0.10 | -7.0% ✅ |
| 6 | 2023-12→2024-10 | 13 | +6.9% | +0.96 | -4.2% ✅ |
| 7 | 2024-10→2025-08 | 16 | +7.1% | +0.91 | -6.1% ✅ |

**6/7 OOS profitable | Mean OOS Sharpe: +0.61 | Total OOS Return: +30.3%**

### Binance Cross-Validation

| Metric | OKX | Binance |
|--------|-----|---------|
| Trades | 88 | 96 |
| Compound Return | +34.7% | +41.2% |
| Sharpe (daily) | +0.56 | +0.60 |
| Max DD | -7.4% | -10.2% |
| Win Rate | 61.4% | 59.4% |
| Profit Factor | 1.44 | 1.45 |

### Binance Walk-Forward (7 splits)

| Split | Period | Trades | Return | Sharpe | DD |
|-------|--------|--------|--------|--------|-----|
| 1 | 2019-10→2020-08 | 14 | +16.0% | +1.88 | -5.0% ✅ |
| 2 | 2020-08→2021-06 | 15 | +0.7% | +0.14 | -5.4% ✅ |
| 3 | 2021-06→2022-04 | 10 | +3.0% | +0.45 | -6.2% ✅ |
| 4 | 2022-04→2023-02 | 8 | +5.8% | +1.12 | -3.1% ✅ |
| 5 | 2023-02→2023-12 | 11 | -1.1% | -0.13 | -7.5% ❌ |
| 6 | 2023-12→2024-10 | 15 | +10.0% | +1.29 | -5.5% ✅ |
| 7 | 2024-10→2025-08 | 15 | -1.0% | -0.07 | -6.1% ❌ |

**5/7 OOS profitable | Mean OOS Sharpe: +0.67 | Total OOS Return: +33.3%**

### SMA200 Filter: ESSENTIAL

| Metric | With SMA200 | No SMA200 | Delta |
|--------|-------------|-----------|-------|
| Trades | 88 | 272 | +184 |
| Sharpe | +0.56 | +0.04 | -0.51 |
| Compound Return | +34.7% | -3.0% | -37.7% |
| Max DD | -7.4% | -25.5% | +18.1% |
| Win Rate | 61.4% | 54.4% | -7.0% |
| Profit Factor | 1.44 | 1.02 | -0.43 |

Without SMA200, the strategy goes from profitable (Sharpe +0.56) to break-even (Sharpe +0.04). The BB filter alone cannot salvage it.

---

## 5. Comparison: Filtered vs Unfiltered

| Metric | Baseline | Filtered v1.3 | Improvement |
|--------|----------|---------------|-------------|
| Trades | 558 | 88 | -470 |
| Sharpe (daily) | -0.45 | +0.56 | +1.00 |
| Compound Return | -61.2% | +34.7% | +95.9% |
| Max DD | -61.8% | -7.4% | -54.3% |
| Win Rate | 47.0% | 61.4% | +14.4% |
| Profit Factor | 0.88 | 1.44 | +0.56 |

The filters transform a deeply broken strategy into a profitable one. The trade-off is an 84% reduction in trade count — from 558 to 88.

---

## 6. Parameter Evolution

| Version | BB Low | BB High | Trades | Sharpe | MaxDD | WF OKX | WF Binance |
|---------|--------|---------|--------|--------|-------|--------|------------|
| v1.0.0 | 0.20 | 0.60 | 78 | +1.53† | -5.5% | 5/6 | 4/6 |
| v1.1.0 | 0.15 | 0.65 | ~91 | +1.76† | — | 6/7 | — |
| v1.2.0 | 0.12 | 0.65 | ~99 | +1.38† | — | 6/7 | 6/7 |
| **v1.3.0** | **0.15** | **0.60** | **88** | **+0.56** | **-7.4%** | **6/7** | **5/7** |

† v1.0.0–v1.2.0 used custom regime_backtest() with per-trade Sharpe. v1.3.0 uses BacktestEngine with daily Sharpe. Daily Sharpe is the standard metric and is ~2-3× lower than per-trade Sharpe.

---

## 7. Risk & Limitations

### Low Trade Count
88 trades over 7.5 years = ~12 trades/year. Walk-forward splits have as few as 6 trades, making statistical significance questionable.

### Daily Sharpe Below Deployment Threshold
Daily Sharpe +0.56 is below the ≥1.0 deployment threshold. While the per-trade Sharpe (computed in prior research) was +1.53, the daily Sharpe is the standard metric used by the framework.

### Bear Market Vulnerability
Split 2 on OKX (Nov 2020–Jun 2021) is negative. During this period, BTC entered a strong bull run where pullbacks were shallow — the Spring pattern fired on brief dips that didn't develop into full reversals.

### Time-Exit Dominance
42% of trades are still time-exits, though this is improved from 70.5% with the original 3.0% target and 16h hold. 100% of time-exits were profitable at some point — the signal has edge, but timing is imprecise.

### SMA200 Dependency
The strategy is completely dependent on SMA200. Without it, Sharpe drops to +0.04. This means the strategy cannot trade during bear markets (when price is below SMA200), missing potential counter-trend opportunities.

### Multi-Pair Untested
Only validated on BTC/USDT. The signal may not work on altcoins with different volatility profiles.

---

## 8. Code Location

| Component | Path |
|-----------|------|
| Strategy class | `strategies/spring.py` → `SpringReversal` |
| Signal function | `cryptoquant/strategy/signals.py` → `spring_reversal_signal()` |
| Backtest script | `research/backtest_spring_definitive.py` |
| Research docs | `docs/research/spring/` |

### Usage

```python
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.data.store import OHLCVStore
from strategies.spring import SpringReversal

store = OHLCVStore()
df = store.load("okx", "BTC/USDT", "1h")

strategy = SpringReversal()
engine = BacktestEngine(commission=0.0005, slippage=0.0005)

result = engine.run(
    df, strategy, symbol="BTC/USDT",
    stop_loss_pct=strategy.params["stop_pct"],
    take_profit_pct=strategy.params["target_pct"],
    max_hold_bars=strategy.params["hold_hours"],
)
```

---

## 9. Recommendation

### 🔬 MORE RESEARCH NEEDED — Not yet deployable

**What works:**
- SMA200 + BB %B [0.15, 0.60) filters transform a broken strategy into a profitable one
- 6/7 OKX walk-forward splits profitable
- MaxDD reduced from -61.8% to -7.4%
- 100% of time-exits were profitable at some point — signal edge is real
- Binance cross-validation confirms (5/7 WF, Sharpe +0.60)

**What blocks deployment:**
- Daily Sharpe +0.56 below ≥1.0 threshold
- Only ~12 trades/year — too sparse for confident deployment
- Binance WF is 5/7 (weaker than OKX 6/7)
- No multi-pair validation

**Next steps:**
1. **Multi-pair deployment** — Test on ETH/USDT, SOL/USDT to increase trade frequency
2. **4h timeframe** — Fewer but higher-quality signals (already partially explored)
3. **Combine with BB Upper Breakout** — They should be complementary (reversal vs momentum)
4. **Position sizing research** — Kelly criterion or volatility-based sizing

### If Paper Trading Today

```python
params = {
    "stop_pct": 3.0,      # Lows-based
    "target_pct": 2.75,   # Lowered from 5.0%
    "hold_hours": 32,     # Extended from 16h
    "sma200_filter": True,  # NEVER disable
    "bb_filter": True,      # NEVER disable
    "bb_low": 0.15,
    "bb_high": 0.60,
}
```

Expected performance: Daily Sharpe +0.3 to +0.7, MaxDD -5% to -15%, ~10-15 trades/year on BTC.

---

## 10. Reproduction

```bash
cd /home/roler/Code/CryptoQuant
uv run python research/backtest_spring_definitive.py
```

**Data:** OKX + Binance BTC/USDT 1h (2019-2026, ~65k bars each)
**Engine:** BacktestEngine with lows-based stops, compound returns, flat commission
**Commission:** 5 bps (round-trip)
**Slippage:** 5 bps

---

## Document History

- v1.0.0 (2026-06-15): Initial strategy class with SMA200 + BB %B [0.15, 0.60) filters
- v1.1.0 (2026-06-15): Expanded BB filter [0.15, 0.65) + vol-adaptive exits
- v1.2.0 (2026-06-15): BB filter expanded to [0.12, 0.65), exits optimized to s3.0/t2.75/h32
- v1.3.0 (2026-06-15): BB filter tightened to [0.15, 0.60), SMA200 confirmed essential
- v1.4.0 (2026-06-16): **STRATEGY.md written.** Definitive backtest with BacktestEngine for canonical benchmark numbers. Validated SMA200 essentiality, exit optimization sweep, cross-exchange WF.
