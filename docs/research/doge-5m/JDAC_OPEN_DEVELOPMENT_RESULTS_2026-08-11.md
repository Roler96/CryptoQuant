# JDAC v1 — DOGE 5m 开放开发结果

日期：2026-08-11
状态：`DEVELOPMENT_FAIL — NO HOLD SCAN / NO SHARED-ENGINE PROMOTION`

## 结论

DOGE 5m 数据不支持“统计跳跃在短确认窗保留后继续沿跳跃方向运行”这一 JDAC v1 表达。

结构扫描的 24 个预定义组合全部亏损、Sharpe 全部为负，且 long/short 两侧在每个组合中都亏损。最好的单笔净均值仍为 -39.58 bps；扣回 30 bps 往返成本后，毛均值仍为 -9.58 bps。因此失败不是交易成本单独造成，也不是某一个方向或参数点造成。

按机制设计中的顺序短路规则，不运行持有期扫描，不选择 plateau center，也不晋级共享引擎验证。

## 机制

- 标的：`DOGE-USDT-SWAP`
- 周期：原生 5m
- 输入：DOGE 自身标准 OHLCV；`dvol=close*volume`
- jump 尺度：历史 12h/24h 收益的 bipower variation
- jump 门：`zJ ∈ {4,5,6}`、实体/区间 ≥ 0.60、成交额 ≥ 历史中位数 2 倍
- 确认：等待 2/3 根 bar，保留率 ≥ 0.60/0.80
- 方向：确认后顺 jump
- 执行：决策后下一根 5m open 入场，固定 24 bars 后 next-open 平仓
- 仓位：25% target weight
- 成本：15 bps/side

完整结构网格：

`n ∈ {144,288} × z ∈ {4,5,6} × d ∈ {2,3} × rho ∈ {0.6,0.8}`，共 24 次 trial。

数据区间为 2021-01-01 至 2026-08-11，共 589,930 根连续 5m bar。该历史已用于开放研究，不是 OOS 或独立确认数据。

## 结果摘要

| 指标 | 结果 |
|---|---:|
| Trials | 24 |
| Episodes 范围 | 485–1,650 |
| 正收益配置 | 0 / 24 |
| 正 Sharpe 配置 | 0 / 24 |
| 毛均值为正配置 | 0 / 24 |
| Long/short 同时亏损配置 | 24 / 24 |
| 六个自然年全正配置 | 0 / 24 |
| 最佳 Sharpe | -1.109 |
| 最佳 Return | -45.95% |
| 最佳单笔净均值 | -39.58 bps |
| 对应毛均值 | -9.58 bps |

### 按 Sharpe 排名最高的配置

`n=144, z=6, d=2, rho=0.8, H=24`

- Episodes：505（long 286 / short 219）
- Return：-45.95%
- Sharpe：-1.109
- MaxDD：-48.90%
- 胜率：30.50%
- Profit Factor：0.604
- 单笔净均值：-46.92 bps
- 六个自然年收益全部为负

### 单笔净均值最高的配置

`n=288, z=5, d=3, rho=0.6, H=24`

- Episodes：865（long 501 / short 364）
- 单笔净均值：-39.58 bps
- 扣回成本后的毛均值：-9.58 bps
- Return：-58.77%
- Sharpe：-1.639
- MaxDD：-59.16%
- long aggregate PnL：-40.46%
- short aggregate PnL：-45.12%
- 六个自然年收益全部为负

## 机制预测审计

1. 提高保留率没有产生预期的质量改善。
   - `rho=0.6`：平均 989.8 episodes，平均净均值 -49.21 bps
   - `rho=0.8`：平均 955.6 episodes，平均净均值 -48.15 bps
   - 更严格确认只带来很小变化，没有把 expectancy 推向正值。

2. 失败不是单一方向暴露。
   - 24/24 配置的 long aggregate PnL 与 short aggregate PnL 均为负。

3. 失败不是成本边际。
   - 24/24 配置即使返还全部 30 bps 往返成本，单笔毛均值仍为负。

4. 不存在可进入第二阶段的参数平台。
   - 所有结构点均显著为负，因此扫描 `H ∈ {12,24,48}`只会在已失败结构上继续搜索退出，不符合预定义晋级顺序。

## 裁决

`JDAC v1 = DEVELOPMENT_FAIL`

被否决的是当前精确定义：BV jump + 成交额/实体门 + 10–15m 保留确认 + 1–4h 顺势持有。结果不证明所有 jump-diffusion 思想永久无效，但它足以停止该规格，不做事后反向、long-only、阈值放宽或持有期救援。

## 产物

- `cq/research/jump_diffusion.py`
- `tests/test_jump_diffusion_research.py`
- `scripts/research_doge_jdac.py`
- `reports/research/doge_jdac_open_development_v1.json`
