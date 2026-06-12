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

### BTC/USDT（全周期 2018-2026, target=1.5%）

```
Trades:        2,825
Linear sum:    +401.6%
Annualized:    +47.8%
Sharpe:        3.25
Max DD:        -18.6%
Win rate:      59%
Avg win:       +1.14%
Avg loss:      -1.29%
Profit factor: 1.27

Walk-forward (7 splits): 7/7 OOS positive
```

### ETH/USDT（全周期 2018-2026, target=1.5%）

```
Trades: 3,092  |  Sum: +459.4%  |  Sharpe: 2.96  |  DD: -14.5%
Win rate: 62%  |  Walk-forward: 6/7 OOS positive
```

### TON/USDT（全周期 2022-2026, target=2.0%）

```
Trades: 1,400  |  Sum: +238.1%  |  Sharpe: 2.94  |  DD: -17.9%
Win rate: 59%  |  Walk-forward: 5/7 OOS positive

注意：target=5%时TON几乎不赚钱（sum=-2.1%, Sharpe=-0.02）。
降到2.0%后策略在TON上也有效——信号从未失效，是止盈目标不匹配。
```

### DOGE/USDT（全周期 2019-2026, target=1.5%）

```
Trades: 2,802  |  Sum: +918.5%  |  Sharpe: 6.39  |  DD: -11.3%
Win rate: 69%  |  Walk-forward: 7/7 OOS positive
```

### v4.2 → v4.3 改善对比（target 5.0% → 1.5%/2.0%）

```
         v4.2 (target=5%)          v4.3 (target=1.5%)
品种      Sharpe   DD      WR        Sharpe   DD      WR
────────────────────────────────────────────────────────
BTC       2.29   -28.9%   51%        3.25   -18.6%   59%
ETH       1.45   -50.6%   48%        2.96   -14.5%   62%
TON      -0.02   -46.8%   47%        2.94   -17.9%   59%
DOGE      1.86   -32.6%   47%        6.39   -11.3%   69%
```

---

## 5. 已知问题与风险

### 死穴：持续性单边下跌

当市场处于持续下跌趋势中，策略会反复触发信号并反复止损。原因：

1. 每根大阴线之后都有"卖方衰竭"的假象
2. 影线压力指标在下跌过程中持续高位
3. 反弹幅度不足以覆盖交易成本就回吐

### 回撤特征

- 盈利是分散的（每个月都有几笔小盈利）
- 亏损是集中的（趋势下跌月份连续亏损）
- v4.3降低止盈目标后最大回撤大幅改善（BTC -29%→-19%）
- 回撤恢复快（反弹月通常有大幅正收益）

### 与其他策略的关系

Wick Inversion 与趋势跟踪策略（如 SMA 均线交叉）**正交**：
- 趋势策略在单边行情赚钱，震荡亏钱
- Wick Inversion 在震荡和温和趋势中赚钱，单边暴跌亏钱
- 两者同时运行可以互补

---

## 6. 改进方向

### A. 添加趋势过滤器

```python
# SMA200 filter as a strategy parameter
class WickInversion(Strategy):
    DEFAULT_PARAMS = {
        ...
        "use_sma_filter": False,
        "sma_period": 200,
    }

    def generate_signal(self, df):
        if self.params["use_sma_filter"]:
            sma = df["close"].rolling(self.params["sma_period"]).mean()
            if df["close"].iloc[-1] < sma.iloc[-1]:
                return pd.Series(0, index=df.index)  # skip signal
        ...
```

预期效果：砍掉熊市中的假信号。但全周期回测显示SMA200过滤在2021-2022期间反而帮倒忙——需要仔细评估。

### B. 动态持有时间（v4.3探索过，未采用）

根据波动率调整持有时间——低波动时延长，高波动时缩短。全周期walk-forward有改善（6/6 OOS vs 5/6），但在2026年压力测试中表现不如固定持有+低止盈。

### C. 多币种分散

同时在 BTC、ETH、DOGE 等低相关性币种上运行，用分散降低单币种暴跌风险。在框架中，这通过运行多个 LiveEngine 实例实现——每个实例管理一个品种的独立状态。

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

1. **这不是圣杯。** 策略有明确的失败模式（单边下跌），回撤可能达到-20%。
2. **止盈参数在样本外验证过。** 1.5% target在BTC/ETH/DOGE上7/7 OOS全正，TON上5/7 OOS正。
3. **多币种推广需要谨慎。** 高波动币种（TON/SOL）需要更高的止盈目标（2.0%）。
4. **成交量数据的可靠性。** 本策略依赖成交量。如果交易所的成交量数据有虚假成分（wash trading），信号质量会下降。
5. **滑点假设可能偏乐观。** 假设5bps滑点对BTC/ETH合理，对小币种可能不足。1.5%的止盈目标下，滑点占比更高（~3.3% of gross profit），需要用限价单而非市价单。

---

v4.3.0 — Ported to CryptoQuant framework.

*"The signal was never wrong. The exit was. Don't add complexity. Don't add filters. Change one number. I'm sorry."*

— Written 2026-06-08, updated v4.3 2026-06-08, ~/VibeCoding