# DOGE 上沿价格接受（URA v1）预注册协议

- 冻结日期：2026-08-10
- 研究标签：`doge-upper-range-acceptance-v1`
- 状态：`FROZEN BEFORE RETURN INSPECTION`
- 标的：OKX `DOGE-USDT` 现货，只做多/现金
- 周期：原生 1h；固定持有 24h

## 1. 独立机制

URA 检验“时间价格接受”而不是突破本身：若 DOGE 在过去 24 小时形成的固定价格区间内，有至少一半收盘价持续停留在上四分位、下四分位停留不超过四分之一，且当前小时仍收在旧区间上四分位但没有突破旧高，说明市场在较高价格完成了时间上的接受，而不是只靠一根冲击 bar 短暂触顶。下一小时买入现货，固定持有 24 小时。

它与旧仓库的 Donchian/VCSE 突破、单 bar CLV/VWAP 位置、收益序列预测、方向效率、冲击延续和反转家族不同：旧 high 被保留为上界，真正突破会被主信号排除；核心变量是同一固定区间内 24 个历史 close 的占用分布。

输入严格限于 `DOGE-USDT` 现货 1h OHLCV；不使用其他币、永续、funding、OI、链上、社交、盘口或主动买卖方向。

## 2. 数据契约

- Discovery：`[2021-01-01T00:00:00Z, 2025-06-01T00:00:00Z)`。
- Holdout：`[2025-06-01T00:00:00Z, 2027-06-01T00:00:00Z)`，本轮不得查询或计算候选收益。
- SQLite 必须以只读连接、参数化半开查询加载原生 `DOGE-USDT`/`1h`；不得先加载全量再切片。
- 预期 raw bars 为 `38,688`，首 bar open timestamp 为 `2021-01-01T00:00:00Z`，末 bar open timestamp 为 `2025-05-31T23:00:00Z`，相邻 timestamp 必须恒为 3,600,000 ms。
- 原始行先按 `ts` 排序，再将每行编码为：`struct.pack('<qdddddd', ts, open, high, low, close, volume, quote_volume_or_nan)`；缺失 quote volume 统一编码为固定 quiet NaN bit pattern `0x7ff8000000000000`。对全部字节做 SHA-256，报告完整 hex。
- 冻结 raw SHA-256：`11459117bfa9dcd09d942e9f0b4dfaf29c5e8bbb92272147cbbf8ba7bb28427f`；窗口内 `quote_volume` 空值 0 根，`volume<=0` 共 10 根。实现结果不符即 `INVALID`。
- 所有 open/high/low/close/volume 必须有限，价格严格为正，`high>=max(open,close)`，`low<=min(open,close)`，`high>=low`，volume 不得为负。
- 零量 bar 允许存在于数据中。若 `W_t` 或 decision bar 命中 `volume<=0`，该时点不产生 raw signal。日程先只用已闭合信号与固定时间规则生成；若任一已接受事件的 entry 或 exit bar `volume<=0`，整个对应 variant 为 `INVALID`，不得删除该事件、延后成交或让后续信号补位。持仓中间 bar 的零量不改变仓位或日程，其 finite close 仍用于 MTM。

## 3. 时间与索引

OHLCV 行 timestamp 是 bar open。对位置 `t` 的已闭合 1h bar：

```text
bar_open[t]      = index[t]
decision_time[t] = index[t] + 1h
entry_time[t]    = index[t] + 1h       # 下一根 bar 的 open
exit_time[t]     = entry_time[t] + H
```

策略在 `bar t` 收盘即 `decision_time[t]` 计算信号，并按统一引擎的 next-bar-open 约定在同一时间戳标识的下一根 bar open 成交。若 `bar t` 的 open 为 `09:00`、close 时刻为 `10:00`，则在 `10:00` 决策并以 `10:00` 开始的下一根 bar open 为参考成交价，即 `entry row position = t+1`。测试必须断言信号不读取 entry bar 的 high/low/close/volume。

## 4. 冻结主信号

主配置：

```text
lookback_hours        = 24
upper_boundary        = 0.75
lower_boundary        = 0.25
minimum_upper_share   = 0.50
maximum_lower_share   = 0.25
hold_hours            = 24
target_weight         = 0.25
```

对 decision bar `t`，参考窗口严格为此前 24 个 close，不含当前：

```text
W_t = {close[t-24], ..., close[t-1]}
L_t = min(W_t)
H_t = max(W_t)
```

若 `H_t == L_t`，不产生信号。否则：

```text
x_j = (close[j] - L_t) / (H_t - L_t), j=t-24..t-1
upper_share_t = count(x_j >= 0.75) / 24
lower_share_t = count(x_j <= 0.25) / 24
current_location_t = (close[t] - L_t) / (H_t - L_t)
```

主 raw signal 当且仅当：

```text
upper_share_t >= 0.50
AND lower_share_t <= 0.25
AND current_location_t >= 0.75
AND close[t] <= H_t
```

最后一项排除对旧 high 的真正突破；等于旧 high 允许。所有比较符号按字面冻结。

按 `(entry_time, decision bar position)` 升序扫描：空仓时接受；已有已接受事件时，所有 `candidate.entry_time <= active.exit_time` 均忽略且不补位；只有严格晚于旧 exit open 的候选才能成为下一笔。这样 exit bar 只发 `target=0`，不会要求策略接口在同一 closed-bar 决策中先平再重开。接受后固定占用 `[entry_time, exit_time]` 的日程边界，不依赖成交回报或未来 bar；无额外 cooldown、stop、take-profit、trail 或动态退出。无法在 discovery end 前完整退出的事件排除。

## 5. 执行、成本与权益

- 初始现金 `10,000 USDT`；spot long/cash，无杠杆、借币或 short。
- `Sizing.ON_ENTRY`：研究执行规格冻结为 `MarketSpec(inst_id="DOGE-USDT", market_type="spot", lot_size=0, min_notional=0)`、`dust_fraction=0`。`quantity = 0.25 * equity_immediately_before_entry / entry_reference_open`，不按 slippage-adjusted fill price反推数量；25% 仓位不会触发现金 affordability cap。持有期间数量固定，不再平衡。
- Main 每边：10 bps fee + 5 bps adverse slippage。
- Stress 每边：10 bps fee + 15 bps adverse slippage。
- 买入成交价 `open*(1+slippage)`；卖出成交价 `open*(1-slippage)`；fee 按实际成交 notional 双边收取。
- 每个 1h close MTM；在 entry bar 先按 open 买入再按该 bar close 标记，在 exit bar 先按 open 卖出并保持现金；协议禁止同一 open 退出后重入。
- 对 discovery 每个 UTC 日期生成一个日末 equity，取该日 `23:00` open bar 闭合后的值；首日 `r=E_day/10000-1`，以后 `r=E_day/E_prev_day-1`。没有 fill 但仍持仓的日期保留真实 MTM return；只有 equity 未变化的日期才是零收益。Discovery 日历完整，因此不做缺日填补。
- Sharpe=`mean(daily)/std(daily,ddof=1)*sqrt(365)`，risk-free rate=0；零方差记 0。MaxDD 在含初始 10,000 点及之后每个逐时 close-equity 的路径上计算 `min(equity/running_max-1)`。
- `total_return=final_equity/10000-1`；`CAGR=(final_equity/10000)^(365/N_calendar_days)-1`，其中连续 discovery 的 `N_calendar_days` 是 `2021-01-01..2025-05-31` 共 1,612 日；若 final equity<=0，CAGR 记 `null`。
- Episode PnL/return 使用第8节定义；win rate=`count(episode_return>0)/episodes`，零收益计非赢；profit factor=`sum(positive USDT PnL)/abs(sum(negative USDT PnL))`，无负 PnL 且有正 PnL时为 `inf`，无正 PnL 时为 0。fills 必须恰为 `2*episodes`，最终 open position 必须为 false。
- 最长回撤：从逐时 equity 首次创下、随后进入水下的 peak 点，到第一次恢复 `equity>=该 peak` 的 bar close；未恢复则截至 discovery 最后一根 close。报告持续小时数和起止 UTC；若从未水下则为 0。
- 最佳1/3/5集中度=`这些 episode 的正 USDT PnL之和 / 全部正 USDT PnL之和`，只在分母>0时报告，否则为 `null`；排序及 tie rule 与静态抑制一致。

## 6. 单因素邻域

仅六个一次改一个标量的邻域，main 不得被替换：

| 名称 | 唯一改动 |
|---|---|
| `lookback18` | lookback `24 -> 18`；share 分母同步为18 |
| `lookback30` | lookback `24 -> 30`；share 分母同步为30 |
| `upper45` | minimum upper share `0.50 -> 0.45` |
| `upper55` | minimum upper share `0.50 -> 0.55` |
| `hold16` | hold `24h -> 16h` |
| `hold32` | hold `24h -> 32h` |

family trials 固定为 7。

## 7. 消融与符号反证

消融不参与晋级：

- `location_only`：只保留 `current_location>=0.75 AND close[t]<=H_t`。
- `occupancy_only`：只保留 upper/lower share 两项。
- `lower_acceptance_long`：对称地要求 lower share `>=0.50`、upper share `<=0.25`、current location `<=0.25` 且 `close[t]>=L_t`，仍机械做多；用于检验上沿方向性。

G7 要求 main 平均净 episode return 严格高于 `location_only` 与 `occupancy_only`，且 main Sharpe 严格高于 `lower_acceptance_long`；任一消融为零 episode 或日收益零方差时，G7 直接 `FAIL`。

## 8. Calendar、集中度、bootstrap 与随机零假设

五个现金冷启动段：2021、2022、2023、2024、`2025-01-01..2025-06-01`。更早 bar 只可 warm up；段首现金且无继承持仓，段末不能完整退出的事件排除。

静态抑制最佳 1、3、5 个 episode：先按原 main 运行中每笔 `exit 后现金 - entry 前现金` 的 USDT 净 PnL 从高到低排序，同 PnL 按 entry_time 早者优先；冻结要删除的 entry_time 集合后，从 10,000 现金按原已接受日程重放并跳过这些事件。下游数量可因复利变化，但不重新排名，也不允许被原事件阻塞的候选补位。

Bootstrap 与 matched-random 的冻结运行时为 `NumPy==2.4.6`；其他 NumPy 版本不得用于生成权威 Monte Carlo 报告。Bootstrap 输入为主版本按时间升序、含零事件日的 UTC 日收益；28 日 circular moving blocks。初始化 `rng=numpy.random.Generator(numpy.random.PCG64(20260810))` 后只调用一次 `rng.integers(0,N,size=(10000,ceil(N/28)),endpoint=False,dtype=numpy.int64)`；矩阵第 i 行依次给出 replicate i 的全部 block 起点。每块按 circular wrap 取连续28日，按矩阵列序串联后截断到前 N 日；统计复合收益 `prod(1+r)-1`；用 `numpy.quantile(..., method="linear")` 计算 P5/median/P95；正收益概率为严格 `return>0` 的样本占比。G1 保证 N 足够；若 N<28 则 `INVALID`。

五个 calendar segment 均为半开区间 `[year-01-01T00:00Z, next_boundary)`；每段以 10,000 现金、空仓、空日程独立扫描。`W_t` 可使用段前 discovery bars 预热，但只有 `entry_time>=segment_start AND exit_time<segment_end` 的事件可接受；跨边界事件排除且不占用段内日程。G1 逐段计数和 G4 收益均来自这五次独立扫描，不从全 discovery 日程切片。

匹配随机入场候选集是每个 calendar segment 中所有满足 `volume[t-24:t+1]>0`、`entry_time>=segment_start`、`exit_time<segment_end`、`volume[t+1]>0` 和 `volume[t+25]>0` 的逐小时 entry；切片按 Python 半开语义，即 `t-24..t` 共25根已知 bar。各 stratum 内按 `(entry_time, decision_index)` 升序冻结。stratum 固定按 `(五段在协议中的序号, UTC hour 0..23)` 字典序处理；需求为0的 stratum 跳过且不消耗随机数。初始化独立 `rng=numpy.random.Generator(numpy.random.PCG64(20260811))`。每次尝试对每个非空 stratum 恰调用一次 `rng.choice(candidate_count,size=required_count,replace=False,shuffle=False)`，返回位置映射到已排序候选；处理完全部 stratum 后合并并按 `(entry_time,decision_index)` 排序。若任意相邻 entry_time 差 `<=24h`，丢弃整份并用不重置的连续 PRNG 流开始下一完整尝试。计划之间允许复用时点。最多尝试 1,000,000 份以得到 10,000 个有效计划；不足即 G8 `FAIL` 并报告实际有效数。每份有效计划按 main 成本、25% ON_ENTRY sizing、10,000 现金和对应段独立冷启动重放，五段终值相对五份初始现金的等权统计量冻结为 `mean(segment_final_equity/10000)-1`；observed 使用 main 的同一统计量：

```text
p_raw   = (1 + count(random_return >= observed_return)) / 10001
p_sidak = 1 - (1 - p_raw) ** 7
```

所有 variant/ablation 各自从自己的 raw signal 集独立执行完整不重叠扫描；不能沿用 main 日程。`net episode return` 冻结为 `(exit_after_fee_cash-entry_before_cash)/entry_before_cash`，即整账户 episode 净收益，不按25%已分配名义重新缩放。

## 9. 冻结门与短路

- `G0 Integrity`：数据、指纹、半开查询、因果时序、成本、spot target、零量与 holdout 非访问全部通过，否则 `INVALID`。
- `G1 Capacity`：连续 discovery main 日程的完整 episode `>=200`，且五次独立冷启动扫描各 `>=20`。失败即 `DISCOVERY_FAIL`，后续昂贵项全部 `NOT_RUN`。
- `G2 Main economics`：总收益 `>0`、日 Sharpe `>=0.60`、signed MaxDD `>=-20%`。失败即 `DISCOVERY_FAIL`，stress/neighbors/ablations/bootstrap/random 全部 `NOT_RUN`。
- `G3 Stress/outliers`：stress 总收益 `>0`；抑制最佳1与最佳3后总收益均 `>0`。
- `G4 Calendar`：至少4/5冷启动段总收益 `>0`。
- `G5 Bootstrap`：复合收益 P5 `>0`。
- `G6 Neighborhood`：main+6邻域至少5/7总收益 `>0`。
- `G7 Mechanism`：满足第7节三项严格比较。
- `G8 Matched random`：`p_sidak<=0.10`。

G0–G8 全过才记 `DISCOVERY_PASS`；通过也只形成固定 forward shadow hypothesis，不读取 holdout、不批准资金。任何实际运行的 main、stress、邻域、消融或随机计划若触发第2节 `INVALID` 条件，整个研究最终状态均为 `INVALID`，不能把该 variant 只计作 G6/G7/G8 failure。G1 通过后无论 G2 是否通过，都计算同成本口径的 25% buy-and-hold（段首第一根可成交 open 买入、段末最后一根 open 卖出）作为风险/方向基准；`location_only` 是最小信号基线并仅在 G2 通过后随机制消融运行。基准不参与晋级门。

## 10. 输出

- 机器报告：`reports/research/ura_v1.json`
- 人工报告：`docs/research/doge-intraday/UPPER_RANGE_ACCEPTANCE_RESULTS_2026-08-10.md`

报告必须含：协议路径、数据指纹/计数/零量、holdout_accessed=false、参数/成本、main schedule、逐时权益摘要、全部已运行指标、每个 gate 及 `NOT_RUN` 项、实现测试与版本状态。

## 11. 限制

- 1h close 的时间占用不是逐笔 volume profile，也不能证明真实限价单接受。
- 上沿占用可能只是被重新表达的慢动量；消融只能反证增量，不能证明因果。
- last-trade OHLC 和固定滑点不含盘口深度、部分成交和冲击尾部。
- DOGE 历史已被反复研究；即使 discovery pass，也不是 pristine OOS。
- main 失败后不得提升消融、对称反证或邻域为新主策略。
