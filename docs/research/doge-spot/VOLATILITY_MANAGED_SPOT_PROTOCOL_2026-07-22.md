# DOGE 波动率管理现货预注册协议（VMS v1，2026-07-22）

> **本文件在读取任何结果前写定。** 机制、族成员、执行、成本、统计检验和
> PASS/FAIL 门槛在运行前固定。任何事后修改都产生新版本并计入尝试账本。
> 时间隔离遵循 `YEARLY_RESEARCH_PROTOCOL.md`：发现只用 `2024-01-01` 之前的数据。

## 为什么换掉零假设，而不是换一个信号

本仓库对 DOGE 现货已尝试约 44 个公式（VCSE、DVR、MPE、DEB、DLC、PPC、ISR、OIFR、
事件几何、DWS），全部被否决或 inconclusive。把它们放在一起看，**死因是同一个**：
每一个都在**择时**进出一个 DOGE 多头仓位，因而都倒在**匹配随机入场零假设**上——
在同年、同持有时长随机进场的表现一样好甚至更好。这说明一个结构性事实：

> DOGE 现货收益由极少数不可预测的右尾暴涨主导；任何做多它一部分时间的策略都继承
> 这些尾部，"择时"无法跑赢"随机在场"。DOGE 没有可发现的择时 alpha。

因此本轮不再提第 45 个择时信号，而是提出唯一一类**在构造上免疫于该死因**的策略：
它**永远做多、从不择时进出**，只调整**仓位大小**。匹配随机入场零假设对它不适用
（没有可随机化的入场时点）。这类机制在文献中最稳健——**波动率管理组合**
（Moreira & Muir 2017）——且在本仓库被引用三次却从未真正测试。

先验机制：加密波动率具有强持续性、可预测。**逆波动率定仓**——当 DOGE 已实现波动
高于其自身近期历史中位时按比例减仓、平静时满仓——理论上能用更小回撤持有同样的漂移。
但存在一个尖锐反面风险：DOGE 暴涨常伴随高波动，机械减仓可能砍掉产生收益的右尾。
孰胜孰负是一个干净、可测、从未回答的实证问题。

## 固定机制

- 数据：OKX `DOGE-USDT` 现货，1h 聚合为 **1d**（UTC 00:00 边界），仅 close-to-close。
- 在每根已闭合 1d bar 上，用**严格过去**的日对数收益计算：
  - 当前已实现波动 `rv_t` = 最近 `rv_window` 根日对数收益的样本标准差；
  - 参考基线 `ref_t` = 最近 `median_window` 根 `rv` 的中位数（滚动 std 序列的中位，
    不含当前值）；
- **逆波动率权重**：`w_t = clip(ref_t / rv_t, 0, size_cap)`，`size_cap = 1.0`；
  - `rv_t <= ref_t`（平静）→ 比值 ≥ 1 → 被 cap 截到满仓 1.0；
  - `rv_t > ref_t`（高波动）→ 比值 < 1 → 按比例减仓；
  - `rv_t = 0` 时取 `size_cap`。
- **执行量化**：目标权重四舍五入到最近的 `0.05`，避免微小 churn 产生无意义成交；
- 决策只用过去价格，完全因果、无状态；下一根 open 成交（`Sizing.ON_ENTRY`），
  仅 long/cash，不借币、不加杠杆（权重恒在 `[0, 1]`）；
- 主成本每边 15 bps（fee 10 + slippage 5），压力每边 25 bps。连续仓位每次跨越 5%
  边界即按差额再平衡并计成本，因此换手成本被完整计入。

warmup = `rv_window + median_window + 1`。

## 固定族成员（先验，非拟合）

| 名称 | rv_window | median_window | 方向 | 角色 |
|---|---:|---:|---|---|
| `vms` | 20 | 180 | inverse | **主策略** |
| `rv10` | 10 | 180 | inverse | 结构邻域（更快 vol 估计） |
| `rv40` | 40 | 180 | inverse | 结构邻域（更慢 vol 估计） |
| `med365` | 20 | 365 | inverse | 结构邻域（更长参考基线） |
| `anti` | 20 | 180 | **anti** | 符号对照：`w=clip(rv/ref,0,1)`，高波动加仓，应更差 |
| `buy_and_hold` | — | — | — | 基准：恒定满仓 1.0 |

本研究新增 **5 个公式变体**（`vms`、`rv10`、`rv40`、`med365`、`anti`）。累计尝试
账本由 44 增至 **49**，统计检验按 **trials = 49** 做 Sidak 校正。`buy_and_hold` 是
基准不计为候选。

## 为什么用不同的零假设

这类策略**没有入场择时**（永远做多，只改大小），所以匹配随机入场零假设**不适用**。
正确的问题是：**这条定仓规则的风险调整收益，是否真的超过恒定满仓？** 因此主统计
检验改为 **VMS 与 buy-and-hold 的 Sharpe 差**，用二者对齐的日收益做**联合 circular
block bootstrap**（同一组块索引同时重采样两条曲线，逐次计算 Sharpe 差），单侧
`p = P(Sharpe_VMS <= Sharpe_BH)`。另用本仓库 `deflated_sharpe_ratio` 报告 VMS 在
49 次尝试下的 deflated Sharpe 作为诊断。

## 冻结的发现门（2021-2023，硬截止 2024-01-01）

主策略 `vms` 必须同时满足以下**全部**：

1. 净 15 bps 总收益 `> 0`；
2. **`Sharpe(vms) > Sharpe(buy_and_hold)`** —— 定仓必须改善风险调整收益（核心，
   且已扣除自身换手成本）；
3. **`MaxDD(vms) < MaxDD(buy_and_hold)`** —— 减仓必须降低回撤；
4. 25 bps/边 压力总收益 `> 0`；
5. **`Sharpe(vms) > Sharpe(anti)`** —— 逆波动方向必须优于反向对照；
6. **联合 block-bootstrap 单侧 `p(Sharpe_vms <= Sharpe_BH) < 0.10`**（块大小 20 个
   交易日）；
7. 2021/2022/2023 三年中至少 **2 年** 满足 `Sharpe(vms_year) > Sharpe(BH_year)`。

任何一项 FAIL，则 `vms` 归档为 `DISCOVERY FAIL`，**不打开 2024**，不回到族里挑
更好的邻域替补，不改 `size_cap`/量化再战。

## 稳健性附表（报告但不设为独立门）

- 平均暴露、总换手（round-trip 等价）；
- 毛收益（0 成本）对照，区分"无效应"与"被成本吃掉"；
- VMS 的 deflated Sharpe（trials=49）与 per-bar Sharpe；
- 逐年 Sharpe/MaxDD 对照（VMS vs BH）。

## 若发现通过

按 `YEARLY_RESEARCH_PROTOCOL.md`：2024 首次验证 → 冻结（固定 rv/median/量化/成本/
源码 SHA256）→ 2025 一次性 pre-freeze 审计 → 封存后写 `holdout_access.jsonl` 再打开
2026（未完整则 `INCONCLUSIVE`）。真实资金在完整证据门通过前一律不批准。

## 可复现文件

- 本协议：`docs/research/doge-spot/VOLATILITY_MANAGED_SPOT_PROTOCOL_2026-07-22.md`
- 发现实现：`research/explore_doge_volatility_managed_spot.py`
- 定向测试：`tests/test_doge_volatility_managed_spot.py`
- 完整结果 JSON：`reports/research/doge_volatility_managed_spot_discovery.json`
- 自动报告：`docs/research/doge-spot/VOLATILITY_MANAGED_SPOT_DISCOVERY_RESULTS_2026-07-22.md`
