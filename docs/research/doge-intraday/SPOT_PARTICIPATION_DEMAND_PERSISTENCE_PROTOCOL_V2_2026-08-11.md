# SPDP v2 Mode-A 修订协议

- 冻结日期：2026-08-11
- 研究标签：`doge-spot-participation-demand-persistence-v2`
- 状态：`FROZEN BEFORE SIGNAL COUNT OR RETURN INSPECTION`
- 基础协议：`SPOT_PARTICIPATION_DEMAND_PERSISTENCE_PROTOCOL_2026-08-11.md`
- v1 Mode-A SHA-256：`1eac7bb5b7fc033643e44b38c05e547dfb497d68d99f91f17b6c7ee2164ca946`
- v1 裁决：`NOT-FIT / NEVER EXECUTE`
- v2 机器报告：`reports/research/spdp_v2.json`

SPDP v2 的完整规范由不可变 v1 基础协议加本文件组成。本文件仅修复 v1 Mode-A 审核列出的确定性与接口缺陷；本文件覆盖基础协议中的冲突。机制、主参数、成本、邻域、消融和 G0–G8 门槛均不变。

## 1. quote_volume 策略接口与 provenance

禁止预计算并注入 decision map。必须从基础协议第2节验证且严格对齐的两腿原始行构造两个只读辅助 `Series`，通过 `run_backtest(..., aux=[spot_qv_series, swap_qv_series])` 交给现有 `Context`：

```text
spot_qv_series.key = ("DOGE-USDT-QV", "1h")
swap_qv_series.key = ("DOGE-USDT-SWAP-QV", "1h")
```

对原始腿每个位置 `i`：

```text
ts[i]     = raw_ts[i]
open[i]   = raw_quote_volume[i]
high[i]   = raw_quote_volume[i]
low[i]    = raw_quote_volume[i]
close[i]  = raw_quote_volume[i]
volume[i] = raw_volume[i]
```

不得标准化、填补、平滑、移位或删除。策略只可通过以下接口读取成交额和成交量：

```text
ctx.market("DOGE-USDT-QV", "1h").close(n)
ctx.market("DOGE-USDT-QV", "1h").volume(n)
ctx.market("DOGE-USDT-SWAP-QV", "1h").close(n)
ctx.market("DOGE-USDT-SWAP-QV", "1h").volume(n)
```

`Context` 依据 close time 对齐；同为原生1h时，decision bar `t` 只能看到辅助位置 `<=t`。

两个辅助 Series 必须使用现有 `cq.context.series_fingerprint()`。其 `(inst_id,timeframe,fingerprint)` 必须逐项出现在 `RunManifest.aux_fingerprints`，顺序固定为 spot-QV、swap-QV。报告同时保留基础协议中的两腿原始行 SHA-256。G0 合成测试和真实 run 都必须断言 aux keys、顺序和 manifest fingerprints 完全一致。

## 2. Calendar cold-start 最早决策

段前 bars 只允许计算指标，不允许生成 intent。对 segment `[start,end)`：

```text
decision_bar.ts >= start
entry_time        = decision_bar.ts + 1h >= start + 1h
exit_time         < end
```

段前最后一根 bar 即使在 `start` 时刻闭合，也不得产生 `start` open 入场。每段最早 decision bar open 为 `start`，最早 entry open 为 `start+1h`。策略在 `decision_bar.ts < start` 时必须返回 flat；测试必须证明评价起点前不存在排队 intent 或继承 hold state。

## 3. INVALID 传播与短路

任何已获准构建或执行的对象只要违反数据、辅助序列、entry/exit 退化bar、schedule、engine、最终flat或指标有限性契约，整个 SPDP v2 立即终止为 `INVALID`，不是对应 gate 的普通 FAIL：

- continuous main 或任一 cold-start schedule 在 G0/G1 阶段 INVALID：整个研究 INVALID，G1–G8 `NOT_RUN`；
- G1 PASS 后真实 main execution/parity INVALID：整个研究 INVALID，G2–G8 `NOT_RUN`；
- stress、静态抑制、任一 neighborhood、任一 ablation、bootstrap 或 matched-random 在获准阶段 INVALID：整个研究 INVALID；当前 gate 及所有后续 gate `NOT_RUN`；
- 未获准运行的对象不做 INVALID 判断，保持 `NOT_RUN`。

不得把 INVALID neighborhood 计作 G6 的负成员，不得把 INVALID ablation 计作 G7 FAIL，也不得删除触发 INVALID 的事件后继续。

## 4. Matched-random 全序与候选不足

stratum 唯一全序：先按基础协议第7节五个 segment 的序号 `0,1,2,3,4`，再按 UTC entry hour `0,1,...,23`，即 `(segment_order,utc_hour)` 字典序。每个 stratum 内候选按 `(entry_time,decision_index)` 升序。

初始化 PCG64 或调用任何随机 API 前，先确定所有非空需求 stratum。若任一 `candidate_count < required_count`，立即令 `G8=FAIL`，报告该 stratum，随机调用次数为0、有效计划为0，不重试。

只有全部充足才初始化 `PCG64(20260812)` 并按上述全序处理；需求为0的 stratum 跳过且不调用 RNG。每份计划失败后沿同一连续随机流开始下一份，不重置 seed。

## 5. CAGR 与最长回撤

对评价半开区间 `[evaluation_start,evaluation_end)`：

```text
calendar_days = (evaluation_end - evaluation_start) / 86_400_000
CAGR = (final_equity / 10000) ** (365.0 / calendar_days) - 1
```

仅当 `final_equity>0 AND calendar_days>0` 时计算，否则为 null。

最长回撤使用 equity 序列：初始点 `E[0]=10000`，timestamp 为评价区间第一根 bar 的 open；之后每个 `E[k]` 是第 `k-1` 根评价 bar 的 close-equity，timestamp 为该 bar open+1h。`running_max[k]=max(E[0:k+1])`。

当 `E[k]<running_max[k]` 且没有 active drawdown 时，drawdown start 为 `k-1` 的 equity timestamp；当首次 `E[k]>=` active peak 时恢复，end 为 `k` timestamp。样本结束仍未恢复时，end 为最后 equity timestamp。duration=`(end-start)/1h`。仅以 `duration>` 更新最长区间，因此并列保留最早开始、最早结束的区间；从未水下则 duration=0、start/end=null。

## 6. G0/G1 与真实收益边界

G0 的 schedule↔engine parity 仅在完全合成、无真实候选数据的测试面板执行：

- 至少800根连续1h bars；
- 人为设置一个恰好满足 main 的 decision bar；
- 更改其未来 bar 不改变信号；
- 期望 entry=`t+1`、exit=`t+49`；
- engine fills 恰为这两个 open；
- aux manifest 按第1节绑定；
- 最终 flat。

G0 不在真实 discovery schedule 调用引擎，不产生真实候选收益。

真实 discovery 顺序冻结为：

1. 只加载/验证真实数据，因果构建 continuous main 与五个 cold-start schedules；
2. 只统计 G1 episode 数；不调用真实引擎、不读取收益；
3. G1 FAIL：立即 `DISCOVERY_FAIL`，G2–G8 `NOT_RUN`；
4. G1 PASS：第一次调用真实引擎运行 main；先核对 rejections、fill timestamps、fills=`2*episodes`、manifest和最终flat；任一不符按第3节 INVALID；
5. parity通过后才从同一次 `RunResult` 读取 G2 指标。引擎内部同步形成但在 parity 通过前未读取的 equity 不构成提前裁决。

## 7. 确定性 condition funnel

必须分别报告 continuous main 和五个 cold-start segment 的 funnel。每个 funnel 从评价范围内满足第2节 decision 边界且允许完整48h退出的 decision index 开始。以下均为前一层幸存集合上的累计计数，顺序固定：

1. `eligible_decisions`：满足最早 `t=742`、segment decision边界、entry/exit边界；
2. `positive_signal_window`：两腿在闭区间位置 `[t-742,t]` 的 raw volume 和 quote_volume 全部严格 `>0`；
3. `positive_sigma`：基础协议第3节720个 return history 的 `std(ddof=1)>0`；
4. `share_level`：`current_share>=share_q75`；
5. `share_migration`：`current_share-prior_share>=0.03`；
6. `positive_impulse`：`R12>=1.50*sqrt(12)*sigma`，这就是 `raw_signals`；
7. `accepted_schedule`：在 raw signals 上按基础协议第4节阻塞规则接受的 episode 数。

`accepted_schedule<=raw_signals`；第1–6层必须单调不增。funnel 不检查未来 entry/exit bar 成交量；那是 accepted schedule 完成后的独立 INVALID 检查，避免未来成交量改变 raw signal或漏斗。

## 8. 消融共同条件

三个消融和 main/邻域都保留：数据对齐、`positive_signal_window`、`sigma>0`、评价边界及同一不重叠规则。

- `price_only` 只删除 `share_level` 与 `share_migration`；
- `share_level_only` 只删除 `share_migration`；
- `participation_only` 只删除 `positive_impulse`，仍要求 `sigma>0`。

以上定义覆盖基础协议中可能产生歧义的简写。
