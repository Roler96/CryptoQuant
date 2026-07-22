# DOGE VCSE 预注册（结果未知时冻结）

> 本文件在运行任何 VCSE 历史收益回测之前写入。旧 DOGE 研究只用于排除已经失败的策略族，不提供本策略公式或参数。

## 研究问题

DOGE 现货在自身波动率长期压缩后，如果同一根闭合 4h bar 同时出现价格突破、区间扩张、强势收盘和现货成交量扩张，是否存在持续数日至数周的正向价格延续？

经济假设：波动压缩代表供需暂时平衡；随后由现货成交量确认的向上价格发现，比单纯技术突破更可能反映真实 DOGE 需求，而不是无成交量的价格漂移。策略只使用 DOGE-USDT 现货 OHLCV。

## 数据

- 输入：OKX `DOGE-USDT` spot 1h，因果聚合为 4h。
- 已知覆盖：2021-01-01 00:00 至 2026-07-20 06:00 UTC。
- 不使用 BTC、ETH、DOGE swap、funding、OI、社交媒体或链上数据。
- 当前历史全部视为探索样本；2026-07-20 后才可能形成真正 forward 数据。

## 固定主策略

名称：`DogeVcse`

### 指标

全部在闭合 4h bar 上计算：

1. True Range：标准 `max(high-low, |high-prev_close|, |low-prev_close|)`。
2. `ATR18`：前18根 TR 的简单均值。
3. `ATR% = ATR18 / close`。
4. 压缩阈值：每个候选压缩 bar 之前540根 ATR%（约90天）的20%分位数。
5. Donchian 入场通道：当前 bar 之前30根 high 的最大值。
6. 成交量基线：当前 bar 之前30根 spot base volume 的中位数。
7. Close Location Value：`(close-low)/(high-low)`；零区间 bar 记0。

### 入场

空仓时，当前闭合 bar 必须同时满足：

- 最近3根已闭合前序 bar 中至少一根 `ATR%` 低于该 bar 当时可见的过去540根20%分位数；
- 当前 close 高于前30根 high；
- 当前 TR 大于前一根可见 `ATR18` 的1.25倍；
- 当前 CLV ≥ 0.70；
- 当前 volume ≥ 前30根 volume 中位数的1.50倍。

信号在当前 bar 收盘后产生，下一根4h open买入 DOGE-USDT spot。

### 退出

持仓时，任一条件满足即在下一根4h open退出：

- 当前 close 低于前10根 low；
- 当前 close 低于持仓以来最高闭合价减去 `3 × ATR18`；
- 已持有60根4h bar（10天）。

不使用同 bar 内的理想化止损价格；所有策略退出都在信号后的下一根 open，避免未知的 bar 内路径。

### 仓位与成本

- 方向：long / flat，绝不做空。
- 研究主口径：target 1.0，`Sizing.ON_ENTRY`，用于判断信号本身是否有 edge。
- 风险缩放对照：target 0.25；它只缩放风险，不参与候选选择。
- 初始权益：10,000 USDT。
- 基准成本：10 bps fee + 5 bps slippage，每边共15 bps。
- 压力成本：25和50 bps/边。

## 预注册对照与邻域

不做全网格优化。主参数保持不变，只运行以下单因素邻域，用来判断是否为参数尖峰：

- compression quantile：15%、25%；
- breakout channel：24、36 bars；
- expansion multiplier：1.00、1.50；
- volume multiplier：1.25、1.75；
- trailing ATR：2.5、3.5；
- max hold：42、78 bars。

消融：

1. 去掉 compression；
2. 去掉 volume confirmation；
3. 去掉 CLV confirmation；
4. 只有 breakout；
5. buy-and-hold。

## 评估顺序

1. 首先只运行固定主策略全历史，记录 Return、CAGR、Sharpe、MaxDD、最长回撤、交易数、胜率、PF、去最佳交易静态收益。
2. 再看按自然年结果，不允许因为某年失败而修改主规则。
3. 再运行成本压力、单因素邻域和消融。
4. 检查收益集中度：最佳1/3/5笔贡献，删除最佳交易静态扣除，episode bootstrap。
5. 所有历史结果只称探索证据，不称 OOS。

## 历史探索通过门槛

主策略只有同时满足以下条件，才允许成为 forward shadow-paper 候选：

- 15 bps/边后全期 Sharpe ≥ 0.60；
- MaxDD ≤ 50%；
- 至少40个闭合交易；
- 至少4个完整自然年收益为正；
- 25 bps/边后总收益仍为正；
- 去掉最佳一笔的静态收益仍为正；
- 至少8/12个单因素邻域总收益为正，且至少6/12 Sharpe > 0.30；
- `breakout only` 不得明显优于完整策略，否则压缩/成交量机制不成立。

任何一项失败即不进入 forward shadow paper。不得在看到结果后降低门槛或将邻域最佳参数替换成主参数。

## 真正 forward 门槛

若历史探索通过：从2026-07-20之后开始只运行冻结主参数；至少30个新闭合交易后一次性评估。期间不调参数，不根据早期PnL切换邻域版本。实际成交成本后 block bootstrap 单侧95%下界必须大于0，且25 bps/边压力仍为正，才可讨论资金灰度。
