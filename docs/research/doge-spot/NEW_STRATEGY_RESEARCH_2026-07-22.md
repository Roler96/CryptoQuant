# DOGE 现货新策略研究结论（2026-07-22）

## 结论先行

本轮提出并冻结了一个新的 DOGE-only 状态变量：**DVR（Directional Variance Ratio，
方向方差占比）**。它不把所有波动都视为坏风险，而是区分上涨平方收益与下跌平方收益，
识别“波动主要由买方价格发现贡献”的阶段。

最终可交易版本 **DVR-T20** 使用25%现货仓位、0.60/0.45状态迟滞和20%峰值回撤锁。
它在首次未见的2024表现很强，但在随后未见的2025明确失败。因此结论不是“找到可实盘
策略”，而是：

> **DVR是一个有解释力的DOGE右尾状态描述器，但当前证据不支持它是跨制度稳定的选时
> alpha。DVR-T20归档，不批准真实资金，也不因2026 YTD结果修改。**

2026数据按用户要求在参数完全冻结后才打开；截至数据库的 `2026-07-22 00:00 UTC`，
自然年尚未结束，所以年度验证固定为 `INCONCLUSIVE`。而候选本身已经被2025拒绝，
任何2026结果都不能挽救它。

## 最终冻结规则

对最近28根完整UTC日线的对数收益 `r`：

`DVR = sum(max(r, 0)^2) / sum(r^2)`。

- armed且空仓：DVR `>= 0.60` 且28日对数收益为正，下一根日线open买入；
- 目标：账户权益的25%持有DOGE，75%持有USDT；
- 正常退出：DVR `<= 0.45` 或28日动量非正，下一根open卖出；
- 尾部退出：从买入信号bar的close开始记录累计最高close，回撤20%后下一根open卖出；
- 尾部退出后disarm，必须等正常退出状态至少出现一次才可重新armed；
- 仅做long/cash，不借币、不加杠杆；
- 信号只读闭合bar，统一引擎下一根open成交；
- 主成本每边15bps（fee10 + slippage5），压力每边25bps。

实现：`cq/strategy/doge_dvr.py::DogeDvrTail20`，冻结源码 SHA256 为
`3d0843ebe4df1d217fb24f90b2b03e3faa636474decb586a55ba16127db8adba`。

## 顺序证据

| Stage | 角色 | Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps return | 决策 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 2021–2023 T20 | discovery内固定邻域 | +85.82% | 0.72 | -19.71% | 21 | +8.04% | 未作主门 | 事后晋级 |
| 2024 | 首次顺序validation | +65.76% | 1.93 | -18.40% | 11 | +4.78% | +64.81% | PASS |
| 2025 | 首次pre-freeze audit | -8.51% | -0.63 | -13.27% | 5 | -10.24% | -8.74% | **FAIL** |
| 2026 YTD | 冻结诊断，年度未完 | -4.56% | -1.21 | -6.89% | 9 | -4.99% | -4.98% | INCONCLUSIVE |

2026同期DOGE现货自身从年初open到当前最后完整日线close约为 `-37.55%`。DVR-T20的
25%仓位和现金状态显著限制了损失，但“比暴跌少亏”不等于正alpha，也不满足冻结门。

### 2025为什么具有否决力

- 冻结策略亏 `-8.51%`，25bps压力后仍亏 `-8.74%`；
- 匹配相同年份和持仓日数的随机25%现货持有，null中位数为 `-5.23%`；
- 策略并未优于随机时点：单侧 `p=0.641336`；
- 2021–2025 pooled circular block-bootstrap P5在2笔块和4笔块分别为
  `-10.58%`、`-5.68%`；
- 删除任一入场年份后的pooled收益仍为正，说明不是单一年份独占；真正失败的是新年度
  可迁移性和信号选时，而不是简单的年份集中。

### 2026当前只说明什么

- 覆盖仅 `2026-01-01 .. 2026-07-22 00:00 UTC`，不是完整自然年；
- 当前匹配随机null中位数 `-5.05%`，DVR-T20为 `-4.56%`，单侧 `p=0.466553`；
- 9笔闭合交易虽达到数量进度，但收益、压力收益、去最佳一笔、bootstrap P5和随机检验
  当前都未过门；
- 因年度未完只能INCONCLUSIVE；因2025已FAIL，未来即使转正也不能反向批准本版本。

## 被否决的独立机制

### 1. 全仓方向状态、三尺度动量、方向效率突破

| Candidate | Return | Sharpe | MaxDD | Less best 1 | 发现门 |
|---|---:|---:|---:|---:|---|
| DVR28 full weight | +420.09% | 0.98 | -69.49% | -20.35% | FAIL |
| MPE (8/32/128d) | -65.38% | -0.27 | -75.92% | -71.85% | FAIL |
| DEB (28/10d) | +125.73% | 0.72 | -83.36% | -246.91% | FAIL |

核心发现：DVR确实比普通多尺度动量更能识别DOGE的上涨右尾，但全仓版本把一次大行情
造成的权益峰值误当成可持续财富，随后出现近70%回撤。高总收益不能覆盖集中度失败。

### 2. 小时事件几何

预注册检验“同样24h涨幅由许多小时分散贡献，是否比单根跳涨更可持续”。结果与先验相反：

| Candidate | Return | Sharpe | MaxDD | Trades | 发现门 |
|---|---:|---:|---:|---:|---|
| Diffuse accumulation | -71.28% | -0.43 | -86.84% | 217 | FAIL |
| Positive-jump second confirmation | +6.56% | 0.28 | -57.42% | 73 | FAIL |
| Concentrated-jump符号对照 | +16.56% | 0.44 | -15.15% | 5 | 不可晋级 |

分散式上涨没有体现“机构拆单”的延续，反而持续买在短期动量耗尽处；集中跳涨对照仅5笔，
不能据此事后构造新策略。PJS在25bps成本后也转负。本轮没有把失败候选Union成router。

### 3. 风险层

DVR-T25把全仓MaxDD从69.49%降到25.86%，但扣除最佳一笔后仍为 `-5.47%`，按预注册
发现门FAIL。固定邻域T20为 `+8.04%`，因此被诚实标为discovery事后选择，并用此前未读
2024验证。2024通过、2025失败，恰好展示了为什么“邻域里挑最好”必须再付一个新年度。

## 机制解释

时间序列动量研究支持1–12个月收益具有一定持续性，但那是跨58个期货的分散证据，不能
直接外推成单一DOGE的稳定alpha。DVR保留“趋势持续”思想，同时把已实现方差分解成上涨
与下跌能量；这种分解来自 realized semivariance，而不是把上涨波动也当作需要惩罚的风险。

本轮最重要的机制判断是：

1. DOGE的可捕获收益主要来自少数买方主导的右尾状态；
2. 总波动率缩放会在暴涨时机械减仓，方向半方差更贴近现货多头真正承担的坏风险；
3. 但状态识别不是条件期望证明。2024能抓住右尾，2025却连同持有期随机入场都没赢；
4. 25%仓位和trailing创造的是风险可承受性，不是alpha。不能把降回撤包装成预测能力。

复杂ML/HMM没有进入候选：当前只有5个完整开发年、单一资产和高度非平稳的右尾，模型
自由度会远快于独立样本增加。

## 研究纪律与可复现性

- discovery查询在数据库层硬截止 `2024-01-01`；
- 2024 runner排他截止 `2025-01-01`；
- 2025 runner排他截止 `2026-01-01`；
- 2026访问先写入 `reports/holdout_access.jsonl`，再读取固定
  `2026-01-01 .. 2027-01-01` 窗口；访问次数为1；
- 2026 runner不用`latest`，年度不完整时强制INCONCLUSIVE；
- 全部策略通过Context读取历史窗口，测试覆盖prefix invariance、long-only、reset、
  trailing disarm/rearm、checkpoint恢复、固定持有和cooldown；
- 40个历史公式纳入尝试账本；2021–2023上的漂亮p值不被当作确认；
- 回测统一使用下一bar open、15/25bps成本和现货不可借贷约束。

## 透明偏差与限制

1. 原tail-risk文字把peak称为“入场后最高close”，冻结代码实际从signal close开始锚定。
   它完全因果，但gap-up时较松、gap-down时较紧，不是单向保守。2024已打开后没有修改
   代码，而是保留源码哈希并明确精确定义。
2. 原风险协议说邻域不得替换主版；T25失败后仍把T20建立为新版本，属于透明的协议偏离。
   它没有回头改写discovery PASS，而是消耗了此前未读的2024做新验证。
3. 年度指标审计发现通用切片没有显式把期初cash点送入Sharpe/MaxDD。事后用前一根真实
   cash equity重算，2024仍为Sharpe `1.93`/MaxDD `18.40%`，2025仍为
   `-0.63`/`13.27%`，未改变裁决；2026 runner已直接使用修正口径。
4. 事件几何脚本实际查看9个版本，早期协议误记8个。最终尝试数已更正为40。
5. 2026在仓库旧VCSE研究中已被访问，不能称资产层面pristine OOS；这里只能声称
   DVR-T20的参数在候选首次读取2026前已冻结。
6. 2026当前只有202个完整日线bar；完整自然年必须在2027-01-01后重新运行同一冻结代码。
7. 成交模型没有盘口冲击、容量、部分成交或真实lot/min-notional；固定10,000 USDT初资下
   15/25bps压力有参考意义，但不能推导容量。
8. 外部Donchian引擎校准门仍为FAILED；内部因果和现货记账测试充分，不等于外部基准
   已完全复现。

## 决策

- **真实资金：不批准。**
- **DVR-T20：归档，状态REJECTED。** 不调参数，不用2026改成T15/T25，不建router。
- **2026年度：INCONCLUSIVE。** 2027-01-01后只能用相同源码哈希做一次完整年度更新，
  但该更新不会推翻2025否决。
- 若继续研究，应提出与本轮40个公式不同的机制，并把真正的新证据放在2026-07-22之后
  或更晚的forward数据上；同一2026路径已经被消费，不能再次称未见验证。

## 后续独立循环：双领导币追赶（DLC v1）

在 DVR-T20 归档后，另行预注册了一个不使用 DVR、VCSE、swap、funding 或旧策略信号的
跨市场信息扩散假设：BTC 与 ETH 的 6 小时收益同时高于各自过去 90 天因果 90% 分位，
而 DOGE 尚未完成滚动 beta 传导并首次出现正小时确认时，买入 25% DOGE 并持有 12h。

本轮严格先写协议，再把三市场查询硬截止在 `2024-01-01`。结果是明确反证：

| Version | Return | Sharpe | MaxDD | Trades | Mean episode |
|---|---:|---:|---:|---:|---:|
| DLC main | -33.95% | -1.47 | -37.36% | 207 | -0.20% |
| leader-only ablation | -18.57% | -0.63 | -24.92% | 255 | -0.08% |
| already-led sign placebo | +8.09% | 0.37 | -7.23% | 123 | +0.07% |

- 2021、2022、2023 冷启动收益分别为 `-7.40%`、`-26.65%`、`-2.75%`；
- 25 bps/边压力收益为 `-40.44%`，bootstrap P5 为 `-46.94%`；
- 同年份、同持仓长度随机入场中位数为 `-6.97%`，主版 raw 单侧
  `p=0.979302`，5 个可交易版本 Sidak-adjusted `p=1.0`；
- 85%/95% 领导币分位和 8h/18h 持有四个冻结邻域全部亏损。

所以正向“补涨”假设被拒绝，而且信号比同一批领导币上涨后的无条件持有更差。符号对照
为正与文献所述的资金追逐热门币更一致，但它是看过结果后的反证组，Sharpe 也只有0.37；
按协议不能替补晋级、不能打开2024、不能据此称为新发现策略。

- 冻结协议：`DUAL_LEADER_CATCHUP_PROTOCOL_2026-07-22.md`
- 实现：`research/explore_doge_dual_leader_catchup.py`
- 完整结果：`reports/research/doge_dual_leader_catchup_discovery.json`
- 自动报告：`DUAL_LEADER_CATCHUP_DISCOVERY_RESULTS_2026-07-22.md`

## 后续独立循环：永续溢价趋势确认（PPC v1）

随后预注册了一个与 DLC、DVR 和 VCSE 不同的数据机制：用 OKX
`DOGE-USDT-SWAP / DOGE-USDT` 的成交价格基差判断杠杆需求，只在过去24h基差中位数
高于不重叠30日因果基线1个MAD、且现货七日动量为正时持有25% DOGE 现货。

spot/swap 的1h源和4h聚合都硬截止 `2024-01-01`。冻结主版本再次明确失败：

| Version | Return | Sharpe | MaxDD | Trades | Mean episode |
|---|---:|---:|---:|---:|---:|
| PPC main | -17.86% | -0.40 | -41.14% | 117 | -0.13% |
| momentum-only ablation | +55.87% | 0.59 | -53.89% | 245 | +0.26% |
| premium-only ablation | -21.67% | -0.44 | -43.83% | 151 | -0.13% |

- 2021为 `+15.14%`，但2022、2023分别为 `-16.30%`、`-14.76%`；
- 25bps/边压力收益 `-22.52%`，bootstrap P5 `-46.62%`；
- 匹配年份和实际持仓长度的随机null中位数 `+5.00%`，主版 raw
  `p=0.861214`，5版本 Sidak-adjusted `p=0.999949`；
- 120根短基线邻域虽为 `+10.32%`，Sharpe仅0.27、MaxDD39.37%，且其余三个冻结邻域
  全亏；按协议不得从唯一正邻域替补。

机制结论是：在这段DOGE历史上，末笔成交价格形成的持续永续溢价没有给普通七日趋势
增加信息，反而选择了更差的持仓区间。momentum-only的正收益伴随53.89%回撤，而且属于
旧趋势公式族；它既不能证明premium机制，也不能由本轮消融替补晋级。PPC v1不读取2024。

- 冻结协议：`PERPETUAL_PREMIUM_CONFIRMATION_PROTOCOL_2026-07-22.md`
- 实现：`research/explore_doge_perpetual_premium_confirmation.py`
- 完整结果：`reports/research/doge_perpetual_premium_confirmation_discovery.json`
- 自动报告：`PERPETUAL_PREMIUM_CONFIRMATION_DISCOVERY_RESULTS_2026-07-22.md`

## 当前衍生品流数据边界

PPC 失败后审计了下一类真正正交信息，而不是继续改 basis 参数。数据库中的衍生品流数据
本身质量连续，但历史长度尚不足以做顺序 discovery/validation：

| Dataset | Coverage | Rows | Spacing | Missing/null |
|---|---|---:|---:|---:|
| BTC/ETH/DOGE realized funding | 2026-04-14 08:00 → 2026-07-22 00:00 UTC | 各297 | 8h | 0 |
| BTC/ETH/DOGE OI + volume USD | 2026-06-20 07:00 → 2026-07-22 04:00 UTC | 各766 | 1h | 0 |

每个目标已有11次 archive run、其中10次成功；时间序列没有间隔异常。问题不是脏数据，
而是只有约99天funding和32天OI。用它们切分训练/验证会让同一市场事件同时主导两段，
无法支持资金部署结论。下一轮可以先冻结一个 forward-only 流量假设，但在积累跨制度样本
前不能把30天回测包装成 discovery PASS；归档任务应继续运行。

## Forward-only 独立循环：OI 挤压反转（OIFR v1）

由于32天OI不足以承担 discovery/validation，本轮没有回测或搜索这段 warm-up，而是在
`2026-07-22 08:25 UTC` 先冻结一个 family size=1 的真正 forward 假设：价格归一化
DOGE OI 的6h变化跌破严格过去30天5%分位、现货6h下跌、最新已实现 funding 为正，且
最后1h出现正收益确认时，观察未来12h的10%小仓位反转。

本循环当前不是“正收益发现”，而是把新的信息优势变成可审计实验：

- `2026-07-22 10:00 UTC` 前的 OI/funding 只准 warm-up，不生成策略结果；
- 每个小时只捕获当时槽，迟到和缺数都不可回填；
- append-only SQLite 账本冻结特征、信号、源摘要哈希和随后 outcome；
- 原每6小时 cron 已经授权改为每小时第10分钟，先同步 DOGE spot/swap，再归档衍生品；
- 365天、60笔、98%捕获率、95%有效率和季度覆盖满足前，固定状态为
  `FORWARD_INCONCLUSIVE`；
- 成熟后只做一次冻结裁决，全部稳健门通过也只进入 shadow paper，当前真实资金不批准。

`2026-07-22 08:36 UTC` 的真实 CLI 首跑正确返回 `not_started`、账本0条；没有读取冻结前
信号或收益。定向测试26项通过，新增/修改文件 Ruff 通过、Pyright 0 errors。完整规则与
状态分别见 `OPEN_INTEREST_FLUSH_REVERSAL_PROTOCOL_2026-07-22.md` 和
`OPEN_INTEREST_FLUSH_REVERSAL_FORWARD_STATUS_2026-07-22.md`。

随后全量回归为491 passed，全仓 Ruff 通过。

09:10运维验收发现 swap 缺少完整历史同步标记，通用恢复器会从2021重走全量并错过捕获
窗；已终止该次重走，把小时脚本改成显式滚动重扫最近3天。09:12完整链路用17秒成功，
行情、funding、OI均更新，观察器仍正确返回 pre-start、账本0条。脚本不会用后来数据回填
这个冻结前槽。

## 后续独立循环：特异性卖压反转（ISR v1）

在等待 OIFR forward 数据期间，另行冻结了一个不读取 OI、funding、basis、volume、DVR
或 VCSE 的三币相对价值机制。ISR 用严格早于当前6h事件的90天小时收益估计 DOGE 对
BTC/ETH 等权市场的 beta，并把当前6h残差与同一因果窗内2,155个历史6h残差比较。只有
DOGE残差跌破5%分位、DOGE自身6h为负、BTC/ETH组合6h非负且DOGE最后1h转正时，才以
25%现货仓位持有12h。

协议、实现和14项定向测试在读取结果前完成，三市场查询排他硬截止 `2024-01-01`。冻结
主版得到明确反证：

| Version | Return | Sharpe | MaxDD | Trades | Mean episode |
|---|---:|---:|---:|---:|---:|
| ISR main | -12.36% | -0.58 | -14.93% | 64 | -0.20% |
| q2.5% | -11.85% | -0.59 | -18.46% | 33 | -0.37% |
| q10% | -5.89% | -0.19 | -14.25% | 110 | -0.05% |
| hold6 | -10.21% | -0.76 | -11.95% | 66 | -0.16% |
| hold24 | -27.13% | -1.06 | -28.62% | 59 | -0.52% |

- 2021、2022、2023 冷启动收益分别为 `-10.93%`、`-0.66%`、`-0.96%`；
- 25bps/边压力收益 `-15.12%`，去最佳一笔后 `-15.25%`，bootstrap P5
  `-25.86%`；
- 同年份、同持有长度随机入场中位数 `-2.52%`，主版 raw 单侧 `p=0.870313`，5版本
  Sidak-adjusted `p=0.999963`；
- 四个可交易邻域全部亏损。

删除 `M6>=0` 的机制消融为 `+8.18%`、Sharpe `0.33`，但 bootstrap P5仍为负，而且它
在协议中明确不可晋级。这个结果最多说明“把市场下跌排除掉”使样本更差；不能在看过结果
后把消融包装成 v2。ISR v1 永久 `REJECTED`，不读取2024。

- 冻结协议：`IDIOSYNCRATIC_SELLOFF_REVERSAL_PROTOCOL_2026-07-22.md`
- 实现：`research/explore_doge_idiosyncratic_selloff_reversal.py`
- 完整结果：`reports/research/doge_idiosyncratic_selloff_reversal_discovery.json`
- 自动报告：`IDIOSYNCRATIC_SELLOFF_REVERSAL_DISCOVERY_RESULTS_2026-07-22.md`

加入 ISR 后全量回归更新为505 passed；全仓 Ruff 和 ISR 定向 Pyright 均通过。

## 后续独立循环：周内季节性（DWS v1）

前面 40 个公式全部属于价格状态 / 动量 / 波动率 / 微观结构 / 衍生品流家族。本轮换到
一个与它们完全正交的家族：**纯日历时钟**。DWS 不读取任何价格、动量、波动率、成交量、
跨币或衍生品信息，只按 **UTC 星期几** 决定是否持有 DOGE 现货。先验来自加密日历异常
文献（周末效应 / 星期效应），主策略先验固定为“持有工作日、周末持现”，`size=1.0`，
1d bar，下一根 open 成交，仅 long/cash。

协议、实现和15项定向测试在读取结果前完成，查询硬截止 `2024-01-01`。冻结主版本得到
明确的 **DISCOVERY FAIL**：

| Candidate | Return | Sharpe | MaxDD | Episodes |
|---|---:|---:|---:|---:|
| weekdays（主） | +205.29% | 0.71 | -95.14% | 156 |
| ex_mon | +910.68% | 0.83 | -81.35% | 156 |
| ex_sun_only | +653.99% | 0.87 | -93.91% | 157 |
| weekend_only（placebo） | +101.99% | 0.63 | -43.39% | 157 |
| buy_and_hold（基准） | +1472.28% | 0.98 | -92.33% | 1 |

两个关键门失败，且都是**尺度不变**的结论（long/cash 固定仓位下 Sharpe 与匹配随机检验
的符号不随 `size` 改变）：

1. **`Sharpe(weekdays)=0.71 < Sharpe(buy_and_hold)=0.98`** —— 跳过周末不但没有改善、
   反而**损害**了风险调整收益；
2. **匹配随机入场 raw 单侧 `p=0.511`**（Sidak trials=44 后 `p=1.0`）—— 星期几日历
   **不携带任何超出在场时长的信息**，同年、同持有长度的随机锚定持有块表现一样好
   （null 中位数 `+224.73%` > observed `+205.29%`）。

毛收益（0 成本）主策略为 `+387.48%`、Sharpe `0.77`，25bps 压力后仍为 `+123.46%`，
所以**不是被成本吃掉**，而是效应本身不存在。描述性季节性图直接反证了文献先验：
DOGE 2021-2023 周六 1d 对数收益均值 `+0.578%`、周日 `+0.169%`（周末并不弱），真正
偏弱的是周一 `-0.765%` 和周三 `-0.067%`。也就是说加密“周末效应”在 DOGE 这段历史上
不成立，逐年 jackknife 显示结果由 2021 单一年份主导（剔除 2021 后转为 `-71.59%`）。

按协议主策略归档为 `DISCOVERY FAIL`，**不打开 2024**，不回到族里挑表现更好的
`ex_mon`/`ex_sun_only` 替补，不改 `size` 再战。DWS v1 永久 `REJECTED`。累计尝试
账本由 40 增至 **44**。这是又一个诚实的正交反证：DOGE 现货没有可交易的星期日历 alpha。

- 冻结协议：`WEEKLY_SEASONALITY_PROTOCOL_2026-07-22.md`
- 实现：`research/explore_doge_weekly_seasonality.py`（SHA256
  `9df311834823b6365aa1e39973fecd00921173d0c2de5d5d38a79d419d1bf64a`）
- 完整结果：`reports/research/doge_weekly_seasonality_discovery.json`
- 自动报告：`WEEKLY_SEASONALITY_DISCOVERY_RESULTS_2026-07-22.md`

加入 DWS 后全量回归更新为 **520 passed**；全仓 Ruff 通过，DWS 定向 Pyright（注入项目
venv）0 errors。

## 学术机制参考

- Moskowitz, Ooi & Pedersen, *Time Series Momentum*：
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463
- Moreira & Muir, *Volatility Managed Portfolios*：
  https://www.nber.org/papers/w22208
- Barndorff-Nielsen, Kinnebrock & Shephard, *Measuring Downside Risk — Realised
  Semivariance*：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1262194
- Caporale & Plastun, *The Day of the Week Effect in the Cryptocurrency Market*：
  https://www.sciencedirect.com/science/article/abs/pii/S1544612318303751
- Ma & Tanizaki, *On the Day-of-the-Week Effects of Bitcoin Markets*：
  https://doi.org/10.1108/IMEFM-04-2019-0165

这些文献只支持机制来源，不构成DOGE结果的外部验证；DWS v1 的结果恰好反证了周末效应在
DOGE 上的可交易性。
