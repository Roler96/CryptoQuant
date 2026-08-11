# URA v1 Mode-B 结果审计

- 日期：2026-08-10
- 裁决：`VALID`
- 审计对象：`reports/research/ura_v1.json`
- 盈利性裁决：未进行；本审计只确认 capacity-gated discovery 结果

## 独立复核

- 数据：38,688 根 DOGE-USDT 1h，冻结 SHA-256 匹配。
- 条件漏斗：38,639 个边界合格 decision → 38,581 个已知正量窗口 → 2,902 个上沿占用窗口 → 2,567 个同时满足下沿限制 → 699 个当前仍在上四分位 → 535 个未突破旧 high 的 raw signals → 167 个不重叠 accepted episodes。
- 五个冷启动段：2021=28、2022=38、2023=43、2024=44、2025 partial=14。
- G1 两处失败：连续样本 167<200；2025 partial 14<20。
- 10 根零量 bar 已盘点；所有 accepted entry/exit bar 均通过正量检查。
- runner 在 G1 失败后、调用 `run_ura()` 之前立即返回；没有计算 main return、Sharpe、MaxDD、buy-and-hold、stress、邻域、消融、bootstrap 或 matched-random。
- 查询上界固定为 `2025-06-01T00:00:00Z` exclusive；holdout 未访问。
- URA 定向测试 12 项通过；全仓测试 449 项通过。
- 复审补充：G2 signed MaxDD、严格 segment exit 边界和 null volume eligibility 均已修正；未执行的 Monte Carlo 分支进一步钉死为 `NumPy==2.4.6` 及精确 RNG 调用顺序。该补充发生在 G1 短路之后，不改变任何已执行计数或裁决。

## 裁决

`DISCOVERY_FAIL` 有效。URA v1 因冻结的样本容量门失败而关闭；不能降低占用阈值、缩短持有期、提升 raw-signal 消融或读取 holdout 来救援该候选。
