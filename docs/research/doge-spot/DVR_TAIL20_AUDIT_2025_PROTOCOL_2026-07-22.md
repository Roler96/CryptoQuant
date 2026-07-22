# DOGE DVR-T20 2025 Pre-freeze 审计预注册（2026-07-22）

> 本文件在首次运行该策略的2025收益之前冻结。2024顺序验证已通过；参数、仓位、成本和
> 源码不因2024结果改变。2025只读取一次，失败则不打开2026。

## 冻结版本与语义勘误

唯一策略仍为 `cq/strategy/doge_dvr.py::DogeDvrTail20`：28日DVR、0.60/0.45迟滞、
25%现货目标、20% trailing、trailing退出后等待原状态重置。

独立代码审计在2024结果产生后指出，早期风险协议把 peak 写成“入场后的最高闭合close”，
而冻结代码实际在信号bar闭合时先以该 close 初始化，随后取更高close。两者都没有未来
数据，但可能产生不同退出。本研究不利用该发现修改已验证代码；精确冻结语义为：

**peak = 买入信号bar的close与之后可见close的累计最大值。**

因此它应被理解为 signal-close anchor，不是成交后的纯峰值。2024验证仍对应预先锁定的
源码哈希，勘误不改变任何数值或交易。

冻结指纹：

- strategy SHA256:
  `3d0843ebe4df1d217fb24f90b2b03e3faa636474decb586a55ba16127db8adba`；
- 2025 audit runner SHA256:
  `66546cfef9ecdef758fbe6a40c0276dea7b709d5d589499f2ddc240135d307d0`；
- runner：`research/audit_doge_dvr_tail20_2025.py`；
- Git base：`b3e619cbd885dbc55311c94be390d4be3008e4af`，研究工作区未提交。

上述哈希若在首次运行前变化，本协议作废。

## 数据与执行

- 进程只加载 OKX `DOGE-USDT` spot OHLCV，排他硬终点
  `2026-01-01 00:00 UTC`；绝不加载2026；
- 主评估为冷启动 `2025-01-01 .. 2026-01-01`，更早bar仅作28日warmup；
- 另以同一冻结策略连续运行2021–2025，只做明确标为in-sample的block bootstrap与
  entry-year jackknife；
- 闭合UTC日线决策、下一日open成交、`Sizing.ON_ENTRY`；初资10,000 USDT；
- 主成本每边15bps（fee10 + slippage5），压力每边25bps；随机种子 `20260722`。

## 2025匹配随机入场

对2025冻结策略的每个持仓episode，固定其入场年份和持仓日数，在2025所有可成交日中
随机抽相同长度窗口，共10,000条组合路径。随机路径使用25%固定初始权重，并按引擎的
双边fee/slippage解析计算episode账户因子。检验为单侧
`(null >= observed的次数 + 1)/(10000+1)`。

这是新的顺序年度，只检验一个冻结策略，因此本年度检验的trial count为1；此前40次发现
自由度已由先后隔离的2024/2025承担，而不把2021–2023发现p值冒充确认p值。

## Pre-freeze通过门

全部满足才允许封存并登记2026访问：

- 2025在15bps/边后收益为正、Sharpe `>= 0.20`、MaxDD `<= 20%`；
- 25bps/边压力后收益为正；
- 静态扣除最佳闭合交易PnL后收益为正；
- 至少4笔闭合交易；
- pooled 2021–2025 episode circular block bootstrap在2笔和4笔块的P5均大于0；
- pooled entry-year jackknife删除任一年后收益均大于0；
- 2025匹配随机入场单侧 `p < 0.10`。

2025 bootstrap和未平仓状态同时报告。若任一项失败，结论固定为 `PRE-FREEZE FAIL`，
本版本归档，不以改门槛、改 trailing 或改仓位继续访问2026。
