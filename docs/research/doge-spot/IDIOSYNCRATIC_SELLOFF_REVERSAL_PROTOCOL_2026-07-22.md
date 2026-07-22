# DOGE 特异性卖压反转冻结协议（ISR v1）

冻结时间：`2026-07-22 09:00 UTC`（在运行本候选的任何信号、收益或参数结果之前）。

## 研究问题

检验 DOGE 在 BTC 与 ETH 并未同步下跌时出现的极端相对卖压，若最后一小时已经转正，
是否存在随后 12 小时的短期流动性反转。经济解释是：非市场性卖单短时耗尽 DOGE 盘口，
流动性提供者承担库存后获得反转补偿；它不是“BTC/ETH 上涨后 DOGE 补涨”的 DLC 假设。

已有大样本研究发现，小币种的短期横截面反转与流动性有关，但同时指出最大、最可交易的
币反而可能呈动量。该证据只提供可证伪机制，不保证 DOGE 或本时域有效：

- Zaremba et al., *Up or down? Short-term reversal, momentum, and liquidity
  effects in cryptocurrency markets*：https://doi.org/10.1016/j.irfa.2021.101908
- Nakagawa & Sakemoto, *New behaviorally-based cross-sectional reversal
  portfolios in the cryptocurrency market and market uncertainty*：
  https://doi.org/10.1016/j.frl.2025.107800

## 与已研究机制的区分

- DLC 要求 BTC 与 ETH 同时处于各自90%上行冲击，再买尚未跟随的 DOGE；ISR 明确要求
  当前 BTC/ETH 组合6h收益非负，但触发变量是 DOGE 相对市场残差自身的下方5%尾部。
- OIFR 使用 forward OI 与 realized funding；ISR 完全不读取衍生品流数据。
- DVR/VCSE/事件几何使用 DOGE 自身方向方差、突破/量价或跳跃形态；ISR 的核心状态是
  同时刻三币横截面残差。
- 本轮不把 DLC 的 `already_led` 符号对照转成策略，也不使用其领导币上行分位。

## 数据与严格顺序

- 数据：OKX `DOGE-USDT`、`BTC-USDT`、`ETH-USDT` spot 1h OHLCV；timestamp 必须逐点
  完全一致，不 forward-fill。
- Discovery 查询在数据库层排他硬截止 `2024-01-01 00:00 UTC`。
- 主版只有通过全部 discovery 门，才允许另写冻结 validation runner 并读取2024；2024
  通过才读取2025。主版失败则不读取后续年度，也不能从邻域或消融挑替代品。
- 仓库其他研究已经查看过这些年度的资产路径，因此后续只能称候选级顺序验证，不能称
  DOGE 资产层面 pristine OOS。
- 初始资金10,000 USDT，long/cash，不借币、不加杠杆；信号只读闭合1h bar，下一根
  1h open 成交；零成交量不成交。

## 冻结特征

记完整小时 bar `t` 的 close 为 `C_t`，小时对数收益为：

`d_i = log(DOGE_close_i / DOGE_close_{i-1})`

`m_i = (log(BTC_close_i / BTC_close_{i-1}) + log(ETH_close_i / ETH_close_{i-1})) / 2`。

当前6h冲击：

`D6_t = sum(d_i, i=t-5..t)`

`M6_t = sum(m_i, i=t-5..t)`。

当前事件前严格不重叠的90天校准窗包含2,160个小时收益
`i=t-2165..t-6`。在该窗口估计有截距等价的市场 beta：

`beta_t = cov(d_i, m_i) / var(m_i)`。

若市场方差为0或任一输入非有限，禁止信号。使用同一个 `beta_t` 对校准窗内所有完整6h
块计算重叠残差：

`e_j = sum(d_i, i=j-5..j) - beta_t * sum(m_i, i=j-5..j)`，

其中 `j=t-2160..t-6`，共2,155个值。尾部阈值固定为 NumPy
`quantile(e, 0.05, method="linear")`，记作 `Q05_t`。当前残差为：

`E6_t = D6_t - beta_t * M6_t`。

## 冻结状态机

空仓且冷却完成时，四项必须同时成立：

1. `E6_t < Q05_t`（DOGE 相对卖压处于自身因果5%尾部）；
2. `D6_t < 0`（DOGE 本身确实下跌，不只是少涨）；
3. `M6_t >= 0`（BTC/ETH 组合没有同步下跌）；
4. `d_t > 0`（最后一小时首次确认反转方向）。

触发后下一根1h open 将账户权益的25%买入 DOGE，固定持有12根完整小时 bar 后下一 open
退出。无止盈、止损或 trailing。退出后再冷却48h；因此 accepted decision 的最小间隔为
60h。持仓和冷却期间的新事件全部忽略，不延长持有。

主成本每边15bps（fee10 + slippage5），压力成本每边25bps。`Sizing.ON_ENTRY`，持有期
不逐小时再平衡。

## 冻结家族、邻域与消融

可交易 family 固定5个版本；只有主版可晋级，邻域只检查稳定性：

- 尾部分位：2.5%、10%；
- 固定持有：6h、24h。

两个不可晋级消融：

- `no_market_filter`：删除 `M6>=0`，其余不变；
- `plain_reversal`：删除残差尾部与市场方向，只保留 `D6<0`、`d_t>0`、相同持有/冷却。

不检验其他 beta 长度、3h/12h冲击、BTC-only、ETH-only、成交量、波动过滤、target、stop
或仓位。若结果失败，不修改残差符号。

## Discovery 晋级门（全部通过）

1. 15bps/边总收益 `>0`、Sharpe `>=0.50`、MaxDD `<=20%`；
2. 至少20笔闭合交易，2021–2023 至少两个冷启动自然年收益为正；
3. 25bps/边压力总收益 `>0`，静态删除最佳一笔闭合交易 PnL 后收益 `>0`；
4. episode bootstrap 10,000次、种子`20260722`的 P5 `>0`；
5. 四个冻结邻域的15bps总收益全部 `>0`；
6. 主版 Sharpe 与 mean episode 同时高于 `plain_reversal`；
7. 主版 mean episode 高于 `no_market_filter`；
8. 按入场年份、实际持有小时、25%仓位和相同成本匹配的10,000次随机入场检验，5个
   可交易版本 Sidak-adjusted 单侧 `p<=0.10`。

任一失败即 `DISCOVERY FAIL`：永久归档 ISR v1，不读取2024，不用唯一正邻域替换主版。

## 后续年度门

若 discovery 通过，2024 必须同时满足：15/25bps收益均正、Sharpe `>0`、至少5笔闭合
交易、去最佳一笔后不为负、匹配随机 raw `p<=0.20`。通过后2025使用相同门。任一年度
失败即永久归档，2026不能反向挽救。

## 预先声明的限制

- 只有 BTC/ETH/DOGE 三币，不是真正广泛横截面；市场因子只是两币等权代理；
- 同一 beta 应用于过去残差分布，保持当时可计算，但不能捕捉窗内 beta 漂移；
- 2,155个6h残差高度重叠，不能当作2,155个独立样本；最终证据以稀疏交易 episode、
  年度迁移、随机入场和成本压力为准；
- 论文所述大样本横截面反转可能集中于不易交易的小币；DOGE若表现为动量，本假设应失败；
- close 决策/next-open 模型没有盘口深度、部分成交或冲击容量，发现通过也最多是候选。
