# DOGE OI 挤压反转 forward 状态（OIFR v1）

初始状态时间：`2026-07-22 08:36 UTC`；运维复核更新：`2026-07-22 09:12 UTC`

## 结论先行

OIFR v1 已完成预注册和可执行化，但**没有历史回测结论，也不是候选策略**。第一根允许
决策的完整 post-freeze bar 要到 `2026-07-22 10:00 UTC` 才结束；首次手动运行因此正确
返回：

```text
OIFR decision=2026-07-22 08:00 UTC status=not_started inserted=False
ledger: captures=0 valid=0 unavailable=0 late=0 signals=0 outcomes=0
stage=FORWARD_INCONCLUSIVE newly_settled=0
```

已有约32天 OI 和99天 funding 只作为未来决策的因果 warm-up。没有计算冻结前信号数、
命中率、收益或参数邻域；因此当前也没有可以包装成 discovery PASS 的数字。

## 已冻结机制

每个小时前 720 个严格过去的 6h、价格归一化 OI 变化形成5%因果分位。当前 OI 变化跌破
该尾部、现货6h为负、最近已实现 funding 为正、但现货最后1h转正时，生成一次去杠杆反转
事件。通过61h最小信号间隔后，计划延迟一小时按 spot open 建立10%纸面仓位，10%止盈或
持有12h，按15bps/边记主成本、25bps/边记压力成本。

精确定义、成熟门和一次性裁决门见
`OPEN_INTEREST_FLUSH_REVERSAL_PROTOCOL_2026-07-22.md`。family size 固定为1，forward
期间不允许搜索阈值、周期、持有、仓位或 funding 符号。

## 可用性和账本保障

- 新增 append-only `forward_records`；相同 key 的不同 payload 直接报错，不执行更新；
- 每个决策只捕获当时刚结束的一小时，10分钟以前不落账、30分钟以后记 `missed_late`；
- 缺 OI/spot/swap/funding 时记 `data_unavailable`，后来补齐也不能改成信号；
- OI 和 OHLCV 可以在普通行情表内被交易所修订，但已冻结的特征、输入摘要哈希和信号
  不随之改变；
- accepted signal 的 outcome 在所需 bar 完成并再等待2h后才可追加，仍不可覆盖；
- 365天、60笔、捕获/有效率、季度分散和全部收益稳健门已经编码，成熟前不计算候选裁决
  指标，统一返回 `FORWARD_INCONCLUSIVE`。

实现源码：`cq/research/oifr.py`，SHA256
`7e83fe0eff5e00e69943bf45574d9cbd0e38229b8968fdba0c8f4660497ca50c`。

## 运维状态

原实际 cron 为每6小时运行一次，无法满足小时捕获。经检查和授权后已改为：

```cron
10 * * * * /home/roler/Code/CQuant/scripts/archive_derivs.sh
```

脚本每小时先重扫最近3天的 `DOGE-USDT` 与 `DOGE-USDT-SWAP`，再归档三币 funding/OI，最后
运行 `cq research observe-oifr`。第一笔允许落账的槽是 `2026-07-22 10:00 UTC`，计划于
10:10 捕获。脚本 SHA256：
`de816cefd37ef0abeb1a169cd8d75b2aeb4ce3d209879bd9858caade7d41cf30`。

09:10 的首次 cron 运维验收发现：旧 `DOGE-USDT-SWAP` 行情虽然存在，但缺少完整历史
`ohlcv_sync` 标记，通用增量恢复器因此正确地尝试从2021重走全量；这会越过30分钟捕获
窗。本次全量重走已终止，小时脚本改为显式滚动3天窗口。任何超过3天的停机仍会作为
`data_unavailable` 暴露，不会伪造 forward 信号。

修正后于09:12手动运行完整链路，17秒内成功：DOGE spot/swap 更新至08:00 open的最新
闭合bar，realized funding更新至08:00，三币OI更新至09:00；观察器正确返回
`decision=09:00 status=not_started inserted=False`，账本仍为0。

## 当前验证

- 定向测试：26 passed；
- 全量回归：505 passed（加入后续 ISR 周期后复核）；
- Ruff（新增/修改 Python 文件）：passed；
- Ruff（全仓）：passed；
- Pyright（正确注入项目 venv 的新增/修改文件）：0 errors；
- shell 语法和 diff whitespace：passed；
- 真实数据库首次 CLI：正确为 `not_started`，没有产生冻结前记录。

## 后续裁决边界

最早也要在 `2027-07-22 10:00 UTC` 以后、且至少60笔 accepted episode 已结算，才可能
成熟。成熟时固定运行一次：15/25bps总收益、平均episode、去最佳一笔、4笔 circular
block bootstrap 均过门，且季度正毛PnL集中度不超过50%，才可标记
`SHADOW_PAPER_CANDIDATE`；否则永久 `REJECTED`。不足60笔继续 INCONCLUSIVE，不降低门槛。

真实资金当前明确不批准。
