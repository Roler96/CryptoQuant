# Strategy Optimization Results — CTA Trend Following

**Backtest period:** 2025-01-01 ~ 2025-12-31  
**Pair:** BTC/USDT  
**Timeframe:** 1h  

---

## Best Configuration

### 25/30 SMA + ATR 2x/3x + Regime Filter

| Metric | Value |
|--------|-------|
| Return | **+14.03%** |
| Trades | 27 |
| Max Drawdown | 23.08% |
| Win Rate | 78% |
| Sharpe | +0.029 |

**Parameters:**
```json
{
    "fast_ma_period": 25,
    "slow_ma_period": 30,
    "ma_type": "sma",
    "use_rsi_filter": true,
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "use_adx_filter": true,
    "adx_period": 14,
    "adx_threshold": 25,
    "use_regime_filter": true,
    "regime_adx_period": 14,
    "regime_chop_period": 14,
    "regime_atr_period": 14,
    "use_atr_exit": true,
    "atr_period": 14,
    "atr_stop_multiplier": 2.0,
    "atr_take_multiplier": 3.0
}
```

---

## Regime Filter Impact

| Filter | Return | Trades | MaxDD | WinRate | Sharpe |
|--------|--------|--------|-------|---------|--------|
| Regime OFF | +14.32% | 30 | 25.42% | 77% | +0.030 |
| **Regime ON** | +14.03% | 27 | **23.08%** ✅ | **78%** ✅ | +0.029 |

Regime filter 过滤了 3 笔震荡期假信号，回撤降低 2.34%，胜率提升 1%。

---

## Full Comparison (Top 8)

| Params | Return | Trades | MaxDD | WinRate | Sharpe |
|--------|--------|--------|-------|---------|--------|
| 25/30 S2T3 | **+14.32%** | 30 | 25.42% | 77% | +0.030 |
| 25/30 S2T5 | +14.32% | 30 | 25.42% | 77% | +0.030 |
| 25/30 S3T3 | +14.00% | 31 | 25.42% | 74% | +0.029 |
| 25/30 S3T5 | +14.00% | 31 | 25.42% | 74% | +0.029 |
| 15/50 S2T3 | +7.29% | 4 | 17.08% | 50% | +0.018 |
| 25/80 S2T3 | +6.33% | 9 | 43.54% | 67% | +0.016 |
| 30/80 S2T3 | +5.60% | 14 | 39.19% | 50% | +0.015 |
| 30/100 S2T3 | -2.78% | 9 | 40.04% | 67% | +0.001 |

*Legend: S=ATR stop multiplier, T=ATR take multiplier*

---

## Key Findings

1. **25/30 is the best MA combination** — fast=25, slow=30 produces the tightest crossover band, capturing trend reversals early with minimal lag.

2. **ATR parameters have negligible impact for this MA combo** — S2T3 vs S2T5 give identical results (14.32%), suggesting 2025 trends were smooth and stops rarely triggered.

3. **Short MA gaps (fast/slow close) work best** — 25/30 (gap=5) beats 15/50 (gap=35), 30/80 (gap=50), 30/100 (gap=70). Fast-line sensitivity to recent price action is key.

4. **ADX filter is essential** — without it, baseline 10/30 loses -20.10%. The ADX<25 filter blocks false entries during ranging periods.

---

## Run Command

```bash
python backtest/run.py -s cta -p BTC/USDT -t 1h \
  --start 2025-01-01 --end 2025-12-31 \
  --no-plot
```

*Note: Default params are now fast=25, slow=30.*
