# NFRR v1 执行状态（2026-08-10）

- 协议：`NEGATIVE_FUNDING_RESILIENCE_REBOUND_PROTOCOL_2026-08-10.md`
- 状态：`MODE-A NOT-FIT / DATA_UNAVAILABLE / NOT RUN`
- 候选收益：未读取
- Holdout：未访问

NFRR v1 需要 OKX `2022-04..2025-06` 官方 DOGE 永续 funding 月档。当前仓库只有 2026-04 之后的 354 条滚动 funding 记录；本机配置的 HTTP 代理不可达，绕过代理直连 OKX 静态档案又被远端重置，且本机不存在旧月档副本。

因此不能用短窗口、预测 funding、其他币种档案或已见 holdout 代替冻结输入。NFRR v1 在任何信号、交易或收益计算前停止，所有门记为 `NOT_RUN`，不形成策略结论。

后续独立 Mode-A 审计另确认该协议仍有阻塞性歧义，包括未来零量过滤造成的非因果性、`R8` close 索引差一小时、主评价区间不明确，以及 target-position 接口无法表达同一 open 退出后重入。因此即使未来补齐 funding 档案，也不得按 v1 原协议运行；必须作为新版本重新冻结并重新审计。
