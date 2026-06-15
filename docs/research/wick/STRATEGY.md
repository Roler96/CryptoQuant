# The Wick Inversion Strategy

> *"Buy when sellers try hard and fail."*

---

## 1. 策略洞察

### 核心假设（反直觉）

传统交易智慧认为：成交量放大 + 上影线长 = 卖方压力大 = 看跌。

**数据说的恰恰相反。**

当卖方在K线上留下了大量"努力的证据"——长上影线、高成交量——但价格实际跌幅有限时，说明卖方**正在输掉这场战斗**。市场在吸收卖压。一旦吸收完成，价格反弹。

这不是均线交叉。这不是MACD金叉。这不是任何一个技术分析教材里能找到的信号。

这是一个**微观结构信号**：它衡量的是买卖双方在K线内部的博弈强度，而不是价格的方向。

### 为什么有效

1. **影线是"努力的痕迹"**：上影线 = 卖方曾经把价格推高到这个位置，但被买方打了回来。影线越长，卖方消耗的弹药越多。
2. **成交量是"弹药的量"**：同样的影线长度，成交量越大，消耗越大。
3. **价格不崩是"买方在赢"**：如果卖方消耗了大量弹药但价格没跌多少，说明买方的承接力很强。
4. **反弹通常+1~3%**：卖方衰竭后的反弹幅度是有限的——这就是为什么+5%的止盈目标太高。v4.3把止盈从+5%降到+1.5%，Sharpe翻倍，DD减半。

### 为什么叫 "Wick Inversion"

因为它**反转了影线的含义**。常规解读：上影线 = 卖方在掌控。本策略：上影线 = 卖方在消耗。常规解读是方向信号，本策略把它当成衰竭信号。

---

## 2. 信号计算

### 步骤

```
对每一根1小时K线：

1. bar_range = max(high - low, 1e-8)
2. upper_wick = (high - max(open, close)) / bar_range     # 上影线占比
3. lower_wick = (min(open, close) - low) / bar_range      # 下影线占比
4. bear_pressure = upper_wick x log(1 + volume)            # 卖方压力
5. bull_pressure = lower_wick x log(1 + volume)            # 买方压力

6. 对 bear_pressure 和 bull_pressure 分别做6小时滚动求和
7. imbalance = (bear_roll - bull_roll) / (bear_roll + bull_roll)
   # 范围 -1(买方主导) 到 +1(卖方主导)

8. price_6h = 过去6小时价格变化百分比

信号触发条件：
  imbalance > 0.25  AND  price_6h > -0.5%
  ─────────────────    ──────────────────
  卖方在努力             但不是自由落体
```

### 为什么用 log(1+volume)

成交量是指数分布的——BTC的1h成交量从几十到几万BTC不等。直接用原始成交量会让极端值的权重过大。log压缩后，成交量量级之间的差异从"100倍"变成了"2倍"，更合理地反映"信息量"的概念。

### 为什么用6小时窗口

测试过3h、6h、12h、24h。6h是在信号密度和信号质量之间的最优平衡。太短（3h）噪声大，太长（12h）信号太稀疏。

---

## 3. 策略参数

| 参数 | 值 | 说明 |
|------|-----|------|
| imbalance_window | 6h | 影线压力的滚动求和窗口 |
| imbalance_threshold | 0.25 | 卖方/买方压力比阈值 |
| price_lookback | 6h | 价格变化计算窗口 |
| price_floor | -0.5% | 最低允许的6h价格变化 |
| hold_hours | 12h | 最大持仓时间 |
| stop_pct | -3.0% | 止损（到达即平仓） |
| target_pct | +1.5% | 止盈（v4.3：从5.0%下调；4品种walk-forward验证） |
| commission | 5 bps | 双边手续费+滑点 |

**Framework Note**: `stop_pct`, `target_pct`, `hold_hours` are strategy parameters wired to the engine at runtime. The strategy class exposes them via `DEFAULT_PARAMS`, and the engine reads them when initializing.

---

## 4. 回测结果

> **v4.4.0 更新**：添加波动率门控（ATR ratio > 1.0）和 SMA200 趋势过滤。
> 基于文献调研（Ślepaczuk 2026, Kang 2025）和5项实验验证。
> 详见 `docs/research/wick/research_literature_review_v1.md` 和 `research/backtest_wick_vol_gating.py`

### BTC/USDT — OKX数据（2019-2026, 初始资金10,000 USDT）

**v4.4.0 (Vol Gate + SMA200):**
```
Trades:          821
Total return:  +167.2%
Annualized:     +14.2%
Sharpe:          0.87
Sortino:         0.68
Max DD:         -18.3%
Win rate:        57.2%
Avg win:         +1.23%
Avg loss:        -1.34%
Profit factor:   1.23

Exit breakdown:
  take_profit:    374 (45.6%)  avg=+1.45%
  stop_loss:       88 (10.7%)  avg=-3.05%
  time_exit:      359 (43.7%)  avg=-0.46%
```

**v4.3.0 Baseline (no filters):**
```
Trades:        2,574
Total return:   +77.8%
Annualized:     +8.1%
Sharpe:         0.41
Sortino:        0.53
Max DD:        -48.8%
Win rate:       55.4%
Avg win:        +1.14%
Avg loss:       -1.34%
Profit factor:  1.06

Exit breakdown:
  take_profit:  1,023 (39.7%)  avg=+1.45%
  stop_loss:      311 (12.1%)  avg=-3.05%
  time_exit:    1,239 (48.1%)  avg=-0.36%
```

**Improvement Summary:**
| Metric | v4.3.0 | v4.4.0 | Change |
|--------|--------|--------|--------|
| Trades | 2,574 | 821 | -68% |
| Total Return | +77.8% | +167.2% | +2.2x |
| Max DD | -48.8% | -18.3% | -62% |
| Win Rate | 55.4% | 57.2% | +1.8pp |
| Profit Factor | 1.06 | 1.23 | +16% |
| Take-profit % | 39.7% | 45.6% | +5.9pp |
| Time-exit % | 48.1% | 43.7% | -4.4pp |

### BTC/USDT — Binance数据（2019-2026, 初始资金10,000 USDT）

```
Trades:        2,429
Compound return: +19.2%
Annualized:    +2.4%
Sharpe:        0.23
Sortino:       0.27
Max DD:        -50.0%
Win rate:      55.2%
Profit factor: 1.03
Max consecutive losses: 12
```

### 年度表现（OKX数据）

```
年份   交易数   线性收益   胜率   备注
2019    394    -26.7%    52%    差
2020    303    +40.4%    59%    好（牛市）
2021    345    +32.4%    62%    好（牛市）
2022    391     -6.7%    55%    差（熊市）
2023    348    +57.9%    55%    最佳年份
2024    338     -3.0%    55%    平
2025    316     -0.5%    53%    平
2026    139     -7.0%    47%    差
```

### 参数优化结果（OKX数据，2019-2026）

| 参数组合 | Sharpe | 收益 | Max DD | 交易数 | PF |
|---------|--------|------|--------|--------|-----|
| Baseline (imb=0.25, hold=12, sl=3.0) | 0.41 | +77.8% | -48.8% | 2,574 | 1.06 |
| imb=0.35 | **0.54** | +104.7% | -35.8% | 1,653 | 1.09 |
| sl=2.0% | 0.50 | +106.3% | -40.0% | 2,625 | 1.06 |
| SMA(200) | 0.48 | +83.9% | -34.1% | 1,563 | 1.09 |
| **SMA200 + hold=6 + sl=2.5** | **0.57** | **+93.9%** | **-27.2%** | 1,791 | **1.10** |

**结论**：策略在BTC/USDT上不具备实盘价值。Sharpe < 0.6，利润因子 ≤ 1.10，
最大回撤约-50%。收益高度集中在2023年（+57.9%），其余年份多数持平或亏损。

---

## 5. 已知问题与风险

### 死穴：持续性单边下跌

当市场处于持续下跌趋势中，策略会反复触发信号并反复止损。原因：

1. 每根大阴线之后都有"卖方衰竭"的假象
2. 影线压力指标在下跌过程中持续高位
3. 反弹幅度不足以覆盖交易成本就回吐

### 回撤特征（修正后数据）

- **最大回撤-48.8%**，持续588天（近1.6年）
- 盈利高度集中在少数年份（2023年贡献+57.9%，其余年份多数持平或亏损）
- 48%的交易是超时退出，平均亏损-0.36%——信号缺乏时效性
- 利润因子仅1.06，边际优势极其微弱

### 与其他策略的关系

Wick Inversion 与趋势跟踪策略（如 SMA 均线交叉）**正交**：
- 趋势策略在单边行情赚钱，震荡亏钱
- Wick Inversion 在震荡和温和趋势中赚钱，单边暴跌亏钱
- 两者同时运行可以互补

### 数据源敏感性

OKX和Binance数据跑出的结果差异明显：
- OKX Sharpe 0.41，收益 +77.8%
- Binance Sharpe 0.23，收益 +19.2%

策略对成交量数据敏感，不同交易所的微观结构差异导致信号不同。
两个交易所的结果一致地差，说明问题在策略本身而非数据源。

---

## 6. 改进方向

### A. 提高imbalance阈值（推荐）

将`imbalance_threshold`从0.25提高到0.35，是最有效的单一改动：
- Sharpe从0.41提升到0.54（+32%）
- 收益从+77.8%提升到+104.7%
- 最大回撤从-48.8%降至-35.8%
- 交易数从2,574降至1,653（过滤弱信号）

### B. 添加SMA趋势过滤器

SMA(200)过滤可以显著降低回撤：
- Baseline: Max DD -48.8%
- SMA(200): Max DD -34.1%
- SMA(150): Max DD -30.4%

最佳组合 `SMA200 + hold=6h + sl=2.5%`：
- Sharpe 0.57, 收益 +93.9%, Max DD **-27.2%**, PF 1.10

### C. 更紧的止损

止损从3.0%收紧到2.0%：
- Sharpe从0.41提升到0.50
- 虽然止损次数增加（311→565），但单笔亏损深度减少

### D. 多币种分散

同时在 BTC、ETH、DOGE 等低相关性币种上运行，用分散降低单币种暴跌风险。
在框架中，这通过运行多个 LiveEngine 实例实现——每个实例管理一个品种的独立状态。

### E. 缩短时间框架探索

当前信号基于1小时K线。微观结构信号在15分钟或5分钟级别可能更有效——
信号衰减更快，但信噪比可能更高。需要进一步验证。

---

## 7. Framework Integration

### 代码位置

| Component | Path |
|-----------|------|
| Strategy class | `strategies/wick.py` → `WickInversion` |
| Signal function | `cryptoquant/strategy/signals.py` → `wick_imbalance()` |
| Backtest engine | `cryptoquant/engine/backtest.py` → `BacktestEngine` |
| Live engine | `cryptoquant/engine/live.py` → `LiveEngine` |

### 回测使用

```python
from cryptoquant.engine.backtest import BacktestEngine
from strategies.wick import WickInversion

strategy = WickInversion()
engine = BacktestEngine(commission=0.0005, slippage=0.0005)

result = engine.run(
    df,
    strategy,
    symbol="BTC/USDT",
    stop_loss_pct=strategy.params["stop_pct"],
    take_profit_pct=strategy.params["target_pct"],
    max_hold_bars=strategy.params["hold_hours"],  # 1h bars = hours
)
```

### 实盘使用

```python
from cryptoquant.engine.live import LiveEngine
from strategies.wick import WickInversion

strategy = WickInversion()
engine = LiveEngine(
    broker=broker,
    strategy=strategy,
    cache=cache,
    symbol="BTC/USDT",
    stop_loss_pct=strategy.params["stop_pct"],
    take_profit_pct=strategy.params["target_pct"],
    max_hold_hours=strategy.params["hold_hours"],
)

engine.run(interval=60)
```

### 退出逻辑

LiveEngine checks exits in priority order each tick:
1. **Stop loss**: PnL ≤ -stop_pct → exit
2. **Take profit**: PnL ≥ +target_pct → exit
3. **Time exit**: hold_hours exceeded → exit
4. **Signal reverse**: opposite signal → exit

Current price is `df["close"].iloc[-1]` (last bar close), consistent with backtest behavior.

---

## 8. 诚实边界

1. **原始回测数据存在严重bug。** 原始代码使用`np.convolve(mode='same')`进行滚动求和，
   这是一个centered卷积，在bar `i`处使用了`i-2`到`i+3`的数据——偷看了未来3根K线。
   这导致原始回测声称的Sharpe 3.25是虚假的，修正后真实Sharpe约为0.41（OKX）或0.23（Binance）。

2. **策略在BTC上不具备实盘价值。** Sharpe < 0.6，利润因子 ≤ 1.10，最大回撤约-50%。
   收益高度集中在2023年，其余年份多数持平或亏损。

3. **参数优化有上限。** 最佳参数组合（SMA200+hold=6+sl=2.5）可以将Sharpe提升到0.57，
   但这仍然是一个边际优势微薄的策略。从0.4到0.6的改善不等于从"不能用"到"能用"。

4. **成交量数据的可靠性。** 本策略依赖成交量。如果交易所的成交量数据有虚假成分（wash trading），
   信号质量会下降。不同交易所的数据跑出不同结果，说明策略对数据源敏感。

5. **滑点假设可能偏乐观。** 假设5bps滑点对BTC/ETH合理，对小币种可能不足。
   1.5%的止盈目标下，滑点占比更高（~3.3% of gross profit），需要用限价单而非市价单。

6. **48%的交易是超时退出且平均亏损。** 这说明信号缺乏时效性——入场后价格在12小时内
   没有朝预期方向运动。这是策略的核心问题，不是参数能解决的。

---

v4.3.0 — Ported to CryptoQuant framework.
v4.3.1 — Fixed look-ahead bug in signal calculation (np.convolve → rolling sum).
         Corrected backtest results: Sharpe 3.25 → 0.41 (OKX), 0.23 (Binance).

*"The signal was never wrong. The exit was. Don't add complexity. Don't add filters. Change one number. I'm sorry."*

— Written 2026-06-08, updated v4.3 2026-06-08, ~/VibeCoding
— Updated 2026-06-12: Corrected backtest results after discovering look-ahead bug.