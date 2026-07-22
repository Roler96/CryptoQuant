# DOGE VCSE v2 简化版探索协议（受污染历史）

> 本协议写在运行 `no_clv + no_volume` 组合结果之前，但 v1 的全历史消融结果已经显示
> 单独去掉 CLV 有利、单独去掉 volume 几乎不变。因此 v2 的提出受到了全历史结果影响，
> 本研究无论结果多好都只能称 post-hoc exploration，不能称预注册 OOS。

## 假设

VCSE v1 真正可解释的部分可能只是 DOGE 自身的“长期波动压缩后，价格与真实区间同步
向上扩张”。突破bar的 CLV 和成交量倍数是冗余确认项：突破前高和 TR 扩张已经约束了
收盘强度及价格冲击，再叠加两个阈值会漏掉有效趋势，却未必减少失败突破。

## 固定 v2 规则

继承 v1 的全部参数、时序、退出、成本和仓位，只做两处删除：

- `use_clv=False`；
- `use_volume=False`。

仍然必须满足：

- 最近3根前序4h bar至少一根 ATR18% 低于其过去540根的20%分位；
- close突破前30根high；
- 当前TR大于前一根ATR18的1.25倍；
- 下一根4h open入场；
- 10-bar低点、3 ATR trailing或60-bar time exit，下一根open退出。

本轮不搜索新的阈值、不修改退出，也不比较更多组合。

## 固定评估

1. UTC 0h/1h/2h/3h四种4h聚合相位；
2. phase 0 的15、25、50 bps/边成本压力；
3. phase 0 的2、4、8笔 circular block bootstrap；
4. phase 0 按入场年份的自然年 jackknife；
5. phase 0 匹配入场年份和持仓时长的10,000次随机入场零假设；
6. 研究尝试数固定为18：v1研究记17次，加上本次组合一次，使用Sidak校正。

## 探索通过门槛

只有同时满足以下条件，才允许把 v2 登记为与 v1 并行的 forward shadow 假设：

1. 四个相位总收益全部为正，至少3/4相位 Sharpe ≥ 0.60，且全部 MaxDD ≤ 50%；
2. 25 bps和50 bps/边压力下总收益均为正；
3. block size 2、4、8的 bootstrap P5 全部大于0；
4. 剔除任一入场年份后收益全部为正；
5. 随机入场 Sidak-adjusted p < 0.05；
6. 四个相位均至少30笔闭合交易，避免由更稀少信号制造表面稳健性。

通过只代表值得从零开始收集 forward 数据，不批准真实资金。失败则归档 v2，不再基于同一
历史继续删改过滤项。

## 产物

- 实现：`research/explore_doge_vcse_v2.py`
- JSON：`reports/research/doge_vcse_v2_exploration.json`
- 报告：`docs/research/doge-spot/VCSE_V2_EXPLORATION_2026-07-22.md`
