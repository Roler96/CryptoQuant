# DOGE 持仓量挤压反转 forward 冻结协议（OIFR v1）

冻结时间：`2026-07-22 08:25 UTC`。冻结时只审计过 OI/funding 的覆盖、间隔和空值，
没有读取本公式在已有 32 天 OI 窗口上的信号数或任何未来收益。第一根允许决策的完整
post-freeze 小时 bar 为 `2026-07-22 09:00 .. 10:00 UTC`，因此
`FORWARD_START_DECISION = 2026-07-22 10:00 UTC`。

## 研究问题与机制边界

检验一种严格 forward-only 的去杠杆反转：当 DOGE 永续的价格归一化 OI 出现自身过去
30 天尾部级下降、DOGE 现货同期下跌、最近一次已实现 funding 为正（挤压前多头仍向空头
付款），但最后一小时现货已经转正时，是否存在随后 12 小时的短暂反转。

这不是“清算已被识别”的断言。OKX Rubik OI 是交易所按币种公布的 USD 序列，没有方向、
账户杠杆或逐笔强平身份。已有跨交易所逐笔研究还发现，部分 venue 的 OI 报送可能延迟或
彼此不合理。因此本版本只把**同一 OKX DOGE 序列的尾部变化**当作状态变量，不把数值解释
成全市场精确仓位，也不和其他交易所横向拼接：

- OKX API 文档：https://www.okx.com/docs-v5/en/
- Giagkiozis & Said, *Reconciling Open Interest with Traded Volume in Perpetual
  Swaps*：https://arxiv.org/abs/2310.14973
- He et al., *Fundamentals of Perpetual Futures*：
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4301150

文献只支持 OI/funding 是杠杆市场状态且数据口径需谨慎，不支持本公式必然有 alpha。

## 输入、可用性时间与不可回填规则

- 交易标的：OKX `DOGE-USDT` spot；只做 long/cash。
- 状态输入：OKX `DOGE` 1h OI USD、`DOGE-USDT-SWAP` 1h close、
  `DOGE-USDT` 1h close，以及 `DOGE-USDT-SWAP` 最近一次非空 `realizedRate`。
- OI、spot、swap 的小时 timestamp 都视为 bar open。时间为 `t` 的数据只有在 `t+1h`
  后才允许进入决策，即使 API 更早返回也不例外。
- 每小时观察器只处理当时刚结束的一个决策槽。标准捕获窗为整点后 10–30 分钟；早于
  10 分钟不落账，晚于 30 分钟记为 `missed_late`，不能用后来取得的数据补成信号。
- 输入不齐、非有限值、小时不连续、最新 funding 过旧或 realized rate 为空时，落账为
  `data_unavailable`。以后数据被 OKX 修订，也不得改写这条记录。
- 每个决策的状态、特征、源窗口摘要与输入摘要哈希进入 append-only SQLite 账本；同一
  `(study, record_type, decision_time)` 只允许完全相同的幂等重放，冲突写入必须报错。
- 冻结前数据只可充当因果 warm-up。禁止计算、展示或利用
  `decision_time < 2026-07-22 10:00 UTC` 的策略信号和收益。

这些规则优先于“尽量多拿样本”：漏跑就是漏跑，不制造伪 forward 记录。

## 冻结特征

令 `d=t+1h` 为决策时间，`P^swap_t` 为 DOGE swap 小时 close，`OIUSD_t` 为同 timestamp
的 OI USD。为消除 USD OI 随价格机械变化的一阶影响，定义近似基础币持仓量：

`N_t = OIUSD_t / P^swap_t`。

当前 6 小时 OI 变化与现货收益为：

`O6_t = log(N_t / N_{t-6})`

`R6_t = log(P^spot_t / P^spot_{t-6})`

`R1_t = log(P^spot_t / P^spot_{t-1})`。

尾部阈值使用严格早于当前值的 720 个小时变化：

`Q05_t = linear_quantile_0.05(O6_{t-720}, ..., O6_{t-1})`。

计算这些变化所需的 OI/swap 源窗口必须从 `t-726` 到 `t` 每小时连续。分位数固定为
NumPy `method="linear"` 口径，禁止 winsorize、插值缺口或根据结果改 quantile。

`F_t` 是在 `d` 时观察器实际取得、settlement time 不晚于 `d` 的最近一次非空
`realizedRate`；其 settlement age 必须不超过 8 小时。预测 `fundingRate` 永不代替它。

## 冻结信号与纸面成交

四项同时成立才产生原始事件：

1. `O6_t < Q05_t`；
2. `R6_t < 0`；
3. `F_t > 0`；
4. `R1_t > 0`。

若事件通过冷却门，则成为 accepted signal：

- 上一 accepted decision 后，固定纸面持有到 `decision+13h`；
- 再冷却 48h；因此相邻 accepted decision 至少间隔 61h；
- signal 在 `d` 冻结，计划于 `d+1h` 的 spot open 买入账户权益的 10%；
- 自入场起观察 12 根完整 1h bar；任一 high 首次达到入场价的 110% 时按恰好 110%
  纸面止盈，否则在 `d+13h` 的 spot open 退出；
- 无止损、不借币、不加杠杆，其余 90% 保持 USDT；
- 主成本每边 15bps（fee 10 + slippage 5），压力成本每边 25bps；
- outcome 只能在所需价格 bar 完成至少 2h 后追加，允许晚结算但不得修改 signal。

这只是研究账本，不向交易所发送订单，也不声称 open/high 模型等同可成交盘口。

## 唯一版本与禁止动作

本轮 family size 固定为 1。forward 期间不运行 q01/q10、3h/12h OI、负 funding、
不同反转确认、不同 target/hold/cooldown、不同仓位或多币版本。不得查看已有 warm-up
窗口的假想收益；不得因事件太少降低阈值；不得因结果不佳重置 forward 起点。

若 OKX 改变 OI 字段定义、时间语义或 funding 制度，旧版停止并标记
`DATA_REGIME_TERMINATED`。任何新口径必须另建 v2 和新的 forward 起点，不能拼接。

## 数据成熟门槛与裁决

在以下条件全部满足前，状态只能是 `FORWARD INCONCLUSIVE`：

1. 从冻结起至少经过 365 个自然日；
2. 至少 60 笔已结算 accepted episodes；
3. 计划决策槽中至少 98% 有不可变 capture 记录，且其中至少 95% 为有效特征而非
   `data_unavailable`/`missed_late`；
4. 至少覆盖四个 UTC 自然季度，且至少三个季度有 accepted signal；
5. 源口径没有触发 `DATA_REGIME_TERMINATED`。

成熟后只作一次主裁决，全部通过才可进入 shadow-paper 候选：

- 15bps/边的 10%账户级总收益 `>0`，episode 平均净收益 `>0`；
- 25bps/边压力总收益 `>0`；
- 删除最佳一笔 episode 后的15bps总收益 `>0`；
- 以 accepted episode 为单位、固定随机种子的 circular block bootstrap，块长4笔、
  10,000次，平均 episode 净收益的单侧95%下界 `>0`；
- 任一自然季度贡献的正毛 PnL 不得超过全部正毛 PnL 的50%；
- signal、outcome 与账本复算零冲突。

任一成熟后门失败即永久 `REJECTED`，不滚动等待到变正；达到365天但不足60笔则继续
`INCONCLUSIVE`，不得降低样本门。即使全部通过，也只允许进入 shadow paper，真实资金
仍受独立引擎校准、真实成交偏差和运维门约束。

## 预先声明的解释限制

- `OIUSD / swap_close` 只是基础币 OI 的近似归一化，不恢复合约面值、账户方向或杠杆；
- OI 下降也可能是自愿平仓、做市库存调整或报送修订，不等同强平；
- 正 funding 只说明该次结算的多头向空头付款，不证明被挤压者一定是多头；
- 小时 OHLC 的 10% target 只有触及顺序，没有盘口深度、滑点尾部或部分成交；
- 60 个稀疏事件仍可能共享市场制度，bootstrap 不能创造独立制度样本；
- 仓库已有大量 DOGE 价格研究，所以 forward 起点提供的是本公式的未见证据，不是研究者
  对 DOGE 资产的完全无先验状态。
