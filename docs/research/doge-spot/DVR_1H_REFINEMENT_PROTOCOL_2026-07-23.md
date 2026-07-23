# DOGE DVR 1h 精化冻结协议（DVR-1H v1）

冻结时间：`2026-07-23`（在运行任何 1h 变体的信号、收益或参数结果之前）。

> 三方向 1h 研究的**第二条(B)**：不开新机制族、不花新 discovery 自由度去发现 alpha，
> 而是把**已经通过审计的日线 DVR-Tail20**（`cq/strategy/doge_dvr.py::DogeDvrTail20`）的
> **执行分辨率**细化到 1h，检验"更快的退出/进入分辨率能否改善已存活的 edge"。这是
> 执行层改进，不是新发现。**零新调参**：全部经济参数冻结为日线 DVR 现值，只改分辨率。

## 动机（承接方向 C 的发现）

方向 C 证明单资产 1h 反转的毛 edge 巨大但被 7027 笔换手成本吞没——**约束是换手频率**。
DVR 是稀疏的制度/事件策略（discovery 2021-2023 仅 21 笔），因此在它上面增加 1h 分辨率
不会引爆换手。最有动机的一处：DVR 的 **20% trailing stop 在日线上只看日收盘**，一个盘中
跌 20% 又收回的 bar 对它不可见；1h 分辨率让 trailing stop 在小时级触发，理论上改善回撤
控制与退出时机。本研究检验这个改进在 discovery 上是否真的优于冻结日线基线。

## 冻结基线（对照锚，不可改）

`DogeDvrTail20` 默认配置在 1d bar 上：`horizon=28, entry_share=0.60, exit_share=0.45,
trail_drawdown=0.20, size=0.25`。所有经济参数在本研究中**冻结不变**，唯一变量是执行分辨率。

## 数据与严格顺序

- 数据：仅 OKX `DOGE-USDT`（1h 主序列；1d 由 1h 重采样作为 hybrid 变体的 as-of 对齐辅助
  周期）。**不使用 BTC/ETH/swap/funding/OI**。
- Discovery 查询在数据库层排他硬截止 `2024-01-01 00:00 UTC`；不读取 2024/2025/2026。
- 初始资金 10,000 USDT，long/cash，25% 仓位；信号只读闭合 bar，下一根同周期 open 成交；
  多周期对齐由 `core/clock` 的 close-time as-of 单点裁决，策略侧无 shift。
- `Sizing.ON_ENTRY`；主成本每边 15bps，压力每边 25bps。

## 三个冻结版本

1. **baseline_daily**：冻结日线 DVR，1d 主序列。对照锚。
2. **full_1h**：把 DVR 完整逻辑搬到 1h 主序列，`horizon=672`（28d×24），其余经济参数不变。
   variance_share 与 momentum 在 672 根小时收益上计算；trailing stop 用 1h 收盘峰值。
   **声明局限**：672h 窗口测的是小时级波动结构，与 28d 窗口测的日级结构并非同一统计量，
   故这不是纯"分辨率"改动，信号内容也随之变化——这是 full_1h 的固有性质，如实标注。
3. **hybrid**：日线制度信号（28d，经 1d aux 的 as-of 对齐，只见昨收及更早，无前视）决定
   进入/regime 退出；trailing 20% stop 与峰值跟踪在 **1h 主序列**上每小时评估，成交在
   下一根 1h open。这隔离了"更快退出/进入分辨率"这一单一改动，最贴合本研究动机。

不检验其他 horizon、entry/exit share、trail 幅度、size 或 timeframe。`FAMILY_TRIALS = 2`
（两个可交易 1h 变体）。

## 附加诊断

- 三版本各自：Return / Sharpe / MaxDD / 最长水下 / Trades / 平均持有 / 25bps 压力。
- 冷启动自然年（2021/2022/2023）逐版本。
- 换手对比：1h 变体相对日线的交易数增幅（成本敏感度）。

## Discovery 晋级门（1h 变体须证明分辨率带来净改善）

某个 1h 变体（full_1h 或 hybrid）"晋级"当且仅当**同时**：

1. 15bps 总收益 `>` baseline_daily 的 15bps 总收益；
2. 15bps Sharpe `>` baseline_daily 的 Sharpe；
3. MaxDD `<=` baseline_daily 的 MaxDD（回撤不劣化——这是本改进的核心卖点）；
4. 25bps 压力下总收益仍 `> 0` 且仍 `>` baseline_daily 的 25bps 收益；
5. 2021–2023 至少两个冷启动自然年收益为正；
6. 该变体 15bps 总收益 `> 0` 且去最佳一笔后 `> 0`。

若两个 1h 变体都不满足全部六项 → `DISCOVERY FAIL`：1h 分辨率不改善 DVR，永久归档
DVR-1H v1，不读取 2024，不调参。若恰有一个满足 → 记为该变体的候选晋级，写单独 validation。

## 预先声明的限制

- baseline_daily 的参数本身可能在历史上接触过 2021-2023；1h 变体在其"主场"上比较，
  若 1h 胜出才有意义，未胜出则倾向负面/不确定，如实报告，不追溯性调 1h 参数去翻盘。
- full_1h 的信号内容随窗口变化（见上），hybrid 才是"纯分辨率"最干净的一版。
- close 决策/next-open 模型无盘口深度、部分成交或冲击容量；发现通过也最多是候选。
