# DOGE 单币种日内开放探索与 CPER 时间挑战结果

日期：2026-08-11  
最终裁决：`REJECTED — TEMPORAL_CHALLENGE_FAIL`

## 结论

本轮没有把旧失败策略恢复、改名或微调后重新提交，而是只使用 DOGE 自身数据，从四个独立的日内状态机制出发做开放探索：

1. coherent path：多 bar 路径一致性后的延续/耗竭反转；
2. frustrated semivariance：上下半方差明显失衡但净位移不足后的释放方向；
3. muted flow impact：有符号成交额显著但价格位移受抑后的价格—流量弹性变化；
4. volatility transition：短窗实现波动相对长窗突然扩张后的延续/反转。

研究池上的 CPER（Coherent-Path Exhaustion Reversal）看似形成了稳定候选，但冻结后的一次性时间挑战为负，因此明确否决，不进入 shadow、live 或资金阶段。

## 数据与边界

- 标的：`DOGE-USDT-SWAP`
- 原始数据：OKX 原生 5m OHLCV，仅 DOGE
- 决策周期：15m，epoch 对齐
- 开放探索池：`[2021-01-01, 2025-06-01)`
- 一次性时间挑战：`[2025-06-01, 2026-08-03 06:45)`
- 成交：信号 bar 收盘后，下一根 15m open
- 主成本：10 bps fee + 5 bps slippage / side
- 压力成本：15 bps fee + 10 bps slippage / side
- funding：关闭；实测 funding 历史不覆盖研究池和挑战起点，所有结果都保留这一限制
- BTC、ETH、跨币种、funding、OI、社交和链上数据均未使用

## 外部机制依据

外部材料只用于机制生成，不用于复制参数：

- Petukhina, Reule & Härdle（2020/2021）使用 5m 加密数据记录了日内收益、成交量和波动的周期与动量结构，说明 5m–小时级状态路径值得直接检验：<https://arxiv.org/abs/2009.04200>
- Drożdż, Kwapień & Wątorek（2023）确认加密市场存在波动聚类，并报告成交量对价格变化的影响强于成熟股票市场，支持检验波动状态转换与价格—流量弹性：<https://arxiv.org/abs/2305.05751>
- Silva, Tung & Chen（2024）汇总了重尾、波动聚类、时间反演不对称等高频 stylized facts，支持使用路径结构和半方差而非单一传统指标：<https://arxiv.org/abs/2408.07653>

## 开放探索

### 第一阶段

共运行 288 个变体：4 个机制家族 × 3 个窗口 × 3 个阈值 × 4 个持有期 × 2 个方向。

| 家族 | 最佳方向 | 事件 | 日 Sharpe | 自然段为正 | 裁决 |
|---|---:|---:|---:|---:|---|
| coherent path | reversal | 106 | 0.69 | 5/5 | 进入局部开发 |
| volatility transition | reversal | 242 | 0.89 | 4/5 | 未晋级；2023 为负 |
| frustrated semivariance | reversal | 187 | -0.05 | 3/5 | 否决 |
| muted flow impact | reversal | 8 | 0.32 | 2/5 | 样本不足且不稳定 |

### 数据质量纠正

初版路径扫描遗漏了“信号窗口全部为正成交量”的正确性约束，导致交易中断附近的路径被识别为高度一致。共享引擎随后在两个候选 entry 上产生零成交量拒单，暴露该缺陷。

纠正方式不是按收益删交易，而是给所有机制统一加入因果数据条件：决策时已知的信号窗口内，每根 base volume 和 quote volume 必须严格为正。纠正后重跑全部试验，旧结果作废。最终 CPER 的 111 个 accepted entry/exit bar 全部为正成交量；共享引擎为 0 拒单。

### 自适应局部开发

围绕 coherent-path 家族又运行 192 个变体：

- window：12/14/16/18/20/24 根 15m bar
- efficiency：0.72–0.88
- hold：4/8/12/16 根 15m bar
- 只检验研究池已支持的 reversal 方向

结果：

- 17/192 个变体五个自然段全部为正；
- 67/192 个变体至少四段为正；
- 138/192 个变体 Sharpe 为正；
- 持有 12 bars（3h）在多个 window/threshold 组合上形成局部平台。

选取的平台中心是：18 bars（4.5h）路径、效率阈值 0.78、反向持有 12 bars（3h）。它不是单 bar wick、CLV、Donchian、RSI、固定 UTC 时钟或跨市场 lead-lag。

## 冻结 CPER

公式：

```text
r_j = log(C_j / C_{j-1}), j = 1..18
E = abs(sum(r_j)) / sum(abs(r_j))
if E >= 0.78:
    target = -sign(sum(r_j)) * 0.25
    hold = 12 complete 15m bars
else:
    target = 0
```

冻结实现：`cq/research/coherent_path.py`  
冻结 SHA-256：`b3d07727193a7fd0901181560ea34d13916738fe7b6176b4d95450e952549b8a`

## 共享引擎开发结果

25% 目标权重；所有路径都由 `cq-engine/1` 执行并按每根 15m close 标记权益。

| 口径 | Return | Sharpe | MaxDD | Episodes | Win rate | PF |
|---|---:|---:|---:|---:|---:|---:|
| 15 bps/side | +40.84% | 1.106 | -14.01% | 111 | 56.76% | 2.80 |
| 25 bps/side | +33.25% | 0.938 | -14.05% | 111 | 51.35% | 2.31 |

主成本分解：

- long：50 笔，合计 PnL +2,268.44 USDT
- short：61 笔，合计 PnL +1,815.40 USDT
- best-1 / best-3 / best-5 正 PnL 集中度：17.97% / 34.77% / 46.19%
- 222 fills，0 rejection，最终 flat

冷启动自然段：

| Segment | Return | Sharpe | MaxDD | Episodes |
|---|---:|---:|---:|---:|
| 2021 | +24.00% | 1.611 | -14.01% | 22 |
| 2022 | +4.76% | 1.434 | -1.71% | 27 |
| 2023 | +1.89% | 0.542 | -4.87% | 26 |
| 2024 | +6.36% | 1.734 | -2.40% | 27 |
| 2025-01-01..05-31 | +0.04% | 0.084 | -1.08% | 9 |

最后一段已经明显衰减，所以只允许冻结后的一次性挑战，不允许直接部署。

## 一次性时间挑战

冻结协议：`docs/research/doge-intraday/COHERENT_PATH_EXHAUSTION_CHALLENGE_PROTOCOL_2026-08-11.md`

| Gate | Result |
|---|---|
| H0 integrity | PASS |
| H1 capacity ≥20 | PASS（53） |
| H2 return >0, Sharpe ≥0.50, MaxDD ≥-20% | **FAIL** |
| H3 directional mechanism | NOT_RUN |
| H4 concentration | NOT_RUN |
| H5 25 bps/side stress | NOT_RUN |

挑战主结果：

| Return | Sharpe | MaxDD | Episodes | Win rate | PF |
|---:|---:|---:|---:|---:|---:|
| **-2.81%** | **-0.487** | -9.70% | 53 | 47.17% | 0.83 |

方向分解：

- long：30 笔，合计 PnL +273.34 USDT
- short：23 笔，合计 PnL -554.40 USDT
- best-5 正 PnL 集中度 80.34%
- 106 fills，0 rejection，最终 flat

CPER 在开发池的双向反转特征没有延续到时间挑战：长侧仍为正，短侧翻为明显负值；总收益、Sharpe 和 PF 同时失效。按冻结顺序，H2 失败后不运行压力测试，也不以“只保留 long”、改阈值、改持有期或增加过滤器救援。

## 最终裁决

`CPER v1 = REJECTED`

它证明了“高一致性 4.5h 路径后的 3h 反转”在 2021–2025 开发池存在可搜索结构，但该结构没有通过 2025-06 之后的时间挑战。当前没有可部署的单币种日内策略成果。

保留的工程产物：

- `scripts/research_doge_intraday_open.py`：480 次开放探索、共享引擎开发验证与完整 trial ledger
- `cq/research/coherent_path.py`：冻结、因果、可测试的 CPER 研究策略
- `tests/test_coherent_path_research.py`：未来不变性、零成交量、持有时序、下一 open 和引擎一致性测试
- `scripts/run_doge_coherent_path_challenge.py`：门控的一次性时间挑战 runner
- `reports/research/doge_intraday_open_exploration_v1.json`：完整机器探索结果
- `reports/research/doge_cper_temporal_challenge_2026-08-11.json`：完整机器挑战结果
