# DOGE 单币种日内开放探索 v2：下跌冲击恢复候选

日期：2026-08-11
裁决：`DEVELOPMENT SURVIVOR — AWAITING FORWARD CONFIRMATION`
不是 OOS 结论，不进入实盘或资金阶段。

## 结论

本轮没有从旧失败策略中挑选候选，而是从五个新的 DOGE-only 日内状态机制开始开放探索：

1. quarter-hour impulse：整刻/刻钟算法参与突增后的延续或反转；
2. jump aftershock：单 bar 跳跃后的冲击传播或衰减；
3. compression release：低方差蓄积后的高成交释放；
4. liquidity vacuum：单位成交额价格位移异常后的修复或延续；
5. tail recovery：多 bar 尾部冲击出现首根部分恢复后的后续路径。

首轮 120 个变体没有完整家族直接晋级。tail-recovery 的方向分解产生了一个清晰的非对称发现：

- 下跌冲击出现恢复阳线后做多：多个持有期有正净期望；
- 上涨冲击出现回落阴线后做空：持续为负；
- 因而有效开发假设不是“双向尾部反转”，而是 **Downside-Shock Partial Recovery（DSPR）**：极端卖压后已经出现但尚未完成的恢复。

围绕该单侧机制运行 420 个 refinement 变体后，选出的平台中心通过共享引擎开发验证：主成本下 +29.20%、Sharpe 1.069、MaxDD -7.50%；25 bps/side 压力成本下仍为 +21.65%、Sharpe 0.834、MaxDD -7.78%。六个自然年冷启动收益全部为正。

但是完整历史已被多轮研究查看，本轮还搜索了 540 个变体。候选单独的 block-bootstrap 显著，但简单多重搜索修正不显著。因此目前只能称为开发 survivor，不能称为已确认 edge。

## 数据与执行

- 标的：`DOGE-USDT-SWAP`
- 数据：OKX 原生 5m OHLCV，仅 DOGE
- 区间：`[2021-01-01 00:00, 2026-08-11 08:50)`
- bar 数：589,930
- 数据 fingerprint：`e74eba06efed1125`
- 信号：5m bar 收盘后形成
- 入场：下一根 5m open
- 出场：固定持有后的 future open
- 仓位：25% target weight，long-only
- sizing：`ON_ENTRY`
- 主成本：10 bps fee + 5 bps slippage / side
- 压力成本：10 bps fee + 15 bps slippage / side
- funding：关闭；历史 funding 不覆盖完整研究区间
- BTC、ETH、跨币、订单簿、OI、funding 信号均未使用
- 数据状态：`untouched_holdout = false`

## 外部机制来源

外部资料只用于生成机制，不复制参数：

- Kończal & Połoczański（2026）在 1m 加密 ETP 中研究极端下跌、no-recovery 与 momentum-reversal anomaly，并指出短期波动和 drawdown 对异常预测较重要：<https://arxiv.org/abs/2608.09576>
- Kim & Hansen（2026）报告加密永续在 1m、5m、15m 整点存在算法参与、成交量和波动突增，支持独立检验 quarter-hour state：<https://arxiv.org/abs/2607.09426>
- Zwydak et al.（2026）使用收益、成交量、复杂度和相关结构识别交易异常，支持将价格—成交活动状态视为机制输入而非传统指标组合：<https://arxiv.org/abs/2607.13916>

## 第一阶段：五家族开放探索

参数结构：15 个信号变体 × 4 个持有期（30m/1h/2h/4h）× 2 个方向，共 120 trials。成本统一为 15 bps/side，信号后 next-open 成交，活跃仓位期间阻塞重叠入场。

| 家族 | 最佳变体 | Episodes | 净均值/笔 | Sharpe | 正收益年份 | 结论 |
|---|---|---:|---:|---:|---:|---|
| liquidity vacuum | ratio=12, inverse, 4h | 57 | -25.0 bps | -0.188 | 4/6 | 总体亏损，否决 |
| tail recovery | z=4.5, native, 2h | 782 | +2.1 bps | 0.121 | 3/6 | 整体不晋级，进入方向诊断 |
| jump aftershock | z=5, inverse, 1h | 1,422 | -10.4 bps | -0.399 | 1/6 | 否决 |
| compression release | ratio=.45, native, 4h | 874 | -20.8 bps | -0.911 | 1/6 | 否决 |
| quarter-hour impulse | qv=3, inverse, 4h | 4,563 | -24.1 bps | -2.019 | 0/6 | 否决 |

### tail-recovery 方向诊断

以 z=4.5 为例：

| Hold | 下跌冲击恢复后做多 | 上涨冲击回落后做空 |
|---:|---:|---:|
| 1h | +29.6 bps/笔，PF 1.41 | -58.3 bps/笔，PF 0.60 |
| 1.5h | +41.5 bps/笔，PF 1.55 | -60.7 bps/笔，PF 0.58 |
| 2h | +46.1 bps/笔，PF 1.56 | -42.5 bps/笔，PF 0.68 |
| 3h | +56.6 bps/笔，PF 1.59 | -49.4 bps/笔，PF 0.68 |

机制明显不对称，因此后续只开发“下跌冲击后的部分恢复做多”，不把亏损 short side 留在策略里。

## 第二阶段：DSPR 自适应 refinement

网格：

- shock window：2/3/4/6 根 5m bar
- shock z：3.5/4.0/4.5/5.0/5.5
- recovery floor：10%/20%/30%，ceiling 固定 80%
- hold：12/18/24/30/36/48/72 bars
- 共 420 trials

结果：

- 389/420 净均值为正；
- 88/420 至少五个自然年为正；
- 14/420 六个自然年全部为正；
- 选中候选周围 24 个局部邻域全部净均值为正；
- 其中 6/24 六年全正；
- 邻域净均值范围 +49.4 至 +99.2 bps/笔，中位数约 +63.2 bps/笔。

选取的平台中心不是最高收益长持有变体，而是短持有局部簇中心：

```text
shock_window = 4 bars (20m)
volatility_window = 2016 bars (7d, full warmup)
shock_z >= 5.5
current return > 0
recovery_fraction = current_return / abs(prior_4bar_return)
0.30 <= recovery_fraction <= 0.80
entry = next 5m open
hold = 12 bars (1h)
target_weight = 0.25
```

冲击窗口内所有 volume/quote_volume 必须严格为正。修正完整 7 日 warmup 与正成交量路径后重跑，选中候选结果未变化。

探索账本中的全仓位事件统计：

- 120 episodes
- 净均值 +87.35 bps/笔
- win rate 55.83%
- PF 2.288
- daily Sharpe 1.064
- MaxDD -12.22%
- 六个自然年全部为正

## 共享引擎开发验证

实现：`cq/research/downside_recovery.py`
引擎：`cq-engine/1`
共享账户路径：25% target、next-open、ON_ENTRY、完整成本、显式 time exit。

| 成本 | Return | Sharpe | MaxDD | Episodes | Win rate | PF | Best-5 正 PnL 占比 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 15 bps/side | +29.20% | 1.069 | -7.50% | 120 | 55.0% | 2.257 | 32.05% |
| 25 bps/side | +21.65% | 0.834 | -7.78% | 120 | 50.8% | 1.835 | 34.10% |

完整性：

- 240 fills
- 0 rejection
- 最终 flat
- 120 个 episodes 与向量事件账本一致

### 自然年冷启动（15 bps/side）

| Year | Return | Sharpe | MaxDD | Episodes | PF |
|---|---:|---:|---:|---:|---:|
| 2021 | +15.20% | 1.616 | -7.50% | 27 | 2.550 |
| 2022 | +1.19% | 0.484 | -2.94% | 22 | 1.305 |
| 2023 | +1.34% | 0.851 | -1.58% | 28 | 1.729 |
| 2024 | +5.20% | 1.525 | -2.32% | 20 | 2.903 |
| 2025 | +0.27% | 0.291 | -1.87% | 12 | 1.112 |
| 2026 partial | +3.68% | 2.199 | -0.49% | 11 | 8.971 |

六年收益方向一致，但 2025 的经济优势很薄，2025/2026 样本稀疏；2023、2025、2026 的年度 best-5 正 PnL 集中度也很高。全期集中度合格，年度切片不能单独证明稳定性。

## 统计稳健性与搜索惩罚

对 120 个净 episode return 使用 11-episode circular block、50,000 次 fixed-seed centered null bootstrap：

- observed mean：+87.35 bps/笔
- 单候选 `p(mean <= 0)`：0.00938
- percentile bootstrap 95% mean interval：约 +34.0 至 +157.5 bps/笔
- 对 420 个 refinement 做简单 Bonferroni：不显著（上限为 1）

解释：历史样本对这个冻结候选本身给出正证据，但不足以抵消完整自适应搜索的多重检验风险。不能用未经修正的 p 值把开发 survivor 升格为确认策略。

## 最终裁决

`DSPR v1 = DEVELOPMENT SURVIVOR — AWAITING FORWARD CONFIRMATION`

通过的内容：

- DOGE-only、因果、next-open；
- 真实 5m 数据；
- 主成本和高成本压力均为正；
- 共享引擎与事件账本一致；
- 六个自然年冷启动收益均为正；
- 参数邻域不是单点尖峰；
- 全期利润不集中在最佳少数交易。

尚未通过的内容：

- 没有未查看的历史 holdout；
- 搜索修正后统计证据不足；
- funding 未计入；
- 2025 优势很薄，近年 forward episode 数不足；
- 尚无冻结后的独立 forward events。

因此不部署、不实盘、不宣称“有效策略”。下一证据只能来自当前规格不再变更后的 forward observer；历史样本不再用于修改 DSPR v1。

## 产物

- `scripts/research_doge_intraday_frontier.py`：五家族 120 trials + DSPR 420 trials 完整 ledger
- `reports/research/doge_intraday_open_frontier_v2.json`：开放探索机器报告
- `cq/research/downside_recovery.py`：共享策略接口实现
- `scripts/run_doge_downside_recovery_validation.py`：共享引擎主/压力/年度 runner
- `reports/research/doge_downside_recovery_development_v1.json`：共享引擎机器报告
- `tests/test_doge_intraday_frontier.py`：前缀不变、next-open、重叠阻塞测试
- `tests/test_downside_recovery_research.py`：信号、零成交量、恢复边界、持有时序测试
- `docs/research/doge-5m/MICROSTRUCTURE_FIRST_PRINCIPLES_MECHANISMS_2026-08-11.md`：后续独立机制候选库（JDAC/PIRD/VCOS，尚未执行）
