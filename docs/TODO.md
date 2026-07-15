# CryptoQuant 待办清单

> 最后更新: 2026-07-15
>
> **与 `review-2026-07-10.md` 的关系**：那份审查列了 P0/P1/P2 共 22 项，本文档**不复制**它。
> 这里只收两类：
>
> 1. 该审查未覆盖的新发现；
> 2. 该审查已列出、但经实测确认**至今仍未修复**的项。
>
> 每一项的「证据」都是实际跑出来的结果，不是读代码推断的。

---

## P1 — 高优先级

### 1. DogeSpotRegimeSwitch 的残余优势极薄，且没有可用的 OOS 证据

**位置:** `strategies/doge_spot_regime_switch.py`、`config.doge_regime_switch.yaml`

**状态:** 原条目"从未被端到端回测验证过"已于 2026-07-15 处理——基线跑出来了，但过程中发现该策略带 20 小时前视（详见下方已完成）。修复后基线为：

| 分段 | 修正后（切片） | 修正后（冷启动） | 研究笔记声称 |
|---|---|---|---|
| Train | +1317% Sh 0.97 | +1317% Sh 0.97 | +891% Sh 1.15 |
| Val | +16% Sh 0.51 | **+5%** Sh 0.40 | +98% Sh 1.31 |
| Test | +34% Sh 0.97 | **+13%** Sh 0.53 | +131% Sh 2.19 |

**影响:** 修正后仍满足研究笔记自定的「通过标准」（三分段为正、Test Sharpe > 0），但该标准只要求"为正"，极弱。冷启动口径下 Val 一年 23 笔 +5%、Test 一年 13 笔 +13%，与噪声难以区分。且笔记自述该族已接触全样本，**locked test 段已被烧毁**（见记忆 doge-research-protocol）——这些数字不是 OOS 证据。

**建议:** 不要基于重跑历史决定上线。该配置自称"testnet 验证档"，真正的下一步是测试网/纸面交易攒新样本；若要重新评估参数，按协议算新研究，且 test 段只能等新数据。

**复现:**
```
uv run python run_doge_backtest.py --strategy doge_spot_regime_switch \
  --symbol DOGE/USDT --exchange okx --start 2021-01-01 --end 2026-07-12 \
  --resample-from 1h --commission-bps 10 --slippage-bps 2
```

---

## P2 — 中优先级

### 2. "看着在测、实际什么都没测"的空测试需要系统排查

**证据:** 2026-07-14 一次会话中就撞到 **4 例**，全部是绿的。四例均已修（第 4 例于 2026-07-15 修复，见下方已完成）。共同特征：**断言在"函数返回退化值"时依然成立**。

| 位置 | 写法 | 为什么是空的 |
|------|------|--------------|
| `tests/test_fetcher.py` chunk-count 测试 | 喂 4 个 `NetworkError` 却只断言错误信息 | 多余的 side_effect 从未被消费，掩盖了重试失效 |
| `tests/test_doge_spot_donchian_sma.py` | `assert (sig == 0).any()` | 序列本来就全是 0，恒真 |
| `tests/test_doge_spot_regime_switch.py` | `assert (sig == 0).any()` | 同上 |
| `tests/test_p0_regression.py:478` | 测独立装饰器函数 | 没穿过 Broker，测不到真正的 bug |

**建议:** 用"改坏源码，测试是否变红"的方式抽查关键路径测试（历次修复均已用 `git stash` 验证过新测试在旧代码上确实 FAILED）。重点排查 `.any()` / `>= 0` / 只断言异常信息 这几类写法。

---

### 3. 静态检查存量

**ruff:** 已清零（2026-07-14 commit 9829c3e），`uv run ruff check .` 通过。

**pyright — 35 项:** 集中在 `tests/test_position_ledger.py`(14)、`tests/test_closed_bar.py`(7)，其余分散。多为 `reportOptionalMemberAccess`（对 `X | None` 直接取属性）。

---

### 4. `review-2026-07-10.md` 的指标已过期，且需逐项复核

**证据:** 该文档称「Ruff（已跟踪文件）通过」「Pyright 4 errors」，实测当前为 **ruff 0 项、pyright 35 项**。文档还称「测试 494 passed」，当前为 **618 passed**。

另一方面，它列的部分 P0 看起来**已经修了**（`live.py` 里有 `P0: Unknown != Flat` 的注释和对应实现，`tests/test_p0_regression.py` 覆盖了未闭合 K 线、持仓未知、策略持仓归属、PnL 符号、signal_reverse look-ahead 等）。3.4 已于 2026-07-15 修复。

**建议:** 对该审查的 22 项做一次复核，逐项标记 已修 / 未修 / 半修，把仍未修的合并进本文档，然后给审查文档加上"已被 TODO.md 取代"的标注。**3.4 的经验说明"有对应测试"不等于"已修复"** —— 必须实测。

---

## 附：2026-07-15 已完成

- **DogeSpotRegimeSwitch 的 20 小时前视（新发现，原 P1-4 的副产品）**：`_daily_trend()` 用 `resample("1D").last()` 取当日最终收盘、无 shift 地 ffill 回当天全部 4h bar —— 当天 00:00 的 bar 用上了当天 20:00 的收盘。**与 2026-07-14 否决 `DogeSpotDonchianSma` 的是同一个构造**；那次审计的结论只落到了那一个策略上，这个兄弟策略共用同一段代码却没人回头查。同文件里 `_bull_channels` / `_bear_drawdown` / `_vol_filter` 全都 `.shift(1)` 了，只有它漏了；研究笔记还明写「所有通道和均线均 shift(1)」。已加 daily `shift(1)` 修复，并给 `docs/research/doge_regime_switch_2026-07-14.md` 加了审计批注。
  - 测试：`TestDailyGateCausality::test_gate_is_prefix_invariant`（门控在第 i 根的值不得随之后的 bar 变化）。旧代码上抓到 42 处违例。**另有两种写法被试过并否决**，因为它们在坏代码上是绿的：对 `generate_signal()` 做端到端前缀检查（状态机会吸收孤立的门控翻转），以及扰动某天最后一根 bar（是否翻转取决于样本）。
- **回测脚本参数化（原 P1-4 的直接要求）**：`run_doge_backtest.py` 改为 argparse，支持 `--strategy`（按模块名解析）/`--symbol`/`--exchange`/`--start`/`--end`/`--commission-bps`/`--slippage-bps`/`--resample-from`。新增 `--resample-from 1h` 是因为 4h 表只有近一年，而研究口径是 1h 聚合成 4h。策略解析逻辑从 `live_runner.py` 提取到 `cryptoquant/strategy/resolve.py` 由两边共用——避免"同一个名字实盘和回测解析到不同类"。顺带收紧：旧实现按 `dir()` 字母序取第一个 `Strategy` 子类，模块里 import 进来的策略类可能胜出；现在只认本模块定义的，且多于一个即报错。

- **Broker 网络重试（原 P0-1，审查 3.4）**：`_handle_ccxt_error()` 把 ccxt 异常转成 `ExecutionError` 后才抛出，而 `retry_on_network` 只认原始 ccxt 类型 —— 12 个方法的重试全部失效（实测 `get_balance()` 在持续 `NetworkError` 下只调用 1 次）。改法套用 fetcher 的模式，新增 `Broker._call_with_retry()` 把 ccxt 调用下沉到内层、重试跑完再转换异常。
  - **下单路径额外加了幂等键**：`market_buy` / `market_sell` / `limit_buy` / `limit_sell` 非幂等，直接放开重试会在 `RequestTimeout`（订单可能已到达交易所、只是响应丢了）时**双开仓**。新增 `_place_order()`：每单挂一个 `clientOrderId`，重发前先拿该键查单，已落地就直接认领；若查询本身也连不上交易所，则拒绝重发（"查不到"≠"没下单"）。
  - **顺带修** `_get_swap_position()` 原先 `except Exception: pass` 后返回 `None`，把"交易所连不上"上报成"没有持仓"——正是 `Unknown != Flat` 那一类病。
  - 测试：`TestNetworkRetryCount` 重写为穿过真实 `Broker`（原版测的是孤立装饰器，恒绿）；新增 `TestOrderPlacementIdempotency`。`git stash` 验证：9/12 在旧代码上 FAILED。
- **移动止损回测/实盘分歧（原 P0-2）**：采用方案 (b)。`config.doge_donchian.yaml` 的 `trailing_stop_pct` 由 `20.0` 置 null —— 该策略的验收基线（120/60，Sharpe 0.90/0.67/0.69）本就是在没有移动止损的引擎上跑出来的，删掉即让实盘回到已验证的基线；`DogeDonchianTrend` 自带 60 根通道出场。**未**写进 `generate_signal()`：那会造出一个从未被回测的新变体，按冻结协议要走新一轮研究。新增 `TestShippedConfigsMatchBacktest` 守卫，任何 config 再开 `trailing_stop_pct` 即 FAIL；另有一条测试盯着 `BacktestEngine.run()`，一旦它真的支持了移动止损就提醒撤掉守卫。
- **年化收益 NaN（原 P1-3）**：`(1 + total_return_pct/100) ** (1/total_years)` 在总收益 ≤ -100%（权益为负，做空可达）时底数为负 → NaN 静默流进报表。现显式返回 -100%。测试用 11 倍拉升碾压 1x 空单复现（-965%）。注意 TODO 原文的 -925% 复现路径已失效：`_make_ohlcv` 的 "up" 只涨 20%，不足以打穿空单，原数字应来自 2026-07-13 引擎语义修复前。
- **pytest 超时配置（原 P1-5）**：`timeout = 120` 从 `[tool.pytest_timeout]` 移入 `[tool.pytest.ini_options]`。实测确认：改成 `timeout = 1` 后 `sleep(3)` 的测试确实被杀。
  - **订正原文一处误诊**：原文称「pytest-timeout 根本没装进当前 venv（`pip list | grep timeout` 无输出）」——**不成立**。该插件一直装着（`.venv/lib/python3.11/site-packages/pytest_timeout.py`，v2.4.0）。uv 建的 venv 默认不含 `pip`，`uv run pip list` 落到了系统 pip 上列出的是另一个环境。查 uv 环境请用 `uv pip list`。真正的病因只有段名一个。
- **`strategies/example/`（原 P2-7）**：本地残留，已不存在，无需处理。

## 附：2026-07-14 已完成（提供上下文，细节见 git 历史）

- **fetcher**：重试失效、`fetch_range` 死循环、起始空洞丢数据、探测步长会静默跳数据（短周期下 30 天定长步长会跨过 5 小时的请求窗口）；新增 `strict` 透传、timeframe 提前校验、进度日志。
- **报表去重**：`generate_report()` 补齐期末权益/最大回撤天数/VaR/CVaR/月度收益/可选逐笔交易表；两个回测脚本的约 90 行手写打印收敛为一行调用；删除逐行等价于 `run_doge_backtest.py ASTR/USDT binance` 的 `run_astr_backtest.py`。
- **回测/实盘平仓语义对齐（P0）**：`live.py` 此前完全不认识 `signal_is_position`，导致目标仓位回 0 时实盘不平仓（实测浮亏 -76.8% 仍持有）。新增 `check_signal_flat()`，三个策略的实盘钩子统一委托给 `generate_signal()`；`config.doge_regime_switch.yaml` 的引擎级止盈止损置 null（实测其会把回测吃满 +955% 的 bull 单在 +10% 砍掉）。
