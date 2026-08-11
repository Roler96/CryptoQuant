# PIRD v2 / PIRD-L v1 — DOGE 5m 开放开发结果

日期：2026-08-11
PIRD v2状态：`TWO-SIDED DEVELOPMENT FAIL`
PIRD-L v1状态：`DEVELOPMENT SURVIVOR — AWAITING FORWARD CONFIRMATION`

## 1. 结论

原始双向 PIRD v2 没有通过：低残差阈值下虽然存在每笔约3–7 bps的毛反转，但无法覆盖30 bps往返成本，且short方向持续亏损。

开放探索显示 residual 强度提高时 expectancy 单调改善；`z>=8` 后开始覆盖成本，`z=9–10` 形成平台。方向分解进一步表明，全部优势来自“负 residual overshoot 后做多”，即下跌方向的传播子外异常冲击回归。

因此双向PIRD被否决，同时产生一个独立的自适应后代：

`PIRD-L v1 = downside flow-aligned residual overshoot reversal`

选中开发配置：

```text
W=4032 bars（14天）
tau=12 bars（真实半衰期1小时）
z_resid=9
side=long only
hold=12 bars（1小时）
target_weight=25%
entry/exit=next 5m open
cost=15 bps/side
```

## 2. 数据与搜索谱系

- 市场：`DOGE-USDT-SWAP`
- 原生周期：5m
- 数据：589,930根连续bar，2021-01-01至2026-08-11
- 输入：DOGE自身标准OHLCV
- 历史均为已见research pool，不是OOS或forward数据

Trial ledger共144项：

- 12项原始结构扫描；
- 48项自适应residual强度扩展；
- 24项双向持有期诊断；
- 60项负residual long-only响应面。

后续的高阈值和long-only分支均由已见结果启发，不能冒充预先冻结证据。

## 3. 双向PIRD v2结果

初始 `z in {3,4}`、`H=12` 的12个配置：

- 0/12净收益为正；
- 0/12 Sharpe为正；
- 12/12 long与short净PnL均为负；
- 六个自然年均无正收益配置；
- 最佳单笔净均值为-22.85 bps；
- 最佳Sharpe为-2.189。

但12/12配置毛均值为正，说明存在很弱的反转现象，只是远小于交易成本。

强度扩展表现：

| residual z | Episodes范围 | 最佳净均值 | 最佳毛均值 | 最佳Sharpe |
|---:|---:|---:|---:|---:|
| 3 | 4,021–4,645 | -22.85 bps | +7.15 bps | -3.479 |
| 4 | 2,349–2,708 | -23.89 bps | +6.11 bps | -2.189 |
| 5 | 1,377–1,678 | -16.78 bps | +13.22 bps | -1.039 |
| 6 | 861–1,100 | -10.28 bps | +19.72 bps | -0.523 |
| 7 | 554–736 | -1.13 bps | +28.87 bps | -0.053 |
| 8 | 371–513 | +8.97 bps | +38.97 bps | +0.270 |
| 10 | 185–260 | +35.33 bps | +65.33 bps | +0.675 |

效应随residual强度增强，但双向结果被亏损的short侧拖累，因此不能保留原双向规格。

## 4. PIRD-L v1主结果

向传播子预测方向发生极端负residual时做多，持有1小时：

| 指标 | 结果 |
|---|---:|
| Episodes | 148 |
| Shared-engine Return | +34.64% |
| Shared-engine Daily Sharpe | 1.166 |
| Shared-engine MaxDD | -8.16% |
| Win rate | 56.76% |
| Shared-engine Profit factor | 2.344 |
| 单笔净均值 | +82.15 bps |
| 正收益自然年 | 5/6 |
| 最佳5笔占正PnL | 32.65% |

向量化episode账户给出+34.72%、Sharpe 1.170、realized-only MaxDD -3.45%。共享引擎逐bar盯市后MaxDD扩大到-8.16%，因此风险结论以共享引擎为准。

自然年：

| 年份 | Episodes | Return |
|---|---:|---:|
| 2021 | 18 | +14.63% |
| 2022 | 14 | -1.22% |
| 2023 | 35 | +1.96% |
| 2024 | 29 | +4.52% |
| 2025 | 34 | +8.41% |
| 2026部分 | 18 | +2.97% |

2022为轻微负收益，因此候选不是“六年全正”；它仍只能作为开发候选。

## 5. 参数平台

### residual阈值平台（W=4032, tau=12, H=12）

| z | Episodes | Return | Sharpe | MaxDD |
|---:|---:|---:|---:|---:|
| 8 | 199 | +29.2% | 0.986 | -3.0% |
| 9 | 148 | +34.7% | 1.170 | -3.4% |
| 10 | 108 | +29.1% | 1.044 | -3.6% |
| 12 | 58 | +25.3% | 0.984 | -3.7% |

### 持有期邻域（W=4032, tau=12, z=9）

| Hold | Episodes | Return | Sharpe | MaxDD | 净均值 |
|---:|---:|---:|---:|---:|---:|
| 30m | 153 | +21.6% | 0.959 | -3.62% | +52.17 bps |
| 1h | 148 | +34.7% | 1.170 | -3.45% | +82.15 bps |
| 2h | 145 | +30.2% | 0.934 | -4.00% | +74.88 bps |

`z=9,H=1h`位于宽平台内部，不是孤立尖峰。`tau=6,W=4032,z=9,H=1h`仍有+20.0%收益、Sharpe 0.833。

## 6. 成本压力

向量化账户结果：

| 成本 | Return | Sharpe | 单笔净均值 |
|---|---:|---:|---:|
| 15 bps/side | +34.72% | 1.170 | +82.15 bps |
| 20 bps/side | +29.8% | 1.037 | +72.15 bps |
| 25 bps/side | +25.1% | 0.900 | +62.15 bps |

候选在25 bps/side下仍为正，但Sharpe下降到0.90。

## 7. 机制消融

| 版本 | Episodes | Return | Sharpe | MaxDD | 净均值 |
|---|---:|---:|---:|---:|---:|
| PIRD-L主规格 | 148 | +34.7% | 1.170 | -3.45% | +82.15 bps |
| 同事件顺residual | 148 | -41.3% | -1.892 | -41.3% | -142.15 bps |
| Raw-return reversal | 677 | +69.0% | 0.824 | -22.2% | +34.82 bps |
| 无记忆flow | 156 | +29.4% | 0.964 | -5.90% | +67.69 bps |
| 去掉高活动门 | 148 | +34.7% | 1.170 | -3.45% | +82.15 bps |
| 纯CLV flow | 0 | 0 | 0 | 0 | 0 |

解释：

- 反转方向明显优于延续，符合瞬态overshoot预测；
- 普通极端下跌反转总收益更高，但事件多4.6倍，Sharpe、回撤和单笔质量明显较差；
- 无记忆flow仍盈利，但传播子状态提高了Sharpe、单笔收益和年度稳定性；
- 高活动门在最终高z规格中完全冗余，应在未来冻结版本中删除，而不是保留无效条件；
- 纯CLV无法形成同规格事件，成交活动幅度是模型拟合的一部分。

## 8. 与DSPR的独立性

- PIRD-L接受episodes：148
- DSPR接受episodes：120
- 同decision timestamp重叠：0
- Jaccard overlap：0.0

DSPR要求多bar下跌后当前bar已经阳线部分恢复；PIRD-L在当前负residual仍沿下跌方向扩张时入场。两者的状态和时点不同，不是同一信号的阈值改名。

## 9. 共享引擎对账

使用因果向量化特征生成161个原始decision timestamp，再由共享引擎执行持仓互斥、next-open成交、25% ON_ENTRY sizing、15 bps/side成本和逐bar权益盯市：

- 148 episodes，296 fills；
- Return +34.64%；
- Daily Sharpe 1.166；
- MaxDD -8.16%；
- Win rate 56.76%；
- Profit factor 2.344；
- 0 rejection；
- 最终flat；
- 数据fingerprint：`e74eba06efed1125`；
- 引擎：`cq-engine/1`。

Return、Sharpe、episode数和胜率与向量化研究路径一致；MaxDD差异来自共享引擎对持仓期间未实现损益逐bar盯市，简单研究账户只在退出时记账。

## 10. 裁决

- `PIRD v2 two-sided = DEVELOPMENT_FAIL`
- `PIRD-L v1 = DEVELOPMENT_SURVIVOR — AWAITING FORWARD CONFIRMATION`

PIRD-L通过开发经济性、参数平台、成本压力、集中度和核心机制消融，但整个历史已经参与自适应搜索，并且候选是查看方向分解后形成的后代。不能部署，也不能称为确认有效。

下一步只能冻结最终简化规格并收集独立forward事件；同一历史不能再作为确认样本。
