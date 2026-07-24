# DOGE 现货 5m 下破回收（DLSR v1）工程记录

**ENGINEERING STATUS: COMPLETE。** 本记录只说明策略实现、测试和现有框架干跑是否
完成；不作 keep/kill 或研究结论。协议已经模式 A 预注册裁判判为 FIT。

## 实现边界

- 策略实现：`cq/strategy/doge_dlsr.py`
- 合成测试：`tests/test_doge_dlsr.py`
- 工程干跑入口：`scripts/dry_run_doge_dlsr.py`
- DLSR 实现没有要求修改 `cq/core/types.py`、`cq/engine/loop.py` 或
  `cq/data/feed.py`；策略仍直接走既有 `run_backtest`。
- 干跑入口通过只读 SQLite 连接直接读取 `(DOGE-USDT, 5m)`，构造 `Series` 后调用既有
  `run_backtest`；没有从 1h 制造 5m。
- 调用参数显式固定为现货 `MarketSpec("DOGE-USDT", "spot")`、
  `Sizing.ON_ENTRY`、`NoFunding()`、初始资金 10,000 USDT、每边
  fee 10 bps + slippage 5 bps。

最终源码 SHA256：

| 文件 | SHA256 |
|---|---|
| `cq/strategy/doge_dlsr.py` | `2e407bd773d268cf0f53a1943f423c367c1233d307b72ec48e09aa87e38dd2de` |
| `tests/test_doge_dlsr.py` | `94b12e2aa86f440deb2e5ff0dfc8b726b199c9ae67aaa000dd60b57f4c0cd9a7` |
| `scripts/dry_run_doge_dlsr.py` | `8a0d04a4d660991c0eab4e99f11132c6fa15ae2dc76d9068d093e6f0eb018f4d` |

## 执行语义

策略只返回框架原有的 `Intent(target, reason)`，目标集合为 `{0, 0.25}`。
信号在闭合 bar `t` 产生，由现有引擎在 `t+1` open 执行。

现有引擎会把未成交 pending target 顺延。对连续数据，策略在零成交量入场 bar 的 close
立即返回目标 0，从而消费事件并覆盖 pending，禁止追单；零成交量退出则持续返回目标 0，
由引擎在下一根正成交量 bar open 重试。

协议规定缺 bar 时使用恢复 bar open，但策略在该 open 成交之后才有机会看到时间戳缺口。
为避免修改共享引擎或静默使用晚一根的近似，DLSR 检测到任意非连续 5m 时间戳就立即
raise，使该 run 不可能产出结果。干跑入口还在调用引擎前检查全窗连续性。

## 测试

2026-07-24 本地执行：

```text
tests/test_doge_dlsr.py: 25 passed
pytest -m "not integration": 497 passed
ruff（DLSR 策略、测试、干跑入口）: passed
pyright standard（同上）: 0 errors
```

覆盖信号六条件、严格过去基线、成交时序、12-bar 持有、144-bar 冷却、零量入场作废、
零量退出顺延、warmup 前后缺口拒绝、非法 OHLC、目标非负、快照恢复、7 个冻结版本、
非 DOGE/非 5m 拒绝、`Sizing.ON_ENTRY` 框架调用和确定性。

## 现有框架全窗干跑

执行：

```text
.venv/bin/python scripts/dry_run_doge_dlsr.py
```

输出仅含结构事实：

```text
framework dry-run: completed
window: [2021-01-01, 2025-06-01)
bars: 464256
series fingerprint: f03422936d014ffc
```

终点硬编码为 `FORWARD_FREEZE`，SQLite 以 `mode=ro` 打开；未读取
`>= 2025-06-01` 的验证窗，未调用 `forward_holdout`，未写 holdout access 记录。
干跑没有访问或汇总 fills、equity、returns、Sharpe、MaxDD、胜率等绩效字段。

## 后续条件

按冻结协议执行 discovery；仅 discovery 全部门槛通过后，才允许先登记
`record_holdout_access`，再通过 `forward_holdout` 顺序读取验证窗。FIT 不等于盈利，
工程干跑也不构成研究发现。
