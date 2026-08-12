# VCOS v1 — DOGE 5m 开放开发结果

日期：2026-08-12
状态：`DEVELOPMENT_FAIL — NO PLATEAU / NO HOLD SCAN / NO SHARED-ENGINE PROMOTION`

## 结论

DOGE 5m 数据不支持“成交量时钟上的连续同向订单流，在预期 UTC 时段容量扩张时继续运行”这一 VCOS v1 表达。

预先冻结的 12 个结构组合全部亏损、Sharpe 全部为负，long/short 两侧在每个组合中都亏损，六个自然年在每个组合中也全部为负。最好的单笔净均值为 -30.25 bps；返还 30 bps 往返成本后，毛均值仍为 -0.25 bps。因此结果不是可由更低成本挽救的边际候选。

提高容量扩张门从 1.10 到 1.25 在全部六组配对中都使单笔净均值进一步恶化，直接违背机制的预注册预测。按冻结的顺序短路规则，不选择 plateau center，不扫描 `D/H/相邻Q`，不执行候选消融或共享引擎晋级。

## 冻结机制与执行

- 标的：`DOGE-USDT-SWAP`
- 周期：OKX 原生 5m
- 输入：DOGE 自身标准 OHLCV；`dvol = close * volume`
- 时段季节性：当前 UTC 日之前 28 个完整 UTC 日，各 5m slot 的 `dvol` 中位数
- 成交量时钟：从决策 bar 向后构造两个相邻、整 bar、不重叠的等成交额桶
- 单桶最大跨度：72 bars（6h）
- 延续门：两桶同向，且各自 `|R|/RV >= z_vol`
- 单跳排除：两桶最大 `jump_share <= 0.75`
- 容量门：未来 1h 的历史 slot 容量 / 过去 1h 的历史 slot 容量 `>= gamma`
- 执行：决策收盘后的下一根 5m open 入场，持有 12 bars 后 future open 平仓
- 仓位：25% target weight；long/short 对称
- 成本：15 bps/side
- 活跃持仓期间忽略新信号

数据区间为 2021-01-01 至 2026-08-11 08:45 UTC，共 589,930 根连续 5m bar；fingerprint 为 `e74eba06efed1125`。该历史是已见 research pool，不是 OOS 或独立确认数据。

结构网格：

```text
D = 28 days（固定）
H = 12 bars（固定）
Q in {6, 12, 24}
z_vol in {0.60, 0.80}
gamma in {1.10, 1.25}
```

共 12 个 trial。只有出现相邻通过点时，才允许围绕 plateau center 扫描 `D in {14,28}`、`H in {6,12,24}` 和相邻 `Q`。

## 结果摘要

| 指标 | 结果 |
|---|---:|
| 结构 trials | 12 |
| Episodes 范围 | 679–3,380 |
| 正收益配置 | 0 / 12 |
| 正 Sharpe 配置 | 0 / 12 |
| 毛均值为正配置 | 0 / 12 |
| Long/short 同时亏损配置 | 12 / 12 |
| 六个自然年全部为负配置 | 12 / 12 |
| 最佳 Sharpe | -2.802 |
| 最佳 Return | -42.77% |
| 最佳单笔净均值 | -30.25 bps |
| 对应毛均值 | -0.25 bps |

### 按 Sharpe / Return 最不差的配置

`Q=6, z_vol=0.80, gamma=1.25, D=28, H=12`

- Episodes：679（long 369 / short 310）
- Return：-42.77%
- Sharpe：-2.802
- MaxDD：-43.12%
- 胜率：26.80%
- Profit factor：0.396
- 单笔净均值：-32.71 bps
- 单笔毛均值：-2.71 bps
- long aggregate PnL：-37.36%
- short aggregate PnL：-18.16%
- 2021–2026 partial 六个自然年全部为负

### 单笔均值最不差的配置

`Q=6, z_vol=0.60, gamma=1.10, D=28, H=12`

- Episodes：2,663
- 单笔净均值：-30.25 bps
- 单笔毛均值：-0.25 bps
- Return：-86.77%
- Sharpe：-6.393
- MaxDD：-86.79%
- long aggregate PnL：-113.58%
- short aggregate PnL：-87.80%
- 六个自然年全部为负

## 机制预测审计

1. **容量扩张门没有提升交易质量。**
   - 在相同 `Q/z_vol` 下把 `gamma` 从 1.10 提高到 1.25，共六个成对比较；6/6 的单笔净均值都恶化。
   - 更严格容量门确实减少事件，但没有改善 gross 或 net expectancy。

2. **更高路径一致性没有形成稳定改善。**
   - `z_vol=0.80` 相对 0.60 的六个配对中只有两个单笔均值改善，其余四个恶化。
   - 没有随路径一致性单调增强的 continuation 证据。

3. **失败不是单一方向或单一年份造成。**
   - 12/12 配置的 long aggregate PnL 和 short aggregate PnL 均为负。
   - 12/12 配置在六个自然年切片中均为 0 个正收益年份。

4. **失败不只是 30 bps 往返成本。**
   - 所有配置返还全部交易成本后的单笔毛均值仍为负，范围约 -11.27 至 -0.25 bps。

5. **不存在可进入第二阶段的平台。**
   - 结构点没有一个通过最低经济门，更不可能形成相邻通过点。
   - 按预定义研究顺序，停止 `D/H/相邻Q` 扫描，避免在已失败结构上搜索退出或反向参数。

## 裁决

`VCOS v1 = DEVELOPMENT_FAIL`

被否决的是当前精确定义：过去 28 个完整 UTC 日的 slot 季节性 + 两个整 bar 等成交额桶 + 非单跳同向路径 + 未来 1h 容量扩张门 + 1h 顺势持有。

结果不支持事后反向交易、放松 jump-share、改持有期或改用单侧方向救援；这些都不是冻结 VCOS v1 的确认步骤。至此，2026-08-11 三机制设计中的 JDAC、双向 PIRD 与 VCOS 均按各自规格完成；只有由开放方向诊断产生的独立后代 PIRD-L 留作冻结后的 forward observer 候选。

## 产物

- `cq/research/volume_clock.py`
- `tests/test_volume_clock_research.py`
- `tests/test_doge_vcos_research.py`
- `scripts/research_doge_vcos.py`
- `reports/research/doge_vcos_open_development_v1.json`
