# AGENTS.md — CQuant

面向所有在本仓库工作的 AI agent 的入口说明（工具无关）。专用 agent 规范放在
`.agents/`，本文件是索引 + 全仓不可违反的铁律。

## 仓库定位
- `cq/` 是 `fable` 分支从零重建的研究平台（新包名，**不读、不移植** `master` 的
  旧 `cryptoquant/`）。统一事件驱动：回测=实盘同一撮合循环，只换 broker。
- 标的宇宙仅 **OKX 的 BTC/ETH/DOGE 现货 + USDT 线性永续**；不做山寨、不做多交易所。
- 数据在 `data/cq.db`（SQLite，Git LFS）。研究协议与结论在 `docs/research/`。

## 全仓铁律（任何 agent 都必须遵守）
1. **数据隔离**：单一事实源是 `cq/research/split.py`，`FORWARD_FREEZE = 2025-06-01`。
   探索只用 `< 2025-06-01`；`>= 2025-06-01` 是验证窗，读取须经 `forward_holdout` +
   `record_holdout_access`（读的次数=多重检验校正）。时间终点硬编码，禁止用 `latest`。
2. **无前视架构**：策略只见 `Context` 游标切片；信号读闭合 bar `t`，`t+1` open 成交；
   多周期门控由 `core/clock.py` as-of 对齐。现货 `target < 0` 直接 raise。
3. **衍生数据浅历史**：funding/OI 只有数月真实深度，**绝不 forward-fill 到早期年份**；
   资金费口径显式声明 `off` / `actual` / `assumed:<bps>`。

## 专用 agent
- **strategy-proposer** — 见 [`.agents/strategy-proposer.md`](.agents/strategy-proposer.md)。
  按研究协议**只提案**：产出可预注册的 `*_PROTOCOL_*.md`，不实现、不回测、不出数字，
  不读验证数据，不复活已否决家族。
- **strategy-validator** — 见 [`.agents/strategy-validator.md`](.agents/strategy-validator.md)。
  proposer 的对手方，做**方法论审计**：模式 A 预注册裁判把提案判为
  FIT/NOT-FIT；模式 B 取证审计把已完成研究判为 PASS/REJECT，并把可疑数字**复现为缺陷**。
- **strategy-backtester** — 见 [`.agents/strategy-backtester.md`](.agents/strategy-backtester.md)。
  把 FIT 协议实现成 `cq/strategy/*.py`，在统一引擎上执行 discovery+validation，
  产出 RESULTS 后交回 validator 取证。

加载方式：把对应 `.agents/*.md` 全文作为系统提示喂给 agent（Claude Code：`Agent` / 子代理；
Codex 等：作为 instruction 文件加载）。三者构成闭环：**proposer** 产出协议 → **validator** 判 FIT
→ **backtester** 实现并执行、产出 RESULTS → **validator** 取证审计 RESULTS。

> 注意：本文件是**全仓通用**指引，不是某个专用 persona。做一般改动（重构/测试/修 bug）
> 的 agent 读铁律即可；只有明确要"提策略"时才加载 `.agents/strategy-proposer.md`。
