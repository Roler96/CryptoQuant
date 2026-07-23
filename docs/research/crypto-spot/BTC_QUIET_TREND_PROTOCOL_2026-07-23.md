# BTC 安静趋势协议 (BQT v1, 2026-07-23)

## 研究问题

BTC 的中期正动量如果同时处在较低的下行半波动状态，可能代表有序的风险承接；反之，
下行半波动进入自身高分位通常对应去杠杆、流动性冲击或趋势破坏。BQT v1 检验低下行风险
是否能给普通 BTC 时间序列动量增加信息。

本轮只读取和交易 `BTC-USDT` 现货，不使用 ETH、DOGE、swap、funding、OI、成交量或旧
策略信号。

## 数据边界

- 探索窗口：`2021-01-01 00:00 UTC <= ts < 2025-06-01 00:00 UTC`；
- 数据库查询在 `2025-06-01` 排他硬截止；
- 1d bar 只由完整的 1h bar UTC 聚合；
- discovery 运行前不访问验证窗；
- 若任一发现门失败，BQT v1 永久停止，不读验证窗、不从邻域挑替补、不调参数；
- 只有 discovery 全部门通过，才允许冻结实现后登记一次
  `2025-06-01 .. 2027-06-01` holdout 访问。该窗口在 `2026-07` 以前的部分已被旧研究
  看过，只能算 robustness，不能称真正未见 OOS。

## 冻结主版本

对每根闭合 UTC 日线：

1. `momentum = log(close[t] / close[t-90])`；
2. 对任意连续 20 个日收益，定义
   `downside = sqrt(mean(min(log_return, 0)^2))`；
3. 用当前窗口之前连续 252 个同口径 downside 值作为因果基线；
4. 空仓时，若 `momentum > 0` 且当前 downside 不高于历史 35% 分位，目标变为
   100% BTC；
5. 持仓时，若 `momentum <= 0` 或当前 downside 不低于历史 65% 分位，目标变为 0%；
6. 35%/65% 迟滞区间内保持原目标；
7. 当前日线 close 决策，下一根日线 open 成交；
8. long/cash，不借币、不加杠杆，`Sizing.ON_ENTRY`；
9. 主成本每边 15 bps（fee 10 + slippage 5），压力每边 25 bps。

基线严格排除当前 downside。主版本 warmup 为
`downside_window 20 + baseline 252 + 1 = 273` 根日线。

## 冻结家族

登记 7 个可交易版本，Sidak 校正次数固定为 7：

| 名称 | momentum | downside window | entry/exit quantile |
|---|---:|---:|---:|
| main | 90d | 20d | 0.35 / 0.65 |
| momentum_fast | 60d | 20d | 0.35 / 0.65 |
| momentum_slow | 120d | 20d | 0.35 / 0.65 |
| risk_fast | 90d | 15d | 0.35 / 0.65 |
| risk_slow | 90d | 30d | 0.35 / 0.65 |
| hysteresis_tight | 90d | 20d | 0.25 / 0.55 |
| hysteresis_loose | 90d | 20d | 0.45 / 0.75 |

邻域只用于参数平原判断，不能替换主版本。

两个机制消融不计入可交易家族，也不能晋级：

- `momentum_only`：只按 90d momentum 正负进出；
- `quiet_only`：保留 35%/65% downside 迟滞，但不要求 momentum。

基准为相同窗口和成本的 BTC buy-and-hold。

## 冻结发现门

主版本必须同时满足：

1. 15 bps/边净收益为正；
2. 年化 Sharpe `>= 0.75`；
3. MaxDD `<= 35%`；
4. 至少 8 笔闭合交易；
5. 2021、2022、2023、2024、2025 YTD 冷启动切片中至少 3 段为正；
6. 25 bps/边压力收益为正；
7. 静态扣除最佳闭合交易 P&L 后收益仍为正；
8. episode bootstrap P5 `> 0`；
9. 6 个冻结邻域中至少 5 个盈利；
10. 相比 BTC buy-and-hold，MaxDD 至少降低 25%（相对比例）；
11. 主版本 Sharpe 高于 `momentum_only`，且 MaxDD 不高于它；
12. 主版本 Sharpe 高于 `quiet_only`；
13. 按实际入场年份和持有日数匹配的随机 BTC 入场，7 次家族
    Sidak-adjusted 单侧 `p <= 0.10`。

任一门失败均记 `DISCOVERY FAIL`。即使某个邻域、消融或主版本标题收益很高，也不允许
修改发现门或事后扶正。

## 预先声明的局限

- BTC 历史仍只有约 4.4 年，滚动风险分位不是独立样本；
- 波动状态可能只是趋势信号的滞后函数，消融门专门检验其增量；
- 日线 OHLCV 不包含真实盘口冲击、税务和容量；
- 旧研究已看过同一价格路径，discovery 只能生成候选，不能批准真实资金。
