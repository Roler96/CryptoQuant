# DOGE DVR-T20 2026 冻结验证访问协议（2026-07-22）

> 本文件在 DVR-T20 首次读取2026数据之前冻结。策略已经在2025 pre-freeze审计失败，
> 按原晋级协议应归档。由于本次用户目标明确要求“参数冻结后使用2026验证”，本次仍一次性
> 打开候选级2026路径，但只作诊断性证伪；任何2026结果都不能挽救、修改或批准该策略。

## 冻结对象

- strategy：`cq/strategy/doge_dvr.py::DogeDvrTail20`；
- strategy SHA256：
  `3d0843ebe4df1d217fb24f90b2b03e3faa636474decb586a55ba16127db8adba`；
- runner：`research/validate_doge_dvr_tail20_2026.py`；
- runner SHA256：
  `49c8f328a873a9d96a0f1ce3ec296dfa9ca2dbfbd696ad955af821c5fc62d361`；
- split fingerprint：`46405e6c105c2764`；
- 参数：28日DVR，0.60/0.45迟滞，25%现货目标，20% signal-close-anchor trailing；
- 成本：主每边fee10bps + slippage5bps；压力每边25bps；
- 初资10,000 USDT，`Sizing.ON_ENTRY`，随机种子 `20260722`。

源码哈希若在首次访问前改变，本协议作废。

## 访问与边界

- study ID：`doge-dvr-tail20-v1-2026-candidate-holdout`；
- runner必须先写 `reports/holdout_access.jsonl`，然后才打开数据库；
- 查询排他终点固定为 `2027-01-01 00:00 UTC`，不得用 `latest` 替代；
- 2021–2025只作28日warmup，2026以前强制现金且内部状态冷启动；
- 评价窗固定 `2026-01-01 .. 2027-01-01`；
- 2026目前尚未结束。只有数据完整覆盖到2027-01-01才允许输出PASS/FAIL；此前无论收益
  正负，verdict固定为 `INCONCLUSIVE - 2026 INCOMPLETE`。

仓库旧VCSE研究已经读取过2026，所以这里最多是 DVR-T20 candidate-specific temporal
holdout，不声称研究者/资产层面的 pristine OOS。

## 完整年度冻结门

完整2026必须全部满足：

- 15bps/边和25bps/边收益均为正；
- MaxDD `<= 20%`；
- 至少4笔闭合交易；
- 静态扣除最佳闭合交易PnL后收益为正；
- episode bootstrap P5大于0；
- 匹配入场年份和持仓日数的随机入场单侧 `p < 0.10`。

未平仓episode在 observed 与随机null中都按末日close MTM，不虚构退出成交或退出成本。
年度统计必须把窗口前一根cash equity作为路径起点，避免漏算首日收益和回撤。

## 已知结论优先级

2025的 `PRE-FREEZE FAIL` 是永久上位结论：Return -8.51%、25bps后 -8.74%、匹配随机
p=0.641336，且 pooled block-bootstrap P5为负。因此即便2026将来满足全部冻结门，策略的
研究状态仍是 `REJECTED`；最多形成一个“失败后恢复”的新事实，不能回头改门槛。

## 尝试数勘误

事件几何脚本实际展示9个版本，而早期协议误写新增8个：DAC主版、两个邻域、
momentum-only、concentrated，PJS主版、两个邻域、first-jump，共9个。正确累计为：

- 既有VCSE 18；
- DVR/MPE/DEB 9；
- event geometry 9；
- DVR tail risk 4；
- 合计40个历史公式。

T20是这40个公式之一的事后晋级，不另冒充一个未搜索的新公式。
