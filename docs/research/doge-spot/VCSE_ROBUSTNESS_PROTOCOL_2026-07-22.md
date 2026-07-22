# DOGE VCSE v1 稳健性审计协议（结果未知时冻结）

> 本协议在运行下列审计前写入。它不修改 `DogeVcse` 的任何规则或参数，
> 也不把已经看过的历史重新包装成 OOS。审计只决定 VCSE v1 历史证据的可信度
> 和 forward shadow-paper 的优先级。

## 固定对象

- 策略：`DogeVcse(VcseParams())`，即已冻结的 VCSE v1。
- 数据：OKX `DOGE-USDT` 现货 1h OHLCV，因果聚合为 4h。
- 成本：每边 10 bps fee + 5 bps slippage。
- 执行：闭合 4h bar 决策，下一根 4h open 成交。
- 仓位：long/flat，target 1.0，`Sizing.ON_ENTRY`。
- 审计不得用结果修改 v1，也不得把 `no_clv`、`no_volume` 或邻域参数替换为主版本。

## 审计一：4h 聚合相位

UTC 日内没有经济理由使 00:00、01:00、02:00 或 03:00 成为唯一正确的 4h 起点。
因此把同一组 1h bar 分别按以下左闭右开窗口聚合，并独立运行冻结策略：

- phase 0：00:00、04:00、08:00……
- phase 1：01:00、05:00、09:00……
- phase 2：02:00、06:00、10:00……
- phase 3：03:00、07:00、11:00……

只保留恰好包含4根1h bar的完整窗口，不填补缺失数据。

## 审计二：时间聚集 block bootstrap

按真实发生顺序取得每次持仓对组合权益的 episode return。分别使用长度2、4、8笔交易的
circular moving blocks，重采样10,000条与原样本交易数相同的路径。固定随机种子
`20260722 + block_size`。这项审计保留相邻交易的局部聚集，避免把46笔交易错误地视为
完全独立同分布。

## 审计三：自然年 jackknife

按入场成交所在UTC自然年分组。每次静态剔除一个年份的全部 episode，再按时间顺序复合
其余 episode return。它不重跑另一条市场路径，只回答历史收益是否由单一年份决定。

## 审计四：匹配随机入场零假设

对每一笔真实持仓固定：

- 入场成交所在UTC自然年；
- 从入场open到退出open的4h bar数量；
- 每边15 bps成本。

在同一自然年内随机抽取一个可完整容纳相同持仓时长、且入场和退出bar成交量均大于0的
起点，10,000次构成随机策略路径。比较冻结 VCSE 的总收益与该分布；单侧 p 值使用
`(超过或等于观测值的样本数 + 1) / (样本数 + 1)`。考虑本轮历史研究查看过主策略、
12个邻域和4个机制消融，固定按17次试验做 Sidak family correction。

这个零假设控制了“恰好在DOGE牛年持仓”和持仓时长，但不控制更细的月度制度，也不证明
压缩突破机制是唯一解释。

## 预先冻结的强化门槛

只有同时满足以下条件，才称为 `ROBUSTNESS PASS`：

1. 四个4h相位总收益全部为正，且至少3/4相位 Sharpe ≥ 0.60；
2. 四个相位 MaxDD 全部 ≤ 50%；
3. block size 2、4、8的 bootstrap P5 全部大于0；
4. 剔除任一自然年后的复合收益全部为正；
5. 匹配随机入场零假设经17次试验校正后 p < 0.05。

任一项失败即记为 `ROBUSTNESS FAIL`。这不会改写 VCSE v1 原预注册的历史探索结果，
但意味着它不应获得高优先级资金或因历史收益而提前结束 forward 观察。

## 产物

- 实现：`research/audit_doge_vcse_robustness.py`
- 机器结果：`reports/research/doge_vcse_robustness.json`
- 人读报告：`docs/research/doge-spot/VCSE_ROBUSTNESS_2026-07-22.md`
