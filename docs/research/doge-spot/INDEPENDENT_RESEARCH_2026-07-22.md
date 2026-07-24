# DOGE 自身数据独立策略研究结论 (2026-07-22)

> **后续审计更新：** VCSE v1 保留原“历史探索通过”记录，但强化稳健性门为
> `ROBUSTNESS FAIL`；受污染的简化 v2 也为 `EXPLORATION FAIL`。当前仍不批准真实资金，
> 且 v1 只保留低优先级冻结 shadow 记录。详见
> `docs/research/doge-spot/CONTINUED_RESEARCH_2026-07-22.md`。
> 安全 forward 边界也已按 v1 实际提交时间收紧到第一根完全位于其后的4h bar：
> `2026-07-22 08:00 UTC`。

## 结论

本次独立提出并预注册了 **DOGE VCSE (Volatility Compression-Spot Expansion)**。策略只读取 OKX `DOGE-USDT` 现货 OHLCV，不读取 BTC、ETH、DOGE 永续、资金费、OI、旧策略信号或旧研究参数。

固定主策略在15 bps/边历史探索中达到预注册门槛：

- Return `+383.81%`
- CAGR `+32.87%`
- Sharpe `0.95`
- MaxDD `-38.00%`
- 46个闭合交易
- Profit Factor `2.12`
- 去掉最佳一笔后的静态收益 `+264.00%`
- episode bootstrap P5 `+2.53%`，历史路径亏损概率 `4.76%`
- 六个自然年全部为正，但2023和2026接近持平

因此它可以登记为 **forward shadow-paper hypothesis**，但不能批准真实资金。

## 独立机制

研究假设不是旧仓库的暴跌反弹、Donchian+SMA、BTC冲击或Union Router，而是：

1. DOGE现货自身波动率进入历史低分位，代表暂时供需平衡；
2. 随后出现向上价格突破；
3. 突破bar同时表现为区间扩张、强势收盘和现货成交量扩张；
4. 若需求冲击是真实的，价格应在未来数日至十日延续，而不是立即回到区间。

固定入场：

- 4h `ATR18%` 最近3根内低于各自过去540根的20%分位；
- close突破前30根high；
- True Range > 前一根ATR18的1.25倍；
- CLV ≥ 0.70；
- volume ≥ 前30根中位数的1.50倍；
- 当前bar收盘决策，下一根4h open成交。

固定退出：

- close跌破前10根low；或
- close低于持仓最高收盘减3倍ATR18；或
- 持有达到60根4h bar；
- 所有策略退出均在下一根open成交，不假设未知的bar内路径。

完整冻结规格：`docs/research/doge-spot/VCSE_PREREGISTRATION_2026-07-22.md`。

## 历史结果

| Year | Return | Sharpe | MaxDD | Closed trades |
|---:|---:|---:|---:|---:|
| 2021 | +40.37% | 1.22 | -16.52% | 5 |
| 2022 | +54.15% | 1.08 | -33.42% | 8 |
| 2023 | +0.46% | 0.13 | -29.36% | 8 |
| 2024 | +96.36% | 1.73 | -38.00% | 8 |
| 2025 | +11.47% | 0.49 | -27.55% | 13 |
| 2026 | +1.69% | 0.25 | -14.31% | 4 |

### 成本压力

| Cost/side | Return | Sharpe | MaxDD |
|---:|---:|---:|---:|
| 15 bps | +383.81% | 0.95 | -38.00% |
| 25 bps | +341.29% | 0.91 | -38.62% |
| 50 bps | +250.62% | 0.79 | -40.13% |

### 25%风险仓位对照

固定规则不变，只把target从1.0缩到0.25：

- Return `+65.38%`
- CAGR `+9.49%`
- Sharpe `0.84`
- MaxDD `-15.31%`
- Profit Factor `2.59`
- bootstrap P5 `+5.15%`
- 去最佳一笔后 `+40.35%`

仓位缩放没有创造edge，只把全仓策略转成更可承受的风险曲线。

## 参数平原

12个预注册单因素邻域全部盈利，Sharpe范围 `0.72–1.19`：

- compression分位15/25%；
- breakout 24/36 bars；
- expansion 1.00/1.50；
- volume 1.25/1.75；
- trailing ATR 2.5/3.5；
- max hold 42/78 bars。

不存在单一孤立参数尖峰。收益最好的邻域是42-bar最大持仓，但由于结果已经被看到，不允许把它替换成冻结主参数。

## 消融解释

| Variant | Return | Sharpe | MaxDD | Trades |
|---|---:|---:|---:|---:|
| Full VCSE | +383.81% | 0.95 | -38.00% | 46 |
| No compression | +509.76% | 0.82 | -63.37% | 90 |
| No volume | +390.71% | 0.96 | -38.00% | 47 |
| No CLV | +1650.28% | 1.23 | -38.65% | 55 |
| Breakout only | +1206.76% | 1.03 | -60.82% | 117 |
| Buy and hold | +1393.65% | 0.97 | -92.94% | open |

可支持的机制结论：

- **压缩过滤具有风险管理价值**：它将MaxDD从breakout-only的约61%和no-compression的约63%降到38%，并提高PF和bootstrap稳定性。
- **成交量确认没有明显增量**：去掉它后结果几乎不变。
- **CLV确认在历史上是负贡献**：去掉后收益和Sharpe都更高。这是结果出来后的发现，只能登记为下一代假设，不能回头修改VCSE v1。
- **完整VCSE没有在Sharpe上显著超过buy-and-hold**：0.95 vs 0.97；它的价值主要是将MaxDD从约93%降到38%，不是证明了强alpha。

## 集中度与主要风险

主策略去掉最佳1笔仍为 `+264%`，去掉最佳3笔仍为 `+72%`，但去掉最佳5笔转为 `-77%`。前五笔对结果具有决定性影响。

最佳交易包括：

| Entry | Exit | Trade return | Hold |
|---|---|---:|---:|
| 2024-02-26 | 2024-03-05 | +53.81% | 8.0d |
| 2022-10-25 | 2022-11-04 | +95.01% | 9.5d |
| 2025-09-07 | 2025-09-15 | +19.59% | 7.7d |
| 2024-10-14 | 2024-10-24 | +23.29% | 10.0d |
| 2025-05-08 | 2025-05-13 | +15.02% | 4.5d |

这符合DOGE趋势策略的右尾结构，但也意味着46笔交易远不足以确认稳定期望值。

## 证据边界

1. 数据截止于 `2026-07-20 06:00 UTC`，恰好没有可用于本次研究的冻结后样本。
2. 历史数据此前已被其他DOGE研究反复查看；虽然VCSE公式独立提出并在看本次结果前预注册，仍不能把历史结果称为真正OOS。
3. 内部测试通过不能替代外部成交、容量和执行偏差验证；VCSE数字只能用于候选排序。
4. episode bootstrap把交易视为可重采样事件，无法消除制度变化、时间聚集和研究者自由度。
5. 预注册历史门槛的最后一项过于宽松：breakout-only收益明显更高，但Sharpe仅比完整策略高0.08，因此形式上通过“高0.10才算明显占优”的阈值。这项通过不应被解读为完整机制得到强证明。

## 决策

状态：**历史探索通过，批准进入forward shadow paper；不批准真实资金。**

冻结forward版本必须保留本次主参数，不能采用事后表现更好的`no_clv`、42-bar持仓或其他邻域。至少积累30个新的闭合交易后一次性裁决：

- 实际成本后收益为正；
- 25 bps/边压力仍为正；
- block bootstrap单侧95%下界大于0；
- backtest与paper对每根bar的target和成交时序一致；
- 在达到样本量前不调参数、不切换到消融版本。

## 可复现文件

- 预注册：`docs/research/doge-spot/VCSE_PREREGISTRATION_2026-07-22.md`
- 研究实现：`research/backtest_doge_vcse.py`
- 因果测试：`tests/test_vcse_research.py`
- 完整JSON：`reports/research/doge_vcse_results.json`
- 自动报告：`docs/research/doge-spot/VCSE_RESULTS_2026-07-22.md`

验证：

```text
5 targeted tests passed
429 non-integration tests passed
ruff: all checks passed
pyright: 0 errors
```
