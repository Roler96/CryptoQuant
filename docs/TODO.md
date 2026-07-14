# CryptoQuant 待办清单

> 最后更新: 2026-07-14
>
> **与 `review-2026-07-10.md` 的关系**：那份审查列了 P0/P1/P2 共 22 项，本文档**不复制**它。
> 这里只收两类：
>
> 1. 该审查未覆盖的新发现；
> 2. 该审查已列出、但经实测确认**至今仍未修复**的项。
>
> 每一项的「证据」都是实际跑出来的结果，不是读代码推断的。

---

## P0 — 连接真实资金前必须修复

### 1. Broker 的网络重试全部失效（12 个方法）

**位置:** `cryptoquant/execution/broker.py:73`（`_handle_ccxt_error`）、`broker.py:90` 起共 12 个挂 `@retry_on_network` 的方法

**状态:** 审查 3.4 已指出，**仍未修复**。同一 bug 的 fetcher 一半已修复。

**证据:** 实测 `Broker.get_balance()` 在 `ccxt.NetworkError` 持续失败时，`fetch_balance` 只被调用 **1 次**，而非期望的 4 次（1 次初始 + 3 次重试）。根因：`_handle_ccxt_error()` 把 `ccxt.NetworkError` 转成 `ExecutionError` 之后才抛出，而 `retry_on_network` 只捕获 ccxt 自己的网络异常类型 —— 异常到达装饰器时已经"改头换面"，匹配不上。

**影响:** 覆盖 `market_buy` / `market_sell` / `cancel_order` / `wait_for_fill` / `get_position` 等**全部下单与持仓查询路径**。实盘中一次瞬时网络抖动就会让平仓单直接失败，而代码表面看起来是配了重试的。

**建议:** 套用 fetcher 已验证的做法（见 `cryptoquant/data/fetcher.py` 的 `_fetch_ohlcv`）：把 ccxt 调用下沉到内层函数并在其上重试，让原始 ccxt 异常先经过重试，外层方法再转换成 `ExecutionError`。这样 `NetworkError` / `RateLimitExceeded`（后者是前者子类）会退避重试，而 `AuthenticationError` / `InvalidOrder` 这类永久失败仍然一次抛出、不浪费退避预算。

**⚠️ 现有测试不会抓到它:** `tests/test_p0_regression.py:478` 的 `TestNetworkRetryCount` docstring 准确描述了这个 bug，但它测的是一个**独立的装饰器函数**，压根没碰 Broker。装饰器本身能工作从来不是疑点。修复时必须把断言改成穿过真实的 `Broker` 方法（参考 `tests/test_fetcher.py::TestRetry` 的写法）。

---

### 2. 移动止损是实盘独有，回测完全无法建模

**位置:** `cryptoquant/engine/live.py:648`（`_check_trailing_stop`）、`cryptoquant/engine/backtest.py`（无实现）、`config.doge_donchian.yaml:18`

**证据:** `live.py` 有 25 处 trailing 相关代码；`backtest.py` 里 grep `trailing` **零命中**；`BacktestEngine.run()` 的参数只有 `stop_loss_pct` / `take_profit_pct` / `max_hold_bars`。而 `config.doge_donchian.yaml` 设了 `trailing_stop_pct: 20.0`。

**影响:** `doge_donchian_trend` 的实盘存在一条回测从未建模的出场规则。这与已修复的 `signal_exit` 分歧属于**同一类病**：实盘执行的不是被回测验证过的那个策略。回测报出的收益/回撤对这个配置不成立。

**建议:** 二选一 ——
- **(a)** 给 `BacktestEngine.run()` 加 `trailing_stop_pct`，复用 `live.py:_check_trailing_stop` 的锚点逻辑。注意回测需逐 bar 更新锚点，与现有向量化路径的交互要单独测。
- **(b)** 从 `config.doge_donchian.yaml` 移除，改由策略自身在 `generate_signal()` 里表达（与 regime-switch 已采用的方案一致）。

选 (b) 更省事且与当前架构方向一致；选 (a) 则需要同时补回测侧的锚点测试。

---

## P1 — 高优先级

### 3. 年化收益在权益跌破 0 时静默产出 NaN

**位置:** `cryptoquant/engine/backtest.py:535`

**证据:** 公式为 `(1 + total_return_pct / 100) ** (1 / total_years)`。当总收益 < -100%（权益为负）时底数为负，负底数取分数次幂 → **NaN**，仅伴随一条 `RuntimeWarning`，无任何拦截。实测：`BuyThenSell` 在 2000 根上涨行情上（`sell_bar` 发 -1 即开空，被趋势碾压）得到总收益 -925%、底数 -8.25、年化 = `nan`。

**影响:** NaN 会一路传进 `generate_report()` 和 dashboard。现货只做多碰不到，但**带空头的合约策略会**。

**建议:** 权益 ≤ 0 时年化收益没有实数定义，应显式返回 -100%（或 `float("nan")` 但在报表层标注"已爆仓"），而不是让 numpy 静默产出 NaN。加一条针对 `total_return_pct <= -100` 的测试。

---

### 4. DogeSpotRegimeSwitch 从未被端到端回测验证过

**位置:** `strategies/doge_spot_regime_switch.py`、`config.doge_regime_switch.yaml`

**证据:** 仓库里没有该策略的回测脚本（`run_doge_backtest.py` 跑的是 `DogeSpotDonchianSma`）。单元测试覆盖了信号逻辑，但没有任何一次在真实数据上的完整回测。

**影响:** 2026-07-14 已把 `config.doge_regime_switch.yaml` 的 `stop_loss_pct` / `take_profit_pct` / `max_hold_hours` 置为 null（原先它们会泄漏到 bull 单上，把跟着通道跑的突破单在 +10% 砍掉）。现在 bear 腿的止盈止损**完全由策略内部的 `bear_take_profit` / `bear_stop_loss` / `bear_max_hold` 承担**，而这套参数从未在当前引擎语义下跑过完整回测。该配置文件自称是"testnet 验证档"，在没有回测基线的情况下不应上真实资金。

**建议:** 参数化现有回测脚本以支持指定策略（目前策略是硬编码 import），跑出 regime-switch 的基线，与研究笔记 `docs/research/doge_regime_switch_2026-07-14.md` 里的验收门槛对齐。

---

### 5. pytest 超时配置是死的，挂起的测试会永久挂起

**位置:** `pyproject.toml:50`

**证据:** 配置写的是 `[tool.pytest_timeout]`，但 pytest-timeout 读的是 `[tool.pytest.ini_options]` 里的 `timeout` 键 —— **段名不对，整段无效**。且该插件**根本没装进当前 venv**（`pip list | grep timeout` 无输出，尽管 `dev` extra 里声明了）。实测：一个 `sleep(3)` 的测试在 `timeout = 1` 下照样通过。

**影响:** 任何死循环类 bug 会让测试套件**永久挂起**而不是失败 —— CI 里就是一直转到超时被杀，且看不出是哪个测试。

**建议:** 把 `timeout = 120` 移进 `[tool.pytest.ini_options]`，并确保 `uv sync --extra dev` 真的装上 pytest-timeout。

---

## P2 — 中优先级

### 6. "看着在测、实际什么都没测"的空测试需要系统排查

**证据:** 2026-07-14 一次会话中就撞到 **4 例**，全部是绿的：

| 位置 | 写法 | 为什么是空的 |
|------|------|--------------|
| `tests/test_fetcher.py` chunk-count 测试 | 喂 4 个 `NetworkError` 却只断言错误信息 | 多余的 side_effect 从未被消费，掩盖了重试失效 |
| `tests/test_doge_spot_donchian_sma.py` | `assert (sig == 0).any()` | 序列本来就全是 0，恒真 |
| `tests/test_doge_spot_regime_switch.py` | `assert (sig == 0).any()` | 同上 |
| `tests/test_p0_regression.py:478` | 测独立装饰器函数 | 没穿过 Broker，测不到真正的 bug |

前三例已修。共同特征：**断言在"函数返回退化值"时依然成立**。

**建议:** 用"改坏源码，测试是否变红"的方式抽查关键路径测试（本次修复均已用 `git stash` 验证过新测试在旧代码上确实 FAILED）。重点排查 `.any()` / `>= 0` / 只断言异常信息 这几类写法。

---

### 7. `strategies/example/` 是本地残留，不是仓库问题（可直接删）

**证据:** 目录下 `.py` 文件数为 **0**，只有 `__pycache__/ma_cross.cpython-314.pyc`。但 `git ls-files strategies/` 只列出 4 个策略源文件 —— **该目录从不在版本库里**，`.gitignore:2` 已覆盖 `__pycache__/`。全仓 grep `ma_cross` / `strategies.example` 零引用。

**说明:** 纯本地残留，克隆仓库的人不会看到。列在这里只是避免下次又有人把它当成"源文件被误删"来排查。

**建议:** `rm -rf strategies/example/` 即可，无需改动仓库。

---

### 8. 静态检查存量（均为既有，非新引入）

**ruff — 16 项:**

| 文件 | 数量 |
|------|------|
| `cryptoquant/position/ledger.py` | 10 |
| `tests/test_position_ledger.py` | 2 |
| `tests/test_closed_bar.py` | 2 |
| `tests/test_p0_regression.py` | 1 |
| `cryptoquant/execution/lifecycle.py` | 1 |

**pyright — 35 项:** 集中在 `tests/test_position_ledger.py`(14)、`tests/test_closed_bar.py`(7)，其余分散。

**建议:** `ledger.py` 占了 ruff 的 10 项，值得单独收拾一轮。

---

### 9. `review-2026-07-10.md` 的指标已过期，且需逐项复核

**证据:** 该文档称「Ruff（已跟踪文件）通过」「Pyright 4 errors」，实测当前为 **ruff 16 项、pyright 35 项**。文档还称「测试 494 passed」，当前为 **592 passed**。

另一方面，它列的部分 P0 看起来**已经修了**（`live.py` 里有 `P0: Unknown != Flat` 的注释和对应实现，`tests/test_p0_regression.py` 覆盖了未闭合 K 线、持仓未知、策略持仓归属、PnL 符号、signal_reverse look-ahead 等）。但本次只逐项核实了 3.4（结论：**半修**，fetcher 已修、broker 未修）。

**建议:** 对该审查的 22 项做一次复核，逐项标记 已修 / 未修 / 半修，把仍未修的合并进本文档，然后给审查文档加上"已被 TODO.md 取代"的标注。**3.4 的经验说明"有对应测试"不等于"已修复"** —— 必须实测。

---

## 附：2026-07-14 已完成（提供上下文，细节见 git 历史）

- **fetcher**：重试失效、`fetch_range` 死循环、起始空洞丢数据、探测步长会静默跳数据（短周期下 30 天定长步长会跨过 5 小时的请求窗口）；新增 `strict` 透传、timeframe 提前校验、进度日志。
- **报表去重**：`generate_report()` 补齐期末权益/最大回撤天数/VaR/CVaR/月度收益/可选逐笔交易表；两个回测脚本的约 90 行手写打印收敛为一行调用；删除逐行等价于 `run_doge_backtest.py ASTR/USDT binance` 的 `run_astr_backtest.py`。
- **回测/实盘平仓语义对齐（P0）**：`live.py` 此前完全不认识 `signal_is_position`，导致目标仓位回 0 时实盘不平仓（实测浮亏 -76.8% 仍持有）。新增 `check_signal_flat()`，三个策略的实盘钩子统一委托给 `generate_signal()`；`config.doge_regime_switch.yaml` 的引擎级止盈止损置 null（实测其会把回测吃满 +955% 的 bull 单在 +10% 砍掉）。
