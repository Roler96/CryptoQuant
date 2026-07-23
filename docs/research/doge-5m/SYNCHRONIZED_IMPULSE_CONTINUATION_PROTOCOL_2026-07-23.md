# DOGE 5m 现货确认的永续冲击延续协议 (SIC v1)

## 研究问题

BSR v1 检验了现货-永续基差回归，但机会全部集中在 2021，因频率和跨年度覆盖不足而
失败。SIC v1 改测一个方向相反、PnL 来源不同的机制：

> DOGE 永续在 15 分钟内出现相对自身近期波动极端、且伴随异常成交量的价格冲击时，
> 如果现货同步同向确认，该冲击是否代表尚未完成的信息传导，并在随后 15–60 分钟延续？

SIC 交易永续的方向收益，不交易基差；它允许 long/short，但账户 gross exposure 固定
为 0.5x。现货只作确认，不成交。

这是 5 分钟级日内策略，不是撮合级 HFT。历史数据没有 bid/ask、订单簿、逐笔成交、
队列位置或延迟，不能检验做市、抢单或挂单成交优势。

本协议在读取任何 SIC 收益前冻结。DOGE 历史路径已被此前研究广泛观察，因此后续年度
只能称冻结规则的 chronological validation，不称资产层面的 pristine OOS。

## 数据与时序

- 主市场：OKX `DOGE-USDT-SWAP` 原生闭合 5m OHLCV。
- 确认市场：OKX `DOGE-USDT` 原生闭合 5m OHLCV。
- 发现窗口：`2021-01-01 <= ts < 2024-01-01`，数据库查询硬截止 2024。
- 两序列按 bar open timestamp 取交集，不补值。
- 信号只读 bar `t` 的 close/volume，在 `t+1` 的永续 open 成交。
- 任一执行 bar 的永续成交量为零时不建立新仓；退出 bar 为零则延迟到下一可成交 open。
- 发现门失败后不读取 2024+ 的 SIC 收益。

## 因果特征

主版参数：

- impulse horizon：3 根 bar，即 15 分钟；
- baseline：严格早于当前 bar 的最近 2,016 根 bar，即 7 天；
- `swap_impulse_t = log(swap_close_t / swap_close_{t-3})`；
- `spot_impulse_t = log(spot_close_t / spot_close_{t-3})`；
- `sigma_t`：严格过去 2,016 根永续 5m log return 的样本标准差；
- `shock_score_t = swap_impulse_t / (sqrt(3) * sigma_t)`；
- `volume_ratio_t`：最近 3 根永续 volume 之和，除以严格过去 2,016 根单 bar
  volume 中位数的 3 倍。

空仓且冷却结束时，主版须同时满足：

1. `abs(shock_score_t) >= 4.0`；
2. `volume_ratio_t >= 3.0`；
3. 现货与永续 15m impulse 同号；
4. `abs(spot_impulse_t) >= 0.5 * abs(swap_impulse_t)`；
5. 下一根 open 到下一默认资金费时点严格多于最大持仓时间。

信号为正则持有 `+0.5` 永续账户权重，信号为负则持有 `-0.5`。持有 6 根完整 bar
(30 分钟)，随后在下一根 open 全平；平仓后冷却 6 根 bar。无止盈止损、无移动退出，
避免用 OHLC 内未知路径优化结果。

## 资金费与成本

- 主成本：每边 10 bps fee + 5 bps slippage，共 15 bps；
- 压力成本：每边 10 bps fee + 15 bps slippage，共 25 bps；
- taker-only，不假设 maker 返佣或挂单成交；
- 固定初资 10,000 USDT，入场时按权益的 50% 确定名义仓位，持有期不再平衡；
- long/short 均逐 bar close 盯市；
- 不跨默认 00:00/08:00/16:00 UTC 资金费时点，因此历史回测 funding 记零；
- 若真实合约结算频率调整为 1/2/4 小时，实盘必须按 API 返回的实际下一结算时点避让；
- 任何零成交量导致的延迟退出若跨过资金费时点，计为未建模 crossing 并使门槛失败。

## 冻结邻域与尝试数

family size 固定为 7：

| Version | 与主版唯一差异 |
|---|---|
| main | score=4, volume=3, hold=6, spot confirmation |
| score3 | score threshold=3 |
| score5 | score threshold=5 |
| volume2 | volume ratio=2 |
| volume5 | volume ratio=5 |
| hold3 | hold=3 bars |
| hold12 | hold=12 bars |

不测试去除现货确认的版本，因为那会把机制改成普通单市场短期动量，并扩大尝试族。

## 发现门

main 必须同时满足：

1. 15 bps/边总收益 > 0；
2. 年化 Sharpe >= 0.75；
3. MaxDD <= 20%；
4. 至少 100 笔闭合 episode；
5. 2021、2022、2023 至少两年净收益为正；
6. 25 bps/边压力总收益 > 0；
7. 去最佳一笔静态 PnL 后总收益仍 > 0；
8. episode bootstrap P5 > 0；
9. 七个冻结版本至少五个净收益为正；
10. 相对同年份、同方向、同持仓长度的随机入场，七次尝试 Sidak 校正后单侧
    `p <= 0.10`；
11. 没有未建模资金费 crossing。

任一项失败即 `DISCOVERY FAIL`；不得用最佳邻域替换 main，不得依据后续年份调参。

## 顺序验证门

只有发现门通过才读取 2024 SIC 收益。2024 必须：

- 主成本收益 > 0、Sharpe >= 0.50、MaxDD <= 20%；
- 至少 25 笔；
- 压力成本收益 > 0；
- 去最佳一笔后仍 > 0；
- 无资金费 crossing。

只有 2024 通过才以同一门读取 2025。2026 只可作为冻结诊断，不参与选择。

## 预期失败模式

- 极端 15m 冲击可能是短期过度反应，下一根 open 后反转；
- close-to-next-open gap 可能吃掉全部延续；
- 15/25 bps 单边成本对 30 分钟持仓很重；
- K 线 volume 不区分主动买卖，也无法识别强平流；
- 2021 的高波动制度可能再次独占结果；
- 默认资金费时刻无法代表历史上所有自动调整后的实际结算时刻。

即使全部过门，本版本也只能进入实时盘口 shadow，不能直接批准真实资金。
