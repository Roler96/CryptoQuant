# CryptoQuant 策略研究路线图

> 基于学术文献、行业实践和加密市场微观结构特性的前沿策略调研
> 最后更新: 2026-05-14

---

## 一、当前策略评估

| 策略 | 问题 |
|------|------|
| SMA/EMA 交叉 | 所有人都在用，信号延迟，震荡市反复止损 |
| RSI 过滤 | 仅作辅助，单独无 alpha |
| 布林带 | 教科书策略，参数敏感，crypto 波动率结构不适用正态假设 |
| MACD | 本质还是双均线，加了一层延迟 |
| 基础配对交易 | 只用价格比 z-score，忽略协整动态变化，crypto 相关性不稳定 |

**核心问题**: 这些策略都在"价格时序"上做文章，而 crypto 市场真正的 alpha 来自其**独特的市场结构**——永续合约、资金费率、链上数据、清算机制等。

---

## 二、高优先级策略 (推荐实现)

### 策略 1: 资金费率套利 / 资金费率动量

**核心逻辑**:
- 永续合约 (perpetual futures) 是 crypto 独有的衍生品
- 资金费率 (funding rate) = 多空力量平衡的温度计
- 当 funding rate 极端正 (如 +0.1%)，多头过度拥挤，未来有:
  - 均值回归: rate 向 0 收敛 → 做空 perp + 做多 spot (delta-neutral 收费率)
  - 预测性: 极端正费率往往预示短期回调 (多头被清算)

**两种子策略**:

**1a. Delta-Neutral 费率收割**
- 逻辑: Long spot + Short perp → 每小时收正 funding
- Edge: 市场结构性存在 — 大多数散户只做多 perp (杠杆)，专业方收费率
- Sharpe: 文献报告 1.5-3.0 (年化，主要靠稳定收费而非价格收益)
- 风险: 现货与合约价差 (basis risk)、交易所风险、极端行情 basis 剧烈变化
- 数据需求: funding rate (OKX API `fundingRate`)、现货/合约价格
- 复杂度: **中** — 需要同时管理 spot + perp 仓位

**1b. 费率动量 / 反转信号**
- 逻辑: 
  - 极端正 funding (>0.05%) → 未来 4-24h 价格大概率回调
  - 极端负 funding (<-0.05%) → 未来价格反弹
  - 费率变化率 (Δfunding) 比绝对值更有预测力
- Edge: 杠杆交易的清算机制创造了均值回归压力
- Sharpe: 0.8-1.5 (单边，结合其他信号可提升)
- 风险: 趋势行情中费率可能长期偏离 (如牛市中 funding 持续正值)
- 数据需求: 历史 funding rate 时间序列
- 复杂度: **低** — 可以融入现有 CTA 框架作为过滤/确认信号

**参考**:
- "Fundamentals of Perpetual Futures" (arXiv:2212.06888)
- "Designing funding rates for perpetual futures" (arXiv:2506.08573)

---

### 策略 2: 清算级联预测 (Liquidation Cascade)

**核心逻辑**:
- Crypto 市场杠杆率极高 (OKX 最高 125x)
- 价格下跌 → 触发高杠杆多头清算 → 级联抛售 → 更大跌幅
- 这是 crypto 独有的微观结构特征，传统市场没有如此集中的杠杆
- **在级联发生前布局，或在级联末端抄底**

**实现方案**:
- 估算各价位杠杆分布 (基于 open interest + liquidation 价格推算)
- 当价格接近密集清算区 + funding rate 极端 + OI 快速增长 → 高概率级联
- 信号: 清算密集区作为"磁铁价格" — 价格被吸向清算区
- 级联后反转: 大量清算完成后 OI 下降 → 抛压耗尽 → V 型反转

**Edge 来源**:
- 大多数散户不看清算分布
- 清算级联在 crypto 的频率和幅度远超传统市场
- 可以从公开数据 (OI, funding, mark price) 推算清算地图

**Sharpe**: 0.5-1.2 (预测准确率有限，但单次盈亏比高)
**数据需求**: Open Interest (OKX API)、标记价格、funding rate
**复杂度**: **高** — 需要构建清算价格模型，实时监控 OI 变化

---

### 策略 3: 波动率体制转换模型 (Markov Regime-Switching)

**核心逻辑**:
- 现有的 RegimeDetector 用 ADX+CHOP 做硬阈值分类，太粗糙
- Crypto 市场在"低波动-高波动"之间频繁切换，且转换有持续性
- Markov Regime-Switching 模型可以:
  - 概率化当前状态 (而非硬分类)
  - 预测下一期状态转换概率
  - 在不同状态下使用不同策略参数

**实现方案**:
- 两状态 (低波动/高波动) 或三状态 (低/中/高) Markov 模型
- 观测量: 收益率 + 已实现波动率
- 用 Hamilton Filter 估计状态概率
- 状态概率直接驱动仓位大小 (高波动 → 减仓) 和策略切换

**Edge 来源**:
- 比 ADX/CHOP 硬阈值更准确地捕捉体制转换
- 概率化输出比二值信号更有用 — 可直接用于仓位管理
- 体制持续性 (regime persistence) 是 crypto 的显著特征

**Sharpe**: 不是直接交易策略，而是**元策略** — 提升现有策略 20-40% Sharpe
**数据需求**: 仅需 OHLCV (已有)
**复杂度**: **中** — 需要实现 EM 算法或用 statsmodels

**参考**:
- Hamilton (1989) "A New Approach to the Economic Analysis of Nonstationary Time Series"
- Haas et al. (2004) "Markov switching in GARCH processes"

---

### 策略 4: 多因子信号框架 (替代单指标策略)

**核心逻辑**:
- 当前策略是"如果 A 交叉 B，则买入"这种单指标逻辑
- 更好的方式: 构建因子 → 打分 → 综合信号
- 将现有指标 (MA趋势、RSI、ADX、ATR) + 新因子 (funding、OI变化、波动率体制)
  全部归一化为 [-1, 1] 的因子分数，加权综合

**因子列表 (按优先级)**:

| 因子 | 数据源 | 预测方向 | IC (估计) |
|------|--------|----------|-----------|
| 资金费率极值 | OKX funding API | 反转 | 0.05-0.10 |
| OI 变化率 | OKX OI API | 动量/反转 | 0.03-0.07 |
| 波动率体制概率 | OHLCV 计算 | 仓位管理 | 0.02-0.05 |
| 成交量偏离 | OHLCV | 趋势确认 | 0.02-0.04 |
| MA 趋势分数 | OHLCV | 趋势 | 0.01-0.03 |
| 短期反转 (1-3 bar) | OHLCV | 均值回归 | 0.03-0.06 |
| 日内模式 (hour-of-day) | OHLCV | 季节性 | 0.01-0.03 |

**Edge 来源**:
- 多因子分散风险，不依赖单一信号
- 因子权重可以定期优化 (walk-forward)
- 新因子 (funding, OI) 是 crypto 独有 alpha

**Sharpe**: 1.0-2.0 (多因子组合后)
**数据需求**: OHLCV + funding rate + OI
**复杂度**: **中** — 需要因子归一化和权重优化框架

---

## 三、中优先级策略

### 策略 5: BTC 主导率轮动 (Dominance Rotation)

**核心逻辑**:
- BTC.D (BTC dominance) 上升时 → 资金流入 BTC → ALT 弱势
- BTC.D 下降时 → 资金外溢到 ALT → ALT season
- 用 BTC.D 的趋势预测 ALT/BTC 的相对表现
- 配对: Long ALT + Short BTC (或反过来)

**Edge**: Crypto 独有的宏观指标，传统市场没有对应物
**Sharpe**: 0.5-1.0
**复杂度**: 中

### 策略 6: 链上数据信号 (On-Chain Alpha)

**核心逻辑**:
- 大额 BTC 转入交易所 → 未来 24-72h 卖压增加
- 交易所 BTC 净流出 → 长期看涨
- 稳定币供应量变化 → 资金进出市场的前瞻指标
- MVRV > 3.5 → 市场过热; MVRV < 1 → 低估区

**Edge**: Crypto 特有的透明链上数据，传统市场无法获得
**Sharpe**: 0.5-1.5 (取决于信号质量和执行)
**复杂度**: 高 — 需要接入链上数据 (Glassnode/CryptoQuant API)
**数据需求**: 链上数据 API (月费 $30-100)

### 策略 7: 已实现 vs 隐含波动率差 (Volatility Risk Premium)

**核心逻辑**:
- BTC 期权隐含波动率 (IV) 通常 > 已实现波动率 (RV)
- 这个差值就是波动率风险溢价 (VRP)
- 策略: 卖出跨式期权 (short straddle) 收取 VRP
- 或: IV/RV 比率作为方向信号 (IV 极高 → 市场恐慌 → 做多)

**Edge**: VRP 在传统市场已被证实存在，crypto 中更显著
**Sharpe**: 1.0-2.0 (但尾部风险大)
**复杂度**: 高 — 需要期权交易能力
**数据需求**: 期权 IV 数据 (Deribit API)

---

## 四、低优先级 / 未来方向

| 策略 | Edge | 难度 | 备注 |
|------|------|------|------|
| 跨交易所套利 | 价差 | 低 (但需要极速) | Alpha 被量化团队吃尽 |
| MEV / DEX 套利 | 链上 | 极高 | 需要链上基础设施 |
| LLM 交易 Agent | 信息处理 | 高 | 研究热点但 alpha 未验证 |
| 网格交易 | 震荡收益 | 低 | 本质不是 alpha，是卖波动率 |
| 反身性策略 | 市场情绪 | 高 | 有趣但难以系统化 |

---

## 五、推荐实施路线

### Phase 1: 快速见效 (1-2 周)
1. **资金费率信号模块** — 融入现有 CTA 策略作为过滤/确认
2. **多因子打分框架** — 替代单一指标逻辑
3. 在 BacktestEngine 中注册新策略

### Phase 2: 核心升级 (2-4 周)
4. **Markov Regime-Switching** — 替换现有 RegimeDetector
5. **清算分布估算器** — 构建 liquidation map 模型
6. **费率套利策略** (delta-neutral) — 需要同时管理 spot + perp

### Phase 3: 数据扩展 (4-8 周)
7. **OKX API 扩展** — 接入 funding rate, OI, mark price
8. **链上数据接入** — Glassnode 或 CryptoQuant API
9. **BTC.D 轮动策略**

---

## 六、关键数据需求

现有数据: OHLCV (10 对, 1h/4h/1d)

需要新增:
| 数据 | OKX API 端点 | 用途 | 优先级 |
|------|-------------|------|--------|
| Funding Rate | `GET /api/v5/public/funding-rate` | 费率策略 | P0 |
| Open Interest | `GET /api/v5/public/open-interest` | 清算/杠杆分析 | P0 |
| Mark Price | `GET /api/v5/public/mark-price` | 基差计算 | P1 |
| Ticker (24h) | `GET /api/v5/market/ticker` | 实时价格 | P1 |
| Long/Short Ratio | `GET /api/v5/rubik/stat/contracts/long-short-account-ratio` | 多空比 | P2 |
| Liquidation (历史) | `GET /api/v5/rubik/stat/contracts/liquidation` | 清算级联 | P2 |

---

## 七、学术参考文献

1. "Fundamentals of Perpetual Futures" - arXiv:2212.06888
2. "Designing funding rates for perpetual futures" - arXiv:2506.08573
3. "AutoQuant: Execution-Constrained Auto-Tuning in Crypto Perpetual Futures" - arXiv:2512.22476
4. Hamilton, J.D. (1989) "A New Approach to the Economic Analysis of Nonstationary Time Series"
5. Haas, M. et al. (2004) "Markov switching in GARCH processes"
6. Liu, Y. et al. (2022) "Cryptocurrency Liquidity and Volatility Interactions"
7. Alexander, C. et al. (2022) "The implied volatility of Bitcoin" - VRP in crypto
