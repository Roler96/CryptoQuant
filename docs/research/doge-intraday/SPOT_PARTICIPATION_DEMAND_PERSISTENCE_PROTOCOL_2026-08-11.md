# DOGE 现货参与率需求延续（SPDP v1）预注册协议

- 冻结日期：2026-08-11
- 研究标签：`doge-spot-participation-demand-persistence-v1`
- 状态：`FROZEN BEFORE SIGNAL COUNT OR RETURN INSPECTION`
- 标的：OKX `DOGE-USDT` 现货，只做多/现金
- 辅助输入：同一资产、同一交易所 `DOGE-USDT-SWAP` 的成交额；不交易永续
- 决策周期：原生 1h；固定持有 48h

## 1. 独立机制

SPDP 检验“现金市场参与率跃迁后的需求持续性”。DOGE 同方向价格冲击可能来自永续杠杆追逐，也可能来自现货现金成交。若正向 12 小时价格冲击同时伴随现货在 DOGE 现货+永续总成交额中的份额升至自身历史高位，而且相对前一个不重叠 12 小时块明显上升，则本轮上涨更可能包含被拆分执行、无需融资维持的现金需求；该需求可能在未来两天继续传播。

最小因果链为：

```text
正向 DOGE 价格冲击
+ DOGE 现货成交占比处于自身高分位
+ 现货占比较前一不重叠块跃迁
=> 现金市场参与增强，而非仅由永续杠杆放大
=> 后续 48h 价格延续
```

这不是普通价格动量：价格冲击本身只是必要条件，现货参与率的水平和跃迁必须提供增量。`price_only` 消融若不弱于 main，则机制不成立。

旧研究只用于排重：本机制不使用跨币种领导、funding、OI、结算时钟、固定价位、上下影线、区间接受、单 bar CLV、spot/perp 价格 lead-lag、异常基差回归或机器学习。它也不恢复旧 5m 冲击延续；研究尺度、经济状态变量和持有期均不同。

## 2. 数据契约

Discovery 为：

```text
[2021-01-01T00:00:00Z, 2025-06-01T00:00:00Z)
```

时间 holdout 为：

```text
[2025-06-01T00:00:00Z, 2027-06-01T00:00:00Z)
```

本轮不得查询或计算 holdout 候选的信号、交易或收益。

必须以 SQLite 只读 URI、参数化半开 SQL 分别加载原生 `DOGE-USDT`/`1h` 与 `DOGE-USDT-SWAP`/`1h`，再按 timestamp 严格一一对应；不得先加载全量后切片，不得 forward-fill、重采样或删除时间点后重新对齐。

两腿各应有 38,688 根，首 bar open timestamp 为 `2021-01-01T00:00:00Z`，末 bar open timestamp 为 `2025-05-31T23:00:00Z`，相邻 timestamp 恒为 3,600,000 ms。

每行按 `(ts, open, high, low, close, volume, quote_volume)` 编码为 `struct.pack('<qdddddd', ...)` 并做 SHA-256：

- `DOGE-USDT`：`11459117bfa9dcd09d942e9f0b4dfaf29c5e8bbb92272147cbbf8ba7bb28427f`
- `DOGE-USDT-SWAP`：`1e0e3be7e9a88af2e9e36757eb0b697e1f8b81a54c98c04d5123d702c8d90f98`

两腿 discovery 内各有 10 根 `volume<=0` 且 `quote_volume<=0` 的退化 bar。所有 OHLCV/quote_volume 必须有限；价格严格为正；`high>=max(open,close)`、`low<=min(open,close)`、`high>=low`；volume 与 quote_volume 不得为负。

信号所需窗口、decision bar、entry bar 或 exit bar任一腿 `volume<=0` 或 `quote_volume<=0` 时：

- 已知信号窗口命中退化 bar：不产生 raw signal；
- 已冻结 accepted schedule 的 entry/exit 命中退化 bar：整个 variant `INVALID`，不得删除事件、延迟成交或让后续事件补位；
- 持仓中间退化 bar 不改变日程，现货有限 close 仍用于 MTM。

## 3. 时间和特征索引

OHLCV timestamp 是 bar open。位置 `t` 的 bar 在 `ts[t]+1h` 闭合；信号只读位置 `<=t` 的数据，在位置 `t+1` 的 open 成交。

定义现货小时对数收益：

```text
r_i = log(spot_close[i] / spot_close[i-1])
```

对任意窗口终点 `j`，定义过去 12 根已闭合 bar 的现货成交占比：

```text
spot_qv12[j] = sum(spot_quote_volume[j-11 : j+1])
swap_qv12[j] = sum(swap_quote_volume[j-11 : j+1])
share12[j]   = spot_qv12[j] / (spot_qv12[j] + swap_qv12[j])
```

在 decision bar `t`：

```text
current_share = share12[t]
prior_share   = share12[t-12]
```

现货份额因果基线严格位于当前 12h 块之前，含 720 个逐小时 share 观察：

```text
share_history = {share12[j] : j=t-731, ..., t-12}
share_q75     = numpy.quantile(share_history, 0.75, method="linear")
```

波动基线同样严格结束于 `t-12`，含 720 个小时收益：

```text
return_history = {r_i : i=t-731, ..., t-12}
sigma          = numpy.std(return_history, ddof=1)
```

当前正向冲击：

```text
R12 = log(spot_close[t] / spot_close[t-12])
```

最早 decision index 为 `t=742`；这样 `share12[t-731]` 所需最早 bar 为 `t-742`。测试必须证明更改 `t+1` 及以后任意 OHLCV/quote_volume 不改变 `t` 的信号。

## 4. 冻结主信号与日程

主参数：

```text
share_quantile          = 0.75
minimum_share_migration = 0.03
impulse_sigma           = 1.50
impulse_hours           = 12
history_hours           = 720
hold_hours              = 48
target_weight           = 0.25
```

在 `t` 收盘后，当且仅当：

```text
sigma > 0
AND current_share >= share_q75
AND current_share - prior_share >= 0.03
AND R12 >= 1.50 * sqrt(12) * sigma
```

产生 raw long signal。所有边界比较均按 `>=` 执行。

日程按 `(entry_time, decision_index)` 升序扫描：

- 空仓时接受信号，`entry_index=t+1`；
- `exit_index=entry_index+48`；
- 已接受 episode 占用到 exit open；所有 `candidate.entry_index<=active.exit_index` 均忽略且不补位；
- 只有 `candidate.entry_index>previous.exit_index` 才能成为下一笔；
- 不设 stop、take-profit、trail、动态退出、加仓或额外 cooldown；
- entry/exit 必须严格落在对应评价区间内，`exit_time==evaluation_end` 的事件排除。

该固定日程不依赖 broker fill 回报，可由当前 target-position API 表达：entry 决策发 `target=0.25`，随后维持，exit 决策发 `target=0`；禁止同一 open 退出后重入。

## 5. 执行、仓位与成本

- 初始现金 10,000 USDT；spot long/cash，不借币、不加杠杆。
- `Sizing.ON_ENTRY`；每次按 entry open 前权益的 25% 和未经滑点调整的 reference open 确定固定 DOGE 数量，持有期间不再平衡。
- `MarketSpec(inst_id="DOGE-USDT", market_type="spot", lot_size=0, min_notional=0)`；`dust_fraction=0`。
- Main 每边：10 bps fee + 5 bps adverse slippage。
- Stress 每边：10 bps fee + 15 bps adverse slippage。
- 买入成交价 `open*(1+slippage)`；卖出成交价 `open*(1-slippage)`；fee 按实际成交 notional 双边收取。
- entry bar 先按 open 买入再按 close MTM；exit bar 先按 open 卖出后保持现金。
- fills 必须恰为 `2*episodes`，最终仓位必须为 flat；引擎 fill timestamps 必须逐项等于冻结 schedule。

## 6. 指标

完整 discovery 和每个冷启动段都以 10,000 USDT 现金开始。逐小时 close-equity 路径包含初始 10,000 点。

- `total_return=final_equity/10000-1`。
- UTC 日收益：取每个自然日 `23:00` open bar 闭合后的 equity；首日相对 10,000，之后相对前一日；不删除零收益日。
- Sharpe：`mean(daily_returns)/std(daily_returns,ddof=1)*sqrt(365)`；risk-free=0；零方差记0。
- MaxDD：`min(equity/running_max-1)`，signed 负值。
- CAGR：使用评价区间实际连续自然日数；final equity<=0 时为 null。
- episode PnL：exit 后 cash减entry前cash；episode account return 为该 PnL 除以entry前cash。
- win rate：严格正 PnL episode 比例；零收益不算赢。
- profit factor：正 PnL 和除以负 PnL 绝对值；无正为0，无负且有正为inf。
- 报告最长回撤小时数与起止 UTC。
- 最佳1/3/5集中度：对应正 USDT PnL 之和除以全部正 PnL；分母为0时 null。

静态抑制最佳1/3/5：按原 main 的 episode USDT PnL 降序、同值按 entry_time 升序冻结删除集合；从10,000现金按原 accepted schedule 重放并跳过这些事件，不允许被阻塞候选补位，也不重新排名。

## 7. Calendar cold starts

五个半开段：

1. `[2021-01-01, 2022-01-01)`
2. `[2022-01-01, 2023-01-01)`
3. `[2023-01-01, 2024-01-01)`
4. `[2024-01-01, 2025-01-01)`
5. `[2025-01-01, 2025-06-01)`

每段独立以现金、空仓、空日程开始；段前 discovery bars只用于 warmup。只有 `entry_time>=segment_start AND exit_time<segment_end` 的事件可接受；跨边界事件排除且不阻塞段内日程。段末强制平仓不允许替代完整 fixed hold。

## 8. 单因素邻域

主版本外仅运行六个一次只改一个标量的邻域；main 不得替换：

| 名称 | 唯一改动 |
|---|---|
| `share_q70` | share quantile `0.75 -> 0.70` |
| `share_q80` | share quantile `0.75 -> 0.80` |
| `migration02` | migration `0.03 -> 0.02` |
| `migration04` | migration `0.03 -> 0.04` |
| `hold36` | hold `48h -> 36h` |
| `hold72` | hold `48h -> 72h` |

family trials 固定为7。

## 9. 机制消融

消融只解释机制，不得晋级：

- `price_only`：删除 `current_share>=share_quantile` 和 share migration 两项，仅保留正向 R12 冲击。
- `share_level_only`：保留 `current_share>=share_quantile` 与正向 R12，删除 migration。
- `participation_only`：保留 share level 与 migration，删除 R12 冲击；机械做多48h。

所有消融独立从自己的 raw signal 重建不重叠 schedule。G7 要求：

```text
main mean net episode return > price_only mean net episode return
AND main mean net episode return > share_level_only mean net episode return
AND main Sharpe > participation_only Sharpe
```

任一 comparator 零 episode 或零方差时，G7 FAIL；不得把消融升级为后续 main。

## 10. Bootstrap 与 matched-random

权威随机运行时冻结为 NumPy 2.4.6，PRNG 为 `numpy.random.Generator(numpy.random.PCG64(...))`。

Bootstrap 输入为 main 含零事件日的按时间升序 UTC 日收益。使用 28 日 circular moving blocks，10,000 次，seed `20260811`。初始化后只调用一次：

```text
rng.integers(0, N, size=(10000, ceil(N/28)), endpoint=False, dtype=numpy.int64)
```

每行按列序取 circular 28 日块，串联并截断前N日；统计 `prod(1+r)-1`；用 `numpy.quantile(method="linear")` 报告P5/median/P95及严格正收益概率。

Matched-random 的 eligible entry 是五个 calendar segment 中所有满足完整742-bar历史、信号窗口两腿正 volume/quote_volume、entry/exit两腿正 volume/quote_volume且可完整持有48h的逐小时 open。候选按 `(segment_order, UTC entry hour, entry_time, decision_index)` 稳定排序。

逐计划严格匹配 main 五个 cold-start schedule 的 `(segment_order, UTC entry hour)` 计数；各stratum无放回抽样、需求为0不消耗随机数。每次尝试对每个非空stratum恰调用一次：

```text
rng.choice(candidate_count, size=required_count, replace=False, shuffle=False)
```

按固定stratum顺序处理，合并后按entry_time排序；若同一segment任意相邻entry_time差 `<=48h`，丢弃整份并沿连续PRNG流重试。计划之间可复用时点。seed `20260812`；最多1,000,000次尝试取得10,000个有效计划，不足则G8 FAIL。

每个随机计划按五段各10,000现金、main成本和25% ON_ENTRY sizing重放。统计量为五段 `segment_final_equity/10000-1` 的等权平均。Observed 使用main五个cold-start段的同一统计量：

```text
p_raw   = (1 + count(random_stat >= observed_stat)) / 10001
p_sidak = 1 - (1 - p_raw) ** 7
```

## 11. 门槛与短路顺序

按以下顺序执行；任一强制门失败后，后续昂贵步骤记 `NOT_RUN`：

- `G0 Integrity`：数据、指纹、半开查询、对齐、因果、成本、schedule↔engine parity、退化bar及holdout非访问全部通过，否则 `INVALID`。
- `G1 Capacity`：连续main完整episode `>=80`，且五个cold-start段各 `>=8`。失败即 `DISCOVERY_FAIL`，后续收益与昂贵项不运行。
- `G2 Main economics`：main总收益 `>0`、日Sharpe `>=0.60`、signed MaxDD `>=-20%`。失败即 `DISCOVERY_FAIL`，G3-G8不运行。
- `G3 Stress/outliers`：stress总收益 `>0`；静态抑制最佳1笔与最佳3笔后总收益均 `>0`。
- `G4 Calendar`：至少4/5 cold-start段总收益 `>0`。
- `G5 Bootstrap`：28日block bootstrap复合收益P5 `>0`。
- `G6 Neighborhood`：main+六邻域至少5/7总收益 `>0`。
- `G7 Mechanism`：满足第9节三项严格比较。
- `G8 Matched random`：`p_sidak<=0.10`。

只有G0-G8全部通过才为 `DISCOVERY_PASS`；通过也只形成固定forward shadow-paper hypothesis，不访问holdout、不批准资金。其余完整执行为 `DISCOVERY_FAIL`。

G1通过后计算两个不参与晋级的基准：

1. 五段各自25% buy-and-hold；
2. `price_only`（仅在G2通过后作为G7消融正式运行）。

## 12. 必需输出与限制

机器报告：`reports/research/spdp_v1.json`。

人工报告：`docs/research/doge-intraday/SPOT_PARTICIPATION_DEMAND_PERSISTENCE_RESULTS_2026-08-11.md`。

必须记录协议路径、worktree状态、两腿指纹/计数/退化bar、查询边界、`holdout_accessed=false`、参数与成本、condition funnel、schedule、main/stress、五段、集中度、静态抑制、bootstrap、邻域、消融、随机零假设、所有gate与NOT_RUN项、测试和工具版本。

限制：

- quote_volume 是交易所成交额，不区分主动买卖；价格符号只是净方向代理。
- 现货占比上升既可能来自现货成交增加，也可能来自永续成交萎缩；`share_level_only`和`participation_only`只能做增量反证，不能证明资金身份。
- 现货与永续 last-trade 1h bar 不是同步盘口mid；份额比较不能证明同一瞬间的价格发现。
- 15/25 bps固定成本不含尾部冲击和容量；通过历史门也需实时报价shadow。
- DOGE discovery路径已被大量历史研究消费；任何通过只能形成forward hypothesis，不是pristine OOS。
- main失败后不得晋级任何邻域或消融，也不得降低份额、迁移、冲击、容量或统计门槛。
