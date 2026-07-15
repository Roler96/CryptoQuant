# DOGE 双冲击反身性路由研究（2026-07-15）

> ## 结论：历史证据明显强于单策略，但仍只批准 shadow paper
>
> 本轮没有继续寻找均线、RSI、突破、网格或普通暴跌反弹。最终保留的是一个
> **双机制事件路由器**：系统性去杠杆时识别 DOGE 衍生参与接棒；DOGE 自身发生
> beta 无法解释的尾部下跌时，识别持续的衍生品挤压。两类事件只共享一个
> DOGE/USDT 现货仓位，先到者取得 12 小时持仓，随后整个组合进入 48 小时冷却。
>
> 在固定 OKX 1h 快照、10% 权益名义、10 bp 手续费 + 5 bp 滑点/边下，正式
> BacktestEngine 结果为 `+12.98% / Sharpe 0.81 / MTM MaxDD -3.65% / 189笔`。
> 旧单腿为 `+10.79% / 0.75 / -4.08% / 144笔`。历史审计段由 `+1.40%`
> 提升到 `+1.91%`，156 个事件簇 bootstrap 的总收益 P5 为 `+2.44%`，单事件
> 均值 95% 区间为 `[+3.1, +128.4] bp`；两个单腿的均值区间都跨零。
>
> 这仍不是新鲜 OOS。策略是在看过全史后发现，删掉最佳十笔后收益转负，
> 50 bp/边成本下也转负。因此本结论是“找到了更强且机制互补的候选”，不是
> “证明了可投入真实资金的 alpha”。

## 一、洞察：冲击来源不同，恢复时钟也不同

单一的“DOGE 暴跌”把两种完全不同的订单流混在一起：

1. **系统性冲击（ATT）**：BTC 进入自身过去 90 天六小时跌幅的最差 2.5%，
   同时 DOGE 永续相对现货成交参与抬升。它问的是：全市场去风险之后，DOGE
   的注意力是否从现货转移到杠杆场内。
2. **特异性冲击（PIRA）**：DOGE 六小时收益低于其因果 BTC beta 能解释的部分，
   并进入过去 90 天残差的最差 1%，同时永续相对参与连续两小时为正。它问的是：
   这次抛售是否是 DOGE 自身的杠杆拥挤，而不是 BTC beta 的机械传导。

两者不是重复过滤器。在各自独立冷却后，PIRA 64 个事件中仅 1 个与 ATT 精确
同小时，只有 6 个位于 ATT 的 ±6 小时；两腿收益重叠很低。因此把
PIRA 加入路由不是“多加一个相似信号提高频率”，而是把第二种冲击来源接入同一
风险预算。

没有根据历史收益设置优先级。冻结规则只是：

```text
raw_event_t = ATT_t OR PIRA_t
若未处于组合冷却：t 收盘接受事件
t+1 open 买 DOGE/USDT spot
t+13 open 卖出（持有12h）
从信号 t 起 48h 内拒绝所有新 ATT/PIRA
```

历史收益更高的 PIRA-priority 路由被拒绝，因为它的优势主要来自早期，审计段
反而弱于朴素 Union，2026 年也为负。先到先得的 Union 判断自由度更低。

## 二、冻结公式

先定义 DOGE 永续与现货的六小时参与错位：

```text
P6_t = sum(DOGE swap volume, t-5..t)
S6_t = sum(DOGE spot volume, t-5..t)
L_t  = log(P6_t / S6_t)
A_t  = L_t - median(L_{t-29}, ..., L_{t-6})
```

参照区间从 `t-6` 截止，避免最近六小时冲击污染自己的 baseline。任何固定合约
乘数会同时进入 `L_t` 与历史中位数并相消。

系统性腿：

```text
B6_t = log(BTC_t / BTC_{t-6})
ATT_t = [B6_t < causal_quantile_2.5%(B6, past 90d)] AND [A_t > 0]
```

特异性腿：

```text
beta_t = causal rolling_720h cov(r_DOGE, r_BTC) / var(r_BTC)
R6_t   = sum_6h(r_DOGE) - beta_t * sum_6h(r_BTC)
PIRA_t = [R6_t < causal_quantile_1%(R6, past 90d)]
         AND [A_t > 0] AND [A_{t-1} > 0]
```

所有 beta、分位阈值都只使用 `t-1` 及以前数据；BTC 六小时窗口只要有一个缺失
值就禁用信号。策略只做 OKX DOGE/USDT 现货多头，BTC spot 与 DOGE linear swap
仅作为同步上下文。

## 三、数据与研究纪律

- 固定区间：`2021-01-01 00:00 <= t < 2026-07-13 00:00` UTC，共 48,456 根。
- DOGE spot、DOGE swap、BTC spot 均来自项目 OKX 数据库，固定区间无缺口。
- 数据指纹：

```text
DOGE spot  060a599e5c884689d4be1dd63c9d67fc9fa9048bccfdc53617ca8c1f4a17f853
DOGE swap  5cf45705de469f7444930a2d38f89de4e7a5e09c995742704e68a52f1c3e0187
OKX BTC    72316df119e21626e8563c3b0f9693058a0c5cf1b5af955bfa59b594272f2413
```

- 信号只看闭合 bar，统一下一小时 open 成交，持有 12h。
- 成本基准固定为每边 15 bp（10 bp fee + 5 bp slip）；风险口径固定为 10%权益。
- 分段沿用 `2021-01-01..2024-07-01`、`2024-07-01..2025-07-01`、
  `2025-07-01..2026-07-13`，但只称 train / historical validation / historical
  audit，不冒充真正 OOS。
- 第二轮开始后，候选公式在看结果前写死；不做参数网格，也报告失败候选和机制
  反证，避免只展示幸存者。

## 四、统一正式框架结果

15 bp/边、10%权益名义：

| 策略 | 全期收益 | Sharpe | MTM MaxDD | 交易 | PF | 均值/笔 |
|---|---:|---:|---:|---:|---:|---:|
| 系统性 ATT | +10.79% | 0.75 | -4.08% | 144 | 1.60 | +72.4 bp |
| 特异性 PIRA | +6.80% | 0.70 | -2.45% | 64 | 1.76 | +104.0 bp |
| **Union Router** | **+12.98%** | **0.81** | **-3.65%** | **189** | **1.52** | **+65.8 bp** |

路由接受的 189 笔由 `137 ATT-only + 51 PIRA-only + 1 simultaneous` 构成。
组合 PF 和单笔均值下降并不矛盾：它用更多弱相关事件换取更好的时间分散、
回撤和整体置信区间。

### 历史分段

| 策略 | Train | Historical validation | Historical audit |
|---|---:|---:|---:|
| ATT | +5.91% / Sh 0.58 | +3.17% / Sh 1.72 | +1.40% / Sh 0.88 |
| PIRA | +5.37% / Sh 0.83 | +0.62% / Sh 0.37 | +0.74% / Sh 0.57 |
| **Union** | **+7.78% / Sh 0.69** | **+2.86% / Sh 1.33** | **+1.91% / Sh 1.04** |

Union 并没有在每一段都击败 ATT：validation 收益低于 ATT；但三个分段都为正，
且时间上最晚的 audit 段同时提高收益与 Sharpe。该段也已被研究者看过，所以仍然
只是历史审计，不升级为 OOS。

### 自然年

| 年份 | ATT | PIRA | Union |
|---|---:|---:|---:|
| 2021 | +4.07% | +2.07% | +2.83% |
| 2022 | +1.19% | +1.08% | +2.27% |
| 2023 | +1.41% | +0.23% | +1.29% |
| 2024 | +1.50% | +3.37% | +4.24% |
| 2025 | +1.73% | +0.60% | +1.46% |
| 2026 至 7/12 | +0.48% | **-0.67%** | +0.30% |

PIRA 单腿在 2026 年失效；Union 仍为正，是因为 ATT 与 PIRA 的事件时钟不同。
这也是“路由”比“选历史最佳单腿”更有价值的地方。

## 五、淘汰赛，而不是成果展

在固定样本和执行口径下，本轮还实际测试并否决了以下机制：

- swap basis V 型回收：全期有小幅正收益，但 validation/audit 仅 11 笔，机制
  placebo 不支持。
- DOGE 残差暴跌后的价格确认、perp 下影线回收、恐慌转波动压缩、quiet
  derivatives spring、double-tap、residual echo 等 12 个结构候选：多数在
  validation/audit、成本或符号反证中失败。
- 预注册 P1“永续压力未传导”：119 笔、10%收益 `+0.64%`、均值 `+6.4 bp`；
  25 bp/边转负，强收盘组反而输给弱收盘反证，正式否决。
- 预注册 P2“现货韧性吸收永续去杠杆”：83 笔、`+4.73%`；但 92.8% 位于
  ATT 的 ±6h，同一冻结 ATT 母事件内，满足 P2 的 47 笔均值 `-1 bp`，其余
  97 笔 `+107.6 bp`。它只是同一 crash cluster 内替换了确认时点，不是独立 alpha。
- Priority Router：1x 全期收益高于 Union，但 audit 更差且 2026 为负；属于
  事后复杂路由，拒绝进入正式策略。
- Risk-normalized dual sleeve：历史 Sharpe `0.97`、DD `-7.23%`，显示两腿确有
  组合价值；但当前单仓执行框架无法忠实表达独立袖套和重叠仓位，保留为研究
  对照，不伪装成已实现策略。

### 直接 OKX mark/index 反证

为避免永远用成交 OHLCV 代理“清算压力”，本轮从 OKX 公开历史端点额外回补了
DOGE swap mark 与 index 各 48,456 根 1h bar，与固定研究面板逐点对齐；两类数据
都只保存真实 `[open, high, low, close, confirm]`，没有给无成交量价格伪造 volume。

在看收益前冻结了 LIQUIDATION WEDGE：

```text
w_t = 10,000 * log(swap_trade_close / mark_close)
m_t = 10,000 * log(mark_close / index_close)

w_t < 过去90日因果1%分位
AND m_t >= 过去90日因果中位数
AND DOGE spot CLV >= 0.5
```

它试图找“永续激进成交价被打到 mark 下方，但风险价格没有同步下移、现货又守住
bar 中位”的强平真空。结果是明确失败：110 笔、10%收益 `-1.11%`、均值
`-9.3 bp`、PF `0.94`、Sharpe `-0.09`；25/50 bp 每边后均值降到
`-29.3/-79.1 bp`。符号反证均值反而 `+35.9 bp`，弱现货收盘反证为
`+59.0 bp`。更严格地先冻结 181 个负 execution-wedge 母事件再分类，
`CLV>=0.5` 的 90 笔均值 `-47.7 bp`，`CLV<0.5` 的 91 笔为 `+48.0 bp`。

因此“现货表现坚挺代表吸收”这个直觉被直接数据推翻，没有进入路由。反证组的
正收益只能登记为新发现，不能在看到结果后翻转条件并冒充预注册策略。

### SHIB → DOGE 注意力接力反证

项目 OKX 接口还回补了 SHIB spot 45,403 根和 linear swap 45,379 根连续 1h
历史。下载前先冻结状态机：SHIB 六小时收益进入过去 90 天上 2.5% 尾部且自身
衍生参与 `A_SHIB>0`，而 DOGE 对 SHIB 的因果 beta 残差不为正、`A_DOGE<=0`；
每 72h 只冻结第一个母事件，并只允许在随后 1–6h 的首次 DOGE attention 上穿零
后，于下一根 open 买 DOGE。没有确认的母事件也消耗 72h，禁止同波替补。

58 个母事件只有 23 个完成接力确认。冻结主策略 1x 全期 `-5.80%`，即 10%
风险刻度约 `-0.54%`；每笔均值 `-23.5 bp`、PF `0.74`。事件块均值 95% CI
为 `[-111.6, +69.3] bp`，删最佳一笔后进一步降到 `-11.01%`（1x）。虽然只有
4 笔的最近 audit 段为正，也不能挽救全期、样本量和 bootstrap 门槛。

所以“SHIB 爆发后等待 DOGE 杠杆注意力接棒”同样被否决，PEPE 不再用于事后
寻找能翻正的组合权重。跨 meme 数据本身有价值，但需要未来 OI、premium、
taker flow 这类真正的仓位/主动流变量；只有 OHLCV 参与度不足以支持第三条腿。

## 六、成本、延迟与尾部

### Union 压力测试

| 条件 | 10%收益 | Sharpe | PF | 均值/笔 |
|---|---:|---:|---:|---:|
| 15 bp/边 | +12.98% | 0.81 | 1.52 | +65.8 bp |
| 25 bp/边 | +8.77% | 0.56 | 1.34 | +45.6 bp |
| 50 bp/边 | **-1.07%** | -0.06 | 0.97 | -4.5 bp |
| 额外延迟 1h | +13.06% | 0.72 | 1.54 | +66.5 bp |
| 额外延迟 2h | +7.77% | 0.49 | 1.32 | +40.8 bp |
| 额外延迟 4h | +0.05% | 0.02 | 1.01 | +1.4 bp |

优势是短半衰期、低容量的事件效应，不是可以承受任意冲击成本的慢因子。

### 删极值与事件块 bootstrap

按接受信号间隔不超过 72h 合并为同一清算事件簇，固定随机种子做 20,000 次
区块重采样：

| 策略 | 事件簇 | 删最佳5笔 | 删最佳10笔 | 总收益P5 | 亏损概率 | 单事件均值95%CI |
|---|---:|---:|---:|---:|---:|---:|
| ATT | 128 | +2.73% | -1.22% | +0.69% | 3.80% | [-6.1, +152.3] bp |
| PIRA | 57 | +0.93% | -2.51% | -0.06% | 5.16% | [-20.5, +229.1] bp |
| **Union** | **156** | **+4.15%** | **-0.58%** | **+2.44%** | **2.14%** | **[+3.1, +128.4] bp** |

Union 是唯一单事件区间不跨零的候选，也是组合最重要的增量证据。但删最佳十笔
仍转负，说明 DOGE 的右尾不可替代；不能把均匀高胜率策略的直觉套在它身上。

## 七、统计边界和前瞻门槛

本轮至少查看了十余个结构候选和多个路由。虽然每个第二轮候选都先冻结再跑，
整个研究家族仍存在多重比较和发现偏差；Union 的名义 95% 区间不是经过家族错误
率修正后的 95% 证据。历史分段、逐年、bootstrap 只能说明它比旧版更值得进入
前瞻观察，不能逆转“已经看过这些价格”的事实。

从 `2026-07-13 00:00 UTC` 后冻结：

1. 正式主检验只允许 Union，不再在 Union/Priority/Risk Dual 中按新收益切换。
2. shadow paper 至少积累 60 个新的、按 72h 聚类的独立事件簇；期间不得改 beta、
   分位数、持有期或冷却。
3. 使用真实 bid/ask、滑点与拒单记录，在实际成本和 25 bp/边压力下，事件块
   bootstrap 单侧 97.5% 下界都必须大于零。
4. 只有通过统计门槛后，才另行审批真实资金、额度和 kill switch；当前 10% 只是
   研究风险刻度，不是实盘建议。

## 八、实现与复现

正式策略：`strategies/doge_reflexivity_router_spot.py`。

- `build_features()` 同时输出系统性腿、特异性腿和 Union 原始事件。
- 研究 harness 逐点断言研究 Union 与正式 Strategy 的冷却后信号完全一致。
- backtest 使用下一根 open；paper 在闭合 bar 决策后使用当前 forming bar 的最新
  可见价格。正常准点决策时它近似 next-open，context 迟到时则不会回放已经错过
  的 open。手续费按含滑点的真实 fill 名义计算。
- 三路 context feed 要求 DOGE spot/swap/BTC 的同一闭合时间戳；不 forward-fill，
  不重放迟到 bar，decision watermark 持久化防止重启重复下单。
- `config.doge_reflexivity_router.yaml` 固定启用 PaperBroker，即使用主网公开行情也
  不会发送交易所订单；10% sizer 在签署回测权益范围内不再被 1,000 USDT 订单
  上限单边截断。paper 使用独立数据库，不能再覆盖签署研究库；研究 harness
  对三路 SHA256 fail-fast，任何 candle 漂移都必须重新审计而不是静默改结果。

```bash
# 全表、逐年、成本、延迟、删极值与事件簇 bootstrap
uv run python research_doge_reflexivity_router.py

# 正式 Strategy + 通用 BacktestEngine
uv run python run_doge_backtest.py \
  --strategy doge_reflexivity_router_spot \
  --symbol DOGE/USDT --exchange okx --timeframe 1h \
  --start 2021-01-01 --end 2026-07-13 \
  --position-pct 10 --commission-bps 10 --slippage-bps 5 --no-trades

# paper-only 启动预检
uv run python live_runner.py \
  --config config.doge_reflexivity_router.yaml --paper --dry-run

# 因果、路由、研究/生产奇偶与全仓库回归
uv run pytest -q
```
