# DOGE 负资金费率韧性反弹（NFRR v1）预注册协议

- 冻结日期：2026-08-10
- 研究标签：`doge-negative-funding-resilience-rebound-v1`
- 状态：`FROZEN BEFORE RETURN INSPECTION`
- 交易标的：OKX `DOGE-USDT` 现货，只做多/现金
- 决策周期：原生 1h；单笔固定持有 24h

## 1. 独立机制与历史边界

本轮独立提出的机制是“衍生品拥挤与现货韧性背离”：若 DOGE 永续的已实现资金费率落入其自身过去 90 天负尾部，但 DOGE 现货在同一 8 小时窗口并未下跌，说明做空拥挤尚未压低现货，后续 24 小时可能出现空头回补或风险偏好恢复带来的现货上行。

这不是旧研究的价格暴跌反转、OI flush、现货/永续基差回归、永续溢价趋势确认、结算时点价格冲击、突破延续、波动压缩或 bar 几何。旧仓库只用于建立这些禁止重复的家族边界，不能提供本轮参数或结果。

允许输入仅有：

1. OKX `DOGE-USDT` 现货原生 1h OHLCV；
2. OKX 官方 `DOGE-USDT-SWAP` 已实现 funding settlement 档案。

不使用 BTC、ETH、其他币种、OI、swap OHLCV、预测 funding、盘口、成交方向、链上或社交数据。

## 2. 冻结数据契约

- Discovery：`[2022-04-01T00:00:00Z, 2025-06-01T00:00:00Z)`。
- Funding 月档：`2022-04` 至 `2025-06`（含）。`2025-06` 只允许提供 timestamp 严格小于 discovery end 的边界记录。
- 时间 holdout：`[2025-06-01T00:00:00Z, 2027-06-01T00:00:00Z)`，本轮不得查询、加载或报告其候选收益。
- Spot SQL 必须在数据库层使用半开边界；不得先加载全量再切片。
- Funding ZIP 必须来自 OKX 官方 monthly swaprates URL；逐档记录 ZIP SHA-256、CSV schema、行数、首末 timestamp，并生成总 manifest SHA-256。
- Spot 原始行在过滤前按 `(ts, open, high, low, close, volume, quote_volume)` 排序并生成 SHA-256 指纹。
- Spot 必须为连续 1h timestamp，有限且价格为正；任何决策、entry、持有区间或 exit bar 的 `volume<=0`、缺失、非有限或非法 OHLC 都使该事件无效。固定 exit 不允许延后。
- `quote_volume` 不进入信号，只绑定数据身份；允许其为空，但指纹必须保留空值语义。

## 3. Funding 与 1h bar 的因果对齐

对 funding record `i`，原始 settlement timestamp 为 `f_i`，保留 OKX 给出的秒/毫秒偏移，不向整点篡改。

定义：

```text
d_i = 最小整点，使 d_i >= f_i
```

只有在 `d_i` 时刻开始的 1h spot bar 完整闭合后，才允许使用该 funding 与截至该 bar 的 spot 数据。因此：

```text
decision_time_i = d_i + 1h
entry_time_i    = decision_time_i + 1h
exit_time_i     = entry_time_i + H
```

例：`f_i=08:00:03`，则 `d_i=09:00`，使用 `09:00..10:00` bar 的 close 在 `10:00` 决策，`11:00` open 入场。若 `f_i` 恰为 `08:00:00`，则 `d_i=08:00`，使用 `08:00..09:00` bar，在 `09:00` 决策，`10:00` open 入场。

同一 `decision_time` 若出现多条 funding 记录，数据契约失败，不做去重或择一。

## 4. 冻结主信号

主配置：

```text
funding_history_settlements = 270   # 约90天，严格排除当前记录
funding_quantile            = 0.10  # NumPy linear quantile
spot_resilience_hours       = 8
hold_hours                  = 24
weight                      = 0.25
```

对当前 funding `F_i`：

```text
Q10_i = linear_quantile(F_{i-270}, ..., F_{i-1}, 0.10)
R8_i  = log(spot_close[decision_time_i] /
            spot_close[decision_time_i - 8h])
raw_signal_i = (F_i < 0) AND (F_i <= Q10_i) AND (R8_i >= 0)
```

边界均按字面执行：funding 用 `<=`，韧性用 `>=`。历史不足 270 次、任一所需 bar 不连续或非法时不产生 raw signal。

按 `entry_time` 升序扫描 raw signals：

- 空仓时接受事件；
- 已接受事件的 `entry_time <= candidate.entry_time < exit_time` 时忽略候选，不补位；
- `candidate.entry_time == previous.exit_time` 允许先退出、再以该时点 open 重新入场；
- 不设额外 cooldown、止损、止盈、trail 或动态退出；
- Discovery 边界内不能完整退出的事件排除。

## 5. 执行、仓位与成本

- 初始现金 `10,000 USDT`；spot long/cash，不借币、不加杠杆。
- `Sizing.ON_ENTRY`：每次按入场前账户权益的 25% 确定固定 DOGE 数量，持有期间不再平衡。
- 买入价：`entry_open * (1 + slippage_bps/10000)`；卖出价：`exit_open * (1 - slippage_bps/10000)`。
- fee 按实际成交 notional 双边收取。
- Main：每边 `10 bps fee + 5 bps slippage`。
- Stress：每边 `10 bps fee + 15 bps slippage`。
- 每根 1h close 标记权益；收益、Sharpe、MaxDD 都从完整逐时权益路径计算。
- Sharpe：先生成每个 UTC 自然日最后一个 1h mark，缺交易日保留零收益，再算 `mean(daily)/std(daily, ddof=1)*sqrt(365)`；标准差为零时 Sharpe 记 0。

## 6. 冻结单因素邻域

主版本之外仅运行六个一次只改一个标量的邻域；邻域不得替代 main：

| 名称 | 唯一改动 |
|---|---|
| `history180` | funding history `270 -> 180` |
| `history360` | funding history `270 -> 360` |
| `quantile05` | funding quantile `0.10 -> 0.05` |
| `quantile15` | funding quantile `0.10 -> 0.15` |
| `hold16` | hold `24h -> 16h` |
| `hold32` | hold `24h -> 32h` |

家族 trial 数固定为 7（main + 6 neighbors）。

## 7. 机制消融与随机零假设

消融只解释机制，不得晋级：

- `funding_only`：保留 `F_i<0 AND F_i<=Q10_i`，删除 `R8_i>=0`；其余日程、重叠与成本不变。
- `resilience_only`：在每个 funding settlement 检查 `R8_i>=0`，删除 funding tail 条件；其余不变。
- `opposite_resilience`：保留 funding tail，但改为 `R8_i<0`；它是符号反证，不是候选。

匹配随机入场：从所有通过数据完整性、历史 warm-up 且可完整持有 24h 的 funding 对齐时点抽样；逐计划严格匹配 main 实际事件的 `(entry calendar segment, UTC entry hour)` 计数，无放回、同样的不重叠规则、仓位与成本。无法生成完整匹配计划则丢弃整份计划。生成 10,000 个有效计划，seed `20260810`；统计量为 main 的复合总收益：

```text
p_raw   = (1 + count(random_return >= observed_return)) / 10001
p_sidak = 1 - (1 - p_raw) ** 7
```

## 8. Calendar segments、集中度与 bootstrap

四段固定为：

1. `2022-07-01 .. 2023-01-01`（给 270 次 funding warm-up 留边界）；
2. `2023-01-01 .. 2024-01-01`；
3. `2024-01-01 .. 2025-01-01`；
4. `2025-01-01 .. 2025-06-01`。

逐段从 10,000 USDT 现金冷启动；更早输入仅用于指标 warm-up，不继承持仓或权益。段末不能完整退出的事件排除。

Bootstrap 使用主版本含零事件日的 UTC 日收益；28 日 circular moving blocks，10,000 次，seed `20260810`。每份样本截断至原日数，复合 `prod(1+r)-1`，用 NumPy `linear` 5% 分位。报告 P5、median、P95 和正收益概率。

按 episode 的净 PnL 排序，静态抑制最佳 1、3、5 笔后重放原固定日程；不允许被原事件阻塞的候选补位。

## 9. 门槛与短路顺序

按以下顺序执行；任一强制门失败后，后续昂贵步骤标记 `NOT_RUN`：

- `G0 Integrity`：全部数据、时间、执行、成本和 holdout 非访问检查通过，否则 `INVALID`。
- `G1 Capacity`：main 完整 episode `>=80`，四段每段 `>=10`。失败即 `DISCOVERY_FAIL`，stress/neighbors/ablations/bootstrap/random 不运行。
- `G2 Main economics`：main 总收益 `>0`、日 Sharpe `>=0.60`、MaxDD `<=20%`。失败即 `DISCOVERY_FAIL`，后续昂贵步骤不运行。
- `G3 Stress/outliers`：stress 总收益 `>0`；抑制最佳 1 笔后总收益 `>0`；抑制最佳 3 笔后总收益 `>0`。
- `G4 Calendar`：四个冷启动段至少 3 段总收益 `>0`。
- `G5 Bootstrap`：28 日 block bootstrap 复合收益 P5 `>0`。
- `G6 Neighborhood`：main 加六邻域至少 5/7 总收益 `>0`。
- `G7 Mechanism`：main 的平均净 episode return 严格大于 `funding_only` 和 `opposite_resilience`；main Sharpe 严格大于 `resilience_only`。
- `G8 Matched random`：`p_sidak <=0.10`。

仅 G0–G8 全部通过才为 `DISCOVERY_PASS`。通过也只允许登记为冻结 shadow-paper hypothesis，不读取 holdout、不批准资金。其余完整运行结果均为 `DISCOVERY_FAIL`。

## 10. 必需输出

机器报告：`reports/research/nfrr_v1.json`。人工报告：`docs/research/doge-intraday/NEGATIVE_FUNDING_RESILIENCE_REBOUND_RESULTS_2026-08-10.md`。

必须记录：协议路径、Git worktree 状态、spot/funding 源指纹、查询边界、holdout_accessed=false、全部参数与成本、事件日程、逐时权益摘要、main/stress、四段、抑制最佳 1/3/5、bootstrap、邻域、消融、随机零假设、逐门结果和短路项。

## 11. 预先声明的限制

- 极端负 funding 只说明永续多空支付方向，不直接识别账户杠杆、主动成交或强平。
- “现货韧性”可能只是短期上涨动量，而非空头拥挤因果；消融只能削弱解释，不能证明因果。
- 历史 last-trade 1h open/close 不是盘口中价或可成交深度；15/25 bps 只能作保守代理。
- Discovery 已处在被反复研究过的 DOGE 历史，最多形成 forward 假说，不能称 pristine OOS。
- 若 main 失败，不得把 funding-only、opposite-resilience、邻域或 post-hoc 诊断升级为新主策略。
