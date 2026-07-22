# DOGE 周内季节性策略预注册协议（DWS v1，2026-07-22）

> **本文件在读取任何结果前写定。** 机制、族成员、执行、成本、统计检验和
> PASS/FAIL 门槛全部在运行发现脚本之前固定，不得在看到 2021–2023 结果后修改。
> 后续若修改任何一项，都产生新版本，并重新计入尝试账本。
> 时间隔离遵循 `YEARLY_RESEARCH_PROTOCOL.md`：发现只用 `2024-01-01` 之前的数据。

## 为什么是这个机制

到目前为止本仓库对 DOGE 现货尝试过约 40 个公式，全部属于**价格状态 / 动量 /
波动率 / 微观结构 / 衍生品流**家族（VCSE、DVR、MPE、DEB、DLC、PPC、ISR、OIFR、
事件几何）。它们都在回答“当前市场处于什么状态”。

本轮提出一个与上述全部正交的家族：**纯日历时钟**。策略不读取任何价格状态、动量、
波动率、成交量、跨币或衍生品信息，只根据 **UTC 星期几** 决定是否持有 DOGE 现货。

先验假设来自加密日历异常文献（Caporale & Plastun 2019；Ma & Tanizaki 2019；
Kaiser 2019 等）：加密资产历史上存在“周末效应 / 星期效应”，周末（尤其周日、周一）
流动性与机构参与度更低、平均收益偏弱。DOGE 是零售主导、以美国为中心的 meme 币，
其可捕获漂移更可能集中在工作日。因此**先验的主策略是“持有工作日、周末持现”**。

这个先验完全来自文献，不来自对 2021–2023 结果的观察。族成员在下面固定，之后只运行
一次并诚实报告，包含 Sidak 多重检验校正。

## 固定机制

- 数据：OKX `DOGE-USDT` 现货，由 1h 基础 bar 聚合为 **1d**（UTC 00:00 边界）。
- 每根 1d bar 的“工作日归属”由其 **open 时间的 UTC 星期几** 决定
  （Monday=0 … Sunday=6）。
- 持有集合 `H ⊆ {0..6}`。在每根已闭合 1d bar 上，读取**下一根 bar** 的 open 时间
  （等于当前 bar 的 close 时间 `ctx.decision_time`）的星期几 `wd`：
  - `wd ∈ H` → 目标权重 = `size`；
  - `wd ∉ H` → 目标权重 = 0（持现）。
- 决策只用日历时钟，不读取任何价格；因此 warmup = 1，完全因果。
- 统一引擎在**下一根 open** 成交（`Sizing.ON_ENTRY`），仅 long/cash，不借币、不杠杆。
- 主成本每边 15 bps（fee 10 + slippage 5），压力每边 25 bps。

“下一根”而非“当前根”是关键：要在第 `W` 天持仓，必须在第 `W-1` 天闭合时把目标置为
`size`，让引擎在第 `W` 天 open 建仓；这保证策略在某根 bar 是否持仓，只取决于该 bar
自身的日历归属，不引入任何未来价格。

## 固定族成员（先验，非拟合）

全部 long/cash，发现阶段 `size = 1.0`（全仓，最大化漂移与成本双向暴露以看清毛效应）。

| 名称 | 持有集合 H（UTC 星期几） | 角色 | 先验依据 |
|---|---|---|---|
| `weekdays` | {Mon,Tue,Wed,Thu,Fri} | **主策略** | 周末效应：跳过 Sat/Sun |
| `ex_mon` | {Tue,Wed,Thu,Fri} | 结构邻域 | 星期一效应：再跳过 Mon |
| `ex_sun_only` | {Mon,Tue,Wed,Thu,Fri,Sat} | 结构邻域 | 只跳过历史最弱的周日 |
| `weekend_only` | {Sat,Sun} | **符号对照（placebo）** | 机制预测应更差，不可晋级 |
| `buy_and_hold` | 全部 7 天 | **基准** | 始终在场，非候选 |

本研究新增 **4 个可交易候选定义**（`weekdays`、`ex_mon`、`ex_sun_only`、
`weekend_only`）。`buy_and_hold` 是基准不是候选。累计尝试账本从 40 增至 **44**，
主策略的匹配随机检验按 **trials = 44** 做 Sidak 校正。

## 冻结的发现门（2021-2023，硬截止 2024-01-01）

主策略 `weekdays` 必须同时满足以下**全部**门槛才算发现通过（PASS）：

1. 净 15 bps 总收益 `> 0`；
2. 净 15 bps 年化 Sharpe `>= 0.40`；
3. 25 bps/边 压力总收益 `> 0`；
4. 2021/2022/2023 三个冷启动自然年中至少 **2 个** 为正；
5. **`Sharpe(weekdays) > Sharpe(buy_and_hold)`** —— 按日历选日必须改善风险调整收益，
   否则“周末去风险”没有信息价值（季节性的核心检验）；
6. **`Return(weekdays) > Return(weekend_only)` 且
   `Sharpe(weekdays) > Sharpe(weekend_only)`** —— 机制方向：持有的工作日必须优于
   其补集周末；
7. **匹配随机入场单侧 `p < 0.10`**（详见下）—— 日历选择必须携带超出“在场时间占比 /
   持有时长”的信息；
8. 至少 **50** 个持有 episode（工作日连续块）。

任何一项 FAIL，则 `weekdays` 归档为 `DISCOVERY FAIL`，不打开 2024，不回到族里挑
表现更好的成员替补，不改成 `size=0.25` 或其他持有集合再战。

## 匹配随机入场零假设（关键统计门）

复用本仓库既有方法（与 DVR/VCSE 一致，便于横向比较）：对主策略的每一个持有 episode，
固定其**入场自然年**与**持有 bar 数**，在同一年内随机抽取起点 10,000 次，套用相同的
15 bps/边往返成本，复合成零假设收益分布。

- 直接检验：按日历锚定的持有块，是否优于同年、同时长的随机锚定持有块；
- 单侧 p = (超越次数 + 1) / (样本数 + 1)；
- 报告 raw p 与 `trials = 44` 的 Sidak 校正 p；
- 门槛用 **raw 单侧 p < 0.10**（与 DVR-2025 审计门一致）。

零假设为空或候选无成交时，直接判 FAIL，不做例外。

## 稳健性附表（报告但不设为独立门）

- 逐年剔除 jackknife（2021/2022/2023）；
- circular block bootstrap（块 2、块 4）P5；
- 毛收益（0 成本）对照，用于区分“效应不存在”与“效应存在但被成本吃掉”；
- **描述性季节性图**：2021-2023 上 DOGE 1d 对数收益按 UTC 星期几的均值/标准差，以及
  1h 对数收益按 UTC 小时的均值。此图仅作机制解释，**不用于选择**持有集合或参数
  （持有集合已在上文先验固定）。

## 若发现通过

按 `YEARLY_RESEARCH_PROTOCOL.md` 推进：

1. 2024 首次顺序验证（冷启动，只淘汰不增自由度）；
2. 冻结最终版本（固定 `size`、H、成本、源码 SHA256）；
3. 2025 一次性 pre-freeze 审计，失败即整版本归档；
4. 通过后封存，写 `reports/holdout_access.jsonl` 再打开
   `2026-01-01 .. 2027-01-01`，2026 未完整或未达最小交易数时固定 `INCONCLUSIVE`；
5. 2026 结果不修改版本。

真实资金在完整证据门通过前一律不批准。

## 可复现文件

- 本协议：`docs/research/doge-spot/WEEKLY_SEASONALITY_PROTOCOL_2026-07-22.md`
- 发现实现：`research/explore_doge_weekly_seasonality.py`
- 定向测试：`tests/test_doge_weekly_seasonality.py`
- 完整结果 JSON：`reports/research/doge_weekly_seasonality_discovery.json`
- 自动报告：`docs/research/doge-spot/WEEKLY_SEASONALITY_DISCOVERY_RESULTS_2026-07-22.md`
