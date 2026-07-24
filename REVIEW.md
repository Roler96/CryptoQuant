# CryptoQuant 代码库分析与建设性修改建议

* 仓库地址：https://github.com/Roler96/CryptoQuant/tree/fable
* 分析分支：`fable`
* 项目类型：Python 量化研究与回测平台

---

## 1. 总体评价

该项目已经不属于普通的“策略回测脚本”，而是一个具有明确设计原则的量化研究内核。

当前项目体现出的主要设计目标包括：

* 以因果性和防止未来函数为核心；
* 数据缺口不进行静默填充；
* 显式建模成交、手续费、滑点、资金费率和强平；
* 保存数据切分、代码版本、资金费率等研究溯源信息；
* 使用统一的数据结构组织行情、策略和研究结果；
* 配置了 Ruff、Pyright、pytest、coverage 和 `uv.lock`；
* 代码按照 `data / engine / research / strategy` 等模块划分。

总体判断：

> 当前项目已经具备较高质量的研究原型基础，但距离可以长期稳定运行的模拟盘或实盘平台，仍需要补充运行溯源、资金费率因果性、实时恢复、交易所规格和工程化保障。

现阶段最需要优先解决的问题，不是增加更多策略，而是提高以下能力：

1. 结果是否真正可复现；
2. 回测模型是否严格因果；
3. 实时运行是否可以可靠恢复；
4. 交易所规则是否足够准确；
5. 数据、代码和配置是否能够完整追溯。

---

# 1.1 实现进度（2026-07-21 更新）

图例：✅ 已完成　🟡 部分完成　❌ 未开始

本轮聚焦"第一阶段：立即修复"与第 4 节已确认的具体缺陷——即直接影响研究可信度、且自成一体可测试的项目。涉及实时/实盘、交易所对接的后续阶段需要尚未存在的子系统，暂缓。全量测试 324 通过，Ruff / Pyright 无告警，每个修复都配有能在旧代码上失败的回归测试。

| 项 | 状态 | 备注 |
|---|---|---|
| P0-1 指纹绑定 RunResult | ✅ | 新增 frozen `RunManifest`，运行时锁定主/辅数据、spec、成本、资金费、sizing 指纹；报告改为以 manifest 为准并按全内容校验传入行情 |
| P0-2 高周期资金费率用未来收盘价 | ❌ | 需引入独立 `MarkPriceSource` |
| P0-3 资金费率周期推断 | ✅ | 改为众数推断 + 缺口式覆盖检查，容忍异常结算、仍捕获真实缺口 |
| P0-4 回测/实盘共用同一循环 | ❌ | 需统一 `Broker` 协议与 `Engine` |
| P0-5 LiveFeed 重启/断线恢复 | ❌ | 持久化水位、分页回补、事件幂等 |
| P0-6 版本化 InstrumentSpec + 分层维持保证金 | ❌ | |
| 4.1 `_upsert` 新增计数 | ✅ | 批次内去重后再计数 |
| 4.2 仓位 epsilon 统一 | ✅ | `core.types` 单一 `POSITION_EPSILON` / `is_flat()`，引擎与研究层共用 |
| 4.3 "去掉最佳交易"命名 | 🟡 | 方案一已改名 `return_less_best_trade_pnl` 并注明静态扣减；方案二真实反事实重放未做 |
| 4.4 负/零成交量拆分 | 🟡 | 已加 negative_volume / non_finite / misaligned 硬错误；负成交额、invalid_quote_volume 未做 |
| 5.1 数据库迁移机制 | ❌ | |
| 5.2 OHLCV 数据血缘与修订记录 | ❌ | |
| 5.3 Series 真正不可变 | 🟡 | 列数组已复制并置只读；dtype 统一、把 OHLC/对齐校验搬进 `__post_init__` 未做 |
| 5.4 避免重复构造 `close_times` | ❌ | 性能优化 |
| 5.5 Universe 配置 Pydantic 校验 | ❌ | |
| 6.1 预设 Forward 评审条件 | ❌ | |
| 6.2 Split 运行时绑定 | ❌ | 目前仅报告阶段核对 |
| 6.3 策略配置指纹 + 显式方向 | ❌ | manifest 尚无 strategy_config_fingerprint |
| 7.1–7.4 属性/变形/故障注入/Golden 测试 | ❌ | |
| 8.1–8.4 README / ASSUMPTIONS / RESEARCH_PROTOCOL / CHANGELOG | ❌ | |
| 第 9 节 Phase 3/4（实盘、对账、Kill Switch、血缘） | ❌ | |

遗留收尾：第一阶段第 7 条"RunResult 换为不可变快照"仅完成 frozen `RunManifest`，`RunResult` 本体仍可变（equity/fills 在循环内 append），彻底 frozen 化牵动 report.py 多处读取，暂留。

---

# 2. 当前设计中值得保留的部分

## 2.1 防未来函数设计较为扎实

策略通过 `Context` 获取行情数据，而不是直接取得完整 DataFrame 或全部 NumPy 数组。

当前设计具有以下优点：

* 策略只能访问当前游标之前的数据；
* 窗口数据会进行复制；
* 策略无法通过 NumPy 的 `.base` 访问底层完整数组；
* 辅助周期按照“该周期已经收盘”的时间点对齐；
* 辅助市场也按照当前决策时间进行因果对齐。

这种设计明显优于直接将整份行情数据交给策略。

建议继续保留“策略只能通过 Context 访问数据”的原则，不要为了开发方便向策略暴露完整行情数组。

---

## 2.2 对闭合 K 线的处理比较谨慎

历史数据回填只保存已经确认闭合的 K 线。

实时 Feed 同时检查：

* 交易所返回的 `confirm` 状态；
* 当前本地时间；
* K 线是否已经真正结束。

高周期数据由 1h 基础数据重采样生成，并且会丢弃构成不完整的周期。

例如：

* 4h K 线缺少其中一根 1h K 线时，不生成该 4h K 线；
* 1d K 线没有完整的 24 根 1h 数据时，不生成残缺日线。

这种行为能够避免“数据表面连续，但实际包含残缺周期”的隐性问题。

另外，项目通过 `ohlcv_sync` 单独记录一次历史回填是否完整结束，可以识别分页回填过程中程序异常退出导致的历史尾部缺失。

这是一个值得保留的设计。

---

## 2.3 回测事件顺序定义清晰

当前回测引擎大致按照以下顺序处理每根 K 线：

1. 处理开盘时点发生的资金费率；
2. 执行上一根 K 线收盘后产生的目标仓位；
3. 使用当前 K 线的高低价检查止损、止盈和强平；
4. 处理 K 线内部发生的资金费率；
5. K 线闭合后调用策略；
6. 使用收盘价计算账户权益。

同时，测试覆盖了以下情况：

* 跳空止损；
* 同一根 K 线同时触发止损和止盈；
* 使用悲观顺序处理止损止盈冲突；
* 零成交量时不允许成交；
* 资金费率结算；
* 仓位和平仓收益计算。

事件顺序显式定义，是回测系统可信度的重要基础。

---

## 2.4 研究纪律明显强于普通回测项目

项目不仅计算收益率和 Sharpe Ratio，还实现或考虑了以下指标：

* 最长回撤时间；
* 最佳单笔交易依赖度；
* 按持仓区间进行组合收益 Bootstrap；
* Sidak 多重检验修正；
* Deflated Sharpe Ratio；
* 数据切分指纹；
* Holdout 数据访问审计；
* Forward 数据冻结点。

项目明确意识到历史数据被反复观察后，会失去真正的样本外属性，因此设置新的冻结时间点。

这种研究纪律是正确的，应继续保持。

---

# 3. 最高优先级问题

## ✅ P0-1：报告中的数据指纹没有真正绑定到回测运行

> **已实现（2026-07-21）**：新增 frozen `RunManifest`（`cq/engine/loop.py`），在 `run_backtest` 开始、循环触碰数据之前，对主行情、辅助行情、`MarketSpec`、成本、资金费、sizing 逐一计算指纹并写入 `RunResult.manifest`。`series_fingerprint` 迁至 `cq/context.py`（配合只读 Series，见 5.3），覆盖每根 K 线全内容。`build_report` 改为以 manifest 为权威来源：传入的 `series` 不再是指纹的来源，而是被**按全内容校验**——同品种/周期/长度/首时间戳但内容被改的副本会被拒绝；也可不传 series 直接由 manifest 生成报告。回归测试：`test_a_report_rejects_data_doctored_after_the_run`、`test_a_report_can_be_built_straight_from_the_manifest`、`test_a_doctored_auxiliary_market_is_also_rejected`。

这是当前最严重的可复现性问题。

目前 `RunResult` 没有保存回测实际使用的主行情和辅助行情指纹。

生成报告时，`build_report()` 会重新对调用者传入的 `Series` 计算数据指纹。

当前匹配检查主要依赖以下信息：

* 品种；
* 周期；
* K 线数量；
* 第一根 K 线时间戳。

但是它没有验证：

* 完整行情内容；
* 最后一根时间戳；
* OHLCV 是否发生修改；
* 实际数据指纹是否与回测数据一致。

因此可能发生以下情况：

1. 使用数据 A 运行回测；
2. 回测结束后修改其中部分价格；
3. 将修改后的数据 B 传给报告模块；
4. 数据 B 的品种、周期、长度和首时间戳与数据 A 相同；
5. 报告接受数据 B；
6. 报告最终记录的是数据 B 的指纹；
7. 但回测结果实际由数据 A 产生。

最终报告可能错误声明：

> 该回测结果由数据 B 产生。

实际上结果来自数据 A。

### 建议方案

在回测开始时创建不可变的运行清单：

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class RunManifest:
    primary_fingerprint: str
    aux_fingerprints: tuple[tuple[str, str, str], ...]
    strategy_config_fingerprint: str
    market_spec_fingerprint: str
    cost_model_fingerprint: str
    funding_fingerprint: str
    engine_version: str
    code_fingerprint: str
```

将 `RunManifest` 直接写入 `RunResult`：

```python
@dataclass(frozen=True)
class RunResult:
    manifest: RunManifest
    timestamps: tuple[int, ...]
    equity: tuple[float, ...]
    fills: tuple[Fill, ...]
    final_account: AccountSnapshot
```

报告模块只能读取：

```python
result.manifest
```

而不应重新决定回测使用了什么数据。

如果生成报告时仍然允许传入 `Series`，则必须严格验证：

```python
series_fingerprint(series) == result.manifest.primary_fingerprint
```

否则直接拒绝生成报告。

### 进一步建议

还应保存以下内容：

* 策略完整配置；
* 数据切分配置；
* `MarketSpec`；
* 手续费模型；
* 滑点模型；
* 资金费率模型；
* 引擎版本；
* Git commit；
* 工作区是否存在未提交修改；
* 未提交 diff 的 SHA256。

仅记录类似以下字符串仍然不够：

```text
commit-hash-dirty
```

因为它只能说明工作区被修改过，却无法知道具体修改内容。

---

## ❌ P0-2：高周期回测中的资金费率价格包含未来信息

当前引擎对 K 线内部发生的资金费率结算，使用该 K 线最终的 `close` 作为名义价值计算价格。

例如日线回测：

* 00:00 日线开盘；
* 08:00 发生一次资金费率结算；
* 16:00 再次发生资金费率结算；
* 24:00 才能知道日线收盘价。

如果 08:00 的资金费率使用 24:00 的收盘价计算，就使用了当时尚未发生的未来价格。

虽然资金费率金额通常较小，但这仍然属于因果性错误。

### 建议方案

引入独立的标记价格数据源：

```python
from typing import Protocol


class MarkPriceSource(Protocol):
    def price_at(self, inst_id: str, ts: int) -> float:
        ...
```

建议存储：

* 1h 标记价格；
* 1h 指数价格；
* 实际资金费率结算时间；
* 每个结算时刻对应的可用价格。

策略可以继续在 4h 或 1d 周期运行，但资金费率事件应按照真实时间单独处理。

推荐的事件模型：

```text
行情事件
资金费率事件
订单事件
成交事件
强平事件
策略决策事件
```

资金费率不应完全依附于策略运行周期。

### 数据不足时的处理

如果没有结算时刻对应的标记价格，应：

* 明确标记为近似模型；
* 在报告中输出 approximation warning；
* 或禁止高周期回测使用 `ActualFunding`；
* 要求用户显式选择近似资金费率模型。

不能静默使用未来收盘价。

---

## ✅ P0-3：资金费率周期使用最短间隔推断，鲁棒性不足

> **已实现（2026-07-21）**：`cq/engine/funding.py` 的 `_infer_interval` 由 `min(gaps)` 改为**众数**（并列时取较短者），单条异常/临时结算不再把整段历史误判为每小时。覆盖检查 `_require_full_coverage` 从"刚性网格计数"改为**缺口式**：把每条归档结算视为真实事件，只有当两条相邻结算之间的空档大于周期、且其内部落在请求窗口内时才判缺失——于是多出的、离网结算被照常计费而非报错，真实缺口仍会 raise。回归测试：`test_a_single_off_schedule_settlement_does_not_redefine_the_cadence`、`test_an_extra_off_schedule_settlement_is_charged_not_treated_as_a_gap`、`test_a_genuine_hole_in_the_window_still_raises`、`test_a_hole_entirely_before_the_window_is_not_this_runs_concern`。

当前资金费率周期大致通过以下方式推断：

```python
interval = min(
    current_ts - previous_ts
    for previous_ts, current_ts in pairs
)
```

然后根据该最短间隔构建完整结算网格。

这种做法非常脆弱。

例如资金费率时间戳为：

```text
00:00
08:00
16:00
17:00
24:00
```

其中 `17:00` 可能是：

* 异常记录；
* 临时结算；
* 重复或修正数据；
* 交易所临时调整结算周期。

由于最短间隔为 1 小时，整个历史区间可能被错误推断为每小时结算一次。

之后系统会认为一天应该出现 24 次资金费率，从而产生大量虚假缺失。

### 建议方案

不要为整个历史区间推断一个全局固定周期。

更合理的方案是：

1. 直接把每条资金费率记录视为真实结算事件；
2. 保存交易所提供的下一次结算时间；
3. 保存当时适用的结算周期；
4. 对历史数据进行分段；
5. 每个时间段独立识别结算制度；
6. 对结算周期变化生成审计记录。

如果必须推断周期，可使用：

* 局部众数；
* 中位数；
* 分段聚类；
* 异常值过滤；
* 允许多个 cadence regime。

不应使用全局最短间隔。

---

## ❌ P0-4：回测与实盘尚未真正共享同一套循环

项目已经定义了：

* `Feed`；
* `HistoricalFeed`；
* `LiveFeed`。

设计目标是让回测和实时运行共享同一个行情迭代协议。

但是当前 `run_backtest()` 仍然：

* 直接接收完整 `Series`；
* 内部创建 `SimBroker`；
* 使用数组索引循环；
* 没有消费统一 `Feed`；
* 没有通用 Broker 接口；
* 没有状态恢复接口；
* 没有实时事件幂等机制。

因此当前更准确的描述是：

> Feed 抽象已经存在，但核心 Engine 尚未真正接入 Feed。

### 建议方案

定义统一 Broker 接口：

```python
from typing import Protocol


class Broker(Protocol):
    def submit_target(self, target) -> None:
        ...

    def process_event(self, event) -> None:
        ...

    def snapshot(self):
        ...
```

定义统一 Engine：

```python
class Engine:
    def run(
        self,
        feed: Feed,
        broker: Broker,
        strategy: Strategy,
        state_store: StateStore,
    ) -> RunResult:
        ...
```

然后构建三种组合：

```text
ReplayFeed + SimBroker
    用于历史回测

LiveFeed + SimBroker
    用于实时模拟盘

LiveFeed + OkxBroker
    用于实盘交易
```

所有场景必须共用同一个 Engine。

以下规则只能定义一次：

* 何时执行订单；
* 何时计算资金费率；
* 何时调用策略；
* 何时更新权益；
* 何时触发止损；
* 何时进行状态持久化。

不要为实盘单独复制第二套循环。

---

## ❌ P0-5：LiveFeed 无法保证重启和长时间中断后的连续性

当前 `LiveFeed` 主要依靠内存中的：

```python
_last_emitted_ts
```

记录最后发送的 K 线。

每次拉取的 K 线数量有限，例如最近 100 根。

这种实现存在两个问题。

### 问题一：重启后重复发送

程序重启后：

```python
_last_emitted_ts = None
```

Feed 可能重新发送最近的历史 K 线。

如果下游没有幂等机制，可能导致：

* 策略重复执行；
* 订单重复提交；
* 仓位重复调整；
* 统计重复记录。

### 问题二：长时间离线后永久漏数据

如果程序离线超过 100 根 K 线，重新启动时只获取最近 100 根。

更早的缺失 K 线无法通过当前 `poll()` 找回。

### 建议方案

增加持久化水位：

```text
last_processed_close_time
last_processed_event_id
last_committed_order_id
last_account_snapshot
```

Feed 启动时应：

1. 从数据库读取最后处理时间；
2. 从该时间点开始分页回填；
3. 验证时间连续性；
4. 补齐全部缺失数据；
5. 完成恢复后再进入实时轮询。

每个事件应具有稳定 ID：

```python
event_id = (
    inst_id,
    timeframe,
    close_timestamp,
)
```

Engine 和 Broker 必须保证重复事件不会重复产生副作用。

建议增加启动模式：

```text
resume
    从上次状态恢复

latest_only
    忽略历史缺口，从最新数据启动

warmup_then_live
    加载指定数量历史数据后进入实时
```

对于交易系统，默认模式应为 `resume`。

发现行情缺口时，应停止交易并报警，而不是继续运行。

---

## ❌ P0-6：交易所规格与强平模型过于简化

当前 `MarketSpec` 主要包含：

* `lot_size`；
* `min_notional`；
* `max_leverage`；
* 单一 `maintenance_margin_rate`。

对于永续合约，这些字段不足以准确描述交易所规则。

实际交易通常还需要：

* 价格精度；
* tick size；
* 数量精度；
* 最小下单数量；
* 合约面值；
* 合约乘数；
* 保证金币种；
* 结算币种；
* 逐仓或全仓模式；
* 分层维持保证金率；
* 不同仓位档位的最大杠杆；
* 标记价格；
* 指数价格；
* 强平手续费；
* 规格生效时间；
* 历史规格变化。

### 建议方案

引入版本化交易规格：

```python
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class MarginTier:
    max_notional: Decimal
    max_leverage: Decimal
    maintenance_margin_rate: Decimal


@dataclass(frozen=True)
class InstrumentSpec:
    inst_id: str
    effective_from: int

    tick_size: Decimal
    lot_size: Decimal
    contract_value: Decimal
    min_order_size: Decimal

    settle_currency: str
    margin_currency: str

    margin_tiers: tuple[MarginTier, ...]
```

报告中必须保存本次运行使用的 `InstrumentSpec` 指纹。

否则可能发生以下情况：

* 使用今天的最小下单量回测几年前的数据；
* 使用今天的杠杆档位计算历史强平；
* 使用当前维持保证金率解释旧行情。

这种结果无法严格复现历史交易环境。

---

# 4. 已确认的具体代码问题

## ✅ 4.1 `_upsert()` 的新增行数统计可能错误

> **已实现（2026-07-21）**：`cq/data/store.py` 先对批次 key 去重，再 `new = len(unique_keys) - existing`；`_count_existing` 直接接收去重后的 key 集合。回归测试：`test_duplicate_keys_in_one_batch_count_as_one_new_row`。

当前逻辑类似：

```python
existing = _count_existing(...)
conn.executemany(...)
return WriteResult(
    seen=len(rows),
    new=len(rows) - existing,
)
```

问题在于：

* `_count_existing()` 对 key 进行了去重；
* `len(rows)` 没有去重。

假设输入两条完全相同的新 K 线：

```text
seen = 2
new = 2
```

但数据库中实际上只新增了一行。

### 建议修复

```python
unique_keys = {
    tuple(row[position] for position in key_positions)
    for row in rows
}

new_count = len(unique_keys) - existing
```

也可以在写入前直接对批次去重。

更严格的做法是：

* 如果同一个批次出现重复 key，记录警告；
* 或直接抛出异常；
* 因为批次内重复通常意味着分页或数据源处理存在问题。

---

## ✅ 4.2 成交配对混用了 epsilon 和精确零比较

> **已实现（2026-07-21）**：`cq/core/types.py` 定义单一 `POSITION_EPSILON` 与 `is_flat()`，`metrics.trades_from_fills` / `position_spans` 与 `portfolio` 的持仓判断统一改走 `is_flat`；完全平仓时把残余快照回 `0.0`，浮点残余不再被读成反向持仓而生成近零虚假交易。回归测试：`test_a_float_residual_close_does_not_invent_a_phantom_trade`。

模块中已经定义：

```python
POSITION_EPSILON = 1e-12
```

但是部分逻辑仍然使用：

```python
quantity == 0.0
quantity != 0.0
```

浮点数运算可能产生极小残余，例如：

```python
0.3 - 0.1 - 0.2
```

结果可能不是严格的 `0.0`，而是类似：

```text
-2.7755575615628914e-17
```

这可能导致系统错误认为：

* 仓位没有完全平掉；
* 出现极小反向仓位；
* 生成一笔几乎为零的虚假交易；
* 错误识别翻仓。

### 建议修复

统一定义：

```python
POSITION_EPSILON = 1e-12


def is_flat(quantity: float) -> bool:
    return abs(quantity) < POSITION_EPSILON
```

所有仓位判断均使用：

```python
if is_flat(quantity):
    ...
```

包括：

* Portfolio；
* Trade 配对；
* Position span；
* 翻仓判断；
* 平仓判断；
* 风险控制；
* 强平逻辑。

更可靠的方案是，内部使用整数手数：

```python
lots: int
```

实际数量通过：

```python
quantity = lots * lot_size
```

进行换算。

这样可以显著减少浮点误差。

---

## 🟡 4.3 “去掉最佳交易后的收益”不是真正的反事实结果

> **部分实现（2026-07-21）**：采用方案一——字段 `return_excluding_best_trade` 改名为 `return_less_best_trade_pnl`，摘要标注"静态扣减，非重跑"，模块文档说明它不考虑路径依赖。方案二（排除该 episode 真实重放）**未做**。回归测试沿用并改名 `test_return_less_the_best_trade_pnl_is_reported`。

当前算法类似：

```python
without_best_return = (
    final_equity - best_trade_pnl
) / initial_cash - 1
```

这种计算只是从最终权益中静态减去最佳交易收益。

它并不等价于：

> 假设这笔交易从未发生，策略最终会获得多少收益。

原因包括：

* 后续仓位大小可能依赖账户权益；
* 删除一笔交易会改变后续复利路径；
* 后续风险预算可能发生变化；
* 资金费率可能没有完整归属到单笔 Trade；
* 手续费和滑点路径可能改变；
* 强平风险可能改变。

### 建议方案一：修改指标名称

将指标改名为：

```text
静态扣除最佳已平仓交易 P&L 后的收益归因
```

避免将其描述为真正的反事实收益。

### 建议方案二：执行真实反事实重放

重新运行一次策略：

* 排除对应持仓 episode；
* 或禁止该笔开仓；
* 重新计算后续权益和仓位；
* 得到真实 counterfactual equity。

方案二更准确，但计算成本更高。

---

## 🟡 4.4 数据质量检查将负成交量与零成交量混为一类

> **部分实现（2026-07-21）**：`cq/data/quality.py` 拆出 `negative_volume_bars`（硬错误）与 `zero_volume_bars`（警告），并新增硬错误 `non_finite_values`（NaN/±inf，排除可空的 quote_volume）与 `misaligned_timestamps`（开盘时间不在周期网格上）。高低价关系、open/close 越界、重复/倒序时间戳、非正价格此前已有。**未做**：负成交额、invalid_quote_volume 单独校验。回归测试：`test_negative_volume_is_a_hard_error_not_a_zero_volume_warning`、`test_non_finite_value_is_flagged`、`test_a_timestamp_off_the_timeframe_grid_is_flagged`、`test_a_nullable_quote_volume_does_not_trip_the_non_finite_check`。

当前逻辑大致使用：

```python
frame["volume"] <= 0
```

然后统一记录为：

```text
zero_volume_bars
```

问题在于：

* 零成交量可能是合法但可疑的数据；
* 负成交量通常是明确的数据错误。

如果负成交量只被当作普通零成交量警告，可能不会令质量检查失败。

### 建议拆分

```text
zero_volume_bars
    警告

negative_volume_bars
    硬错误

non_finite_values
    硬错误

misaligned_timestamps
    硬错误

invalid_quote_volume
    硬错误或警告
```

同时增加以下检查：

* NaN；
* 正负无穷；
* `high < low`；
* `open` 不在 `[low, high]`；
* `close` 不在 `[low, high]`；
* 时间戳不在周期边界；
* 时间戳重复；
* 时间倒序；
* 成交额为负；
* 价格小于等于零。

---

# 5. 工程架构建议

## ❌ 5.1 增加数据库迁移机制

当前数据库主要依靠：

```sql
CREATE TABLE IF NOT EXISTS
```

进行初始化。

但是没有明确的：

* schema version；
* migration；
* rollback；
* 数据库升级检查。

项目后续增加以下内容时，很容易遇到兼容问题：

* 数据血缘字段；
* InstrumentSpec；
* 状态恢复表；
* 订单和成交记录；
* 运行 Manifest；
* 数据修订记录。

### 建议方案

使用 SQLite 的：

```sql
PRAGMA user_version;
PRAGMA busy_timeout = 5000;
```

建立迁移目录：

```text
cq/data/migrations/
├── 001_initial.sql
├── 002_ohlcv_lineage.sql
├── 003_instrument_specs.sql
├── 004_engine_state.sql
└── 005_run_manifest.sql
```

迁移流程应包括：

1. 检查当前版本；
2. 创建数据库备份；
3. 开启事务；
4. 按顺序执行迁移；
5. 更新 `user_version`；
6. 失败时回滚。

---

## ❌ 5.2 增加 OHLCV 数据血缘和修订记录

当前 OHLCV 使用 upsert 覆盖数据。

如果交易所修改某根已经闭合的 K 线，数据库只保留最终值。

系统无法回答：

* 这根 K 线最初是什么值；
* 什么时候发生修改；
* 哪一次抓取发现修改；
* 修改来自哪个数据源；
* 某次回测使用的是修改前还是修改后数据。

### 建议的数据表

```text
ohlcv_current
    保存当前有效版本

ohlcv_revision
    保存历史修订记录

ingestion_runs
    保存每次抓取任务

data_sources
    保存数据源信息
```

建议至少保存：

```text
inst_id
timeframe
timestamp
old_hash
new_hash
fetched_at
ingestion_run_id
source
revision_number
```

这样才能对历史行情修订进行审计。

---

## 🟡 5.3 `Series` 应实现真正的不可变

> **部分实现（2026-07-21）**：`cq/context.py` 的 `Series.__post_init__` 现对每列 `np.array(copy=True)` 后 `setflags(write=False)`，`series.close[0]=999` 会 raise，且不再与传入数组别名——这正是让指纹可信的前提（配合 P0-1）。**未做**原文的额外建议：dtype 统一、把 OHLC 关系/时间对齐/有限性校验从 quality 层搬进 `__post_init__`。回归测试：`test_series_columns_cannot_be_mutated_in_place`、`test_series_does_not_alias_the_arrays_it_was_given`。

即使 `Series` 使用：

```python
@dataclass(frozen=True)
```

内部的 NumPy 数组仍然可能被修改：

```python
series.close[0] = 999
```

`frozen=True` 只能阻止属性重新赋值，不能阻止数组内容变化。

### 建议方案

在 `__post_init__()` 中：

1. 复制输入数组；
2. 统一 dtype；
3. 验证数组长度；
4. 验证数据合法性；
5. 设置数组只读。

示例：

```python
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Series:
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    def __post_init__(self):
        for name in (
            "ts",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ):
            value = np.array(
                getattr(self, name),
                copy=True,
            )
            value.setflags(write=False)
            object.__setattr__(self, name, value)
```

还应验证：

* 所有数组长度一致；
* 时间戳严格递增；
* 所有价格有限；
* OHLC 关系合法；
* 时间戳与 timeframe 对齐。

---

## ❌ 5.4 避免重复构造 `close_times`

如果 `close_times` 每次访问都会创建完整数组：

```python
close_times = ts + duration
```

在多年 1h 数据、多辅助市场和多次策略调用时，会产生大量无意义内存分配。

可以直接将搜索时间转换为开盘时间：

```python
search_ts = decision_time - duration_ms(series.timeframe)

index = np.searchsorted(
    series.ts,
    search_ts,
    side="right",
) - 1
```

这样不需要为每次查询创建完整 `close_times` 数组。

---

## ❌ 5.5 Universe 配置应使用 Pydantic 校验

项目依赖中已经包含：

* Pydantic；
* pydantic-settings。

但 Universe 配置目前相对简单，可能只是从 YAML 读取若干列表。

建议增加以下校验：

* instrument ID 格式是否合法；
* spot 和 swap 是否重复；
* 列表是否为空；
* 是否存在重复品种；
* 时间周期是否合法；
* 是否存在不支持的市场类型；
* 配置是否具有确定顺序。

示例：

```python
from pydantic import BaseModel, field_validator


class UniverseConfig(BaseModel):
    spot: list[str] = []
    swap: list[str] = []

    @field_validator("spot", "swap")
    @classmethod
    def deduplicate(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
```

配置加载后应生成规范化 JSON，并计算配置指纹。

该指纹写入 `RunManifest`。

---

# 6. 研究流程建议

## ❌ 6.1 当前 Forward Holdout 数据长度不足

项目设置的冻结点为：

```text
2026-07-20
```

冻结点刚刚建立时，真正未见的 Forward 数据非常有限。

一两天的数据无法证明策略稳定性。

Forward 数据只能随着真实时间逐步积累，无法通过历史数据加速获得。

### 建议预先固定评审条件

例如：

```text
最短 Forward 时间：
    6 个月

最少独立持仓 episode：
    30 个

市场环境：
    至少包含上涨、下跌和震荡阶段

评审前：
    不修改主要策略逻辑

未达到条件时：
    只展示运行状态，不输出通过或失败结论
```

评审条件应在观察 Forward 结果之前确定。

---

## ❌ 6.2 数据 Split 应在运行时绑定

当前 Split 更多是在报告阶段检查。

更严格的方式是，在运行回测时直接传入选定区间：

```python
run_backtest(
    series=series,
    strategy=strategy,
    segment=selected_segment,
)
```

Engine 在运行前：

1. 根据 segment 裁剪数据；
2. 生成 segment fingerprint；
3. 将 fingerprint 写入 `RunManifest`；
4. 禁止策略访问区间之外的数据。

报告只能展示已经绑定到运行结果中的 Split。

不能在回测完成后随意附加另一份 Split 描述。

---

## ❌ 6.3 策略参数应使用统一配置指纹

例如 Donchian 策略名称可能只包含：

* entry lookback；
* exit lookback。

如果 `size` 没有包含在名称中，那么不同仓位大小可能拥有相同策略名称。

策略名称只适合展示，不适合当作唯一身份。

### 建议方案

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DonchianConfig:
    entry_lookback: int
    exit_lookback: int
    size: float
    direction: Literal[
        "long_only",
        "short_only",
        "long_short",
    ]
```

对规范化配置计算 SHA256：

```python
strategy_config_fingerprint = sha256(
    normalized_json.encode("utf-8")
).hexdigest()
```

同时应显式配置策略方向。

例如 Spot 市场通常不能直接建立裸空头，策略应支持：

```text
long_only
short_only
long_short
```

而不是在产生空头信号后才由 Broker 抛出错误。

---

# 7. 测试体系建议　❌（本节均未实现；本轮新增的是逐项回归测试，非下列体系）

当前测试已经覆盖较多主要模块。

下一阶段建议增加以下高价值测试。

## 7.1 属性测试

推荐引入 Hypothesis。

重点验证以下不变量：

### 账户权益不变量

```text
现金 + 持仓价值 = 账户权益
```

需要考虑：

* 手续费；
* 已实现收益；
* 未实现收益；
* 资金费率；
* 强平费用。

### Spot 仓位不变量

```text
Spot 仓位永远不能小于零
```

### 价格不变不变量

在以下条件下：

* 价格不变；
* 无手续费；
* 无滑点；
* 无资金费率；

账户权益应保持不变。

### 数量网格不变量

每次成交后：

```text
position / lot_size
```

应接近整数。

### 平仓不变量

完全平仓后：

```python
abs(position) < POSITION_EPSILON
```

### 幂等不变量

重复处理同一个事件：

```text
最终账户状态不应发生第二次变化
```

---

## 7.2 防未来函数变形测试

这是非常重要的一类测试。

测试方法：

1. 使用原始数据运行策略；
2. 记录第 N 根 K 线之前的信号、成交和权益；
3. 随机修改第 N 根之后的全部行情；
4. 再次运行策略；
5. 比较第 N 根之前的结果。

期望：

```text
第 N 根之前的信号完全一致
第 N 根之前的成交完全一致
第 N 根之前的权益完全一致
```

这种测试比只验证单个窗口更能证明系统不存在未来数据泄漏。

---

## 7.3 数据故障测试

建议覆盖：

* API 页面倒序；
* API 页面乱序；
* 同一页面出现重复 K 线；
* 不同页面边界重复；
* 页面返回数量小于预期；
* 回填过程中程序崩溃；
* 数据库事务中断；
* LiveFeed 离线超过最大拉取数量；
* SQLite 被另一个进程占用；
* 交易规格在回测中途变化；
* 资金费率从 8h 切换到 4h；
* 行情数据闭合后被交易所修订；
* 实时事件被重复发送；
* Broker 返回重复成交；
* 网络超时后订单状态未知。

---

## 7.4 Golden Test

为核心回测场景建立固定输入和固定输出。

例如：

```text
tests/golden/
├── simple_long.json
├── stop_gap.json
├── funding_intrabar.json
├── liquidation.json
└── reversal.json
```

每次修改 Engine 后，对比：

* 成交序列；
* 账户权益；
* 手续费；
* 资金费率；
* 最终仓位；
* 强平结果。

这可以防止引擎重构时悄悄改变历史语义。

---

# 8. 仓库完整性建议　❌（README / ASSUMPTIONS / RESEARCH_PROTOCOL / CHANGELOG 均未创建）

当前仓库已经包含主要源码、测试和项目配置，但还建议补充以下文件。

## 8.1 README.md

README 至少应包括：

* 项目定位；
* 当前支持的市场；
* 架构图；
* 安装方法；
* 数据下载方法；
* 最小回测示例；
* 测试命令；
* 已知限制；
* 项目当前状态。

---

## 8.2 ASSUMPTIONS.md

集中记录所有建模假设：

* 成交价格模型；
* 滑点模型；
* 手续费模型；
* 止损止盈顺序；
* K 线内部路径假设；
* 强平价格模型；
* 资金费率价格来源；
* 标记价格近似；
* Spot 与 Swap 的差异；
* 当前未支持功能。

这份文件对于量化系统非常重要。

---

## 8.3 RESEARCH_PROTOCOL.md

记录研究纪律：

* 数据冻结规则；
* 探索集和 Holdout 定义；
* 一次实验如何计数；
* 参数搜索如何记录；
* 多重检验如何修正；
* 何时允许查看 Forward 结果；
* 何时允许修改策略；
* 策略淘汰标准；
* 策略晋级标准。

---

## 8.4 CHANGELOG.md

记录每次版本变更，尤其是会改变回测结果的修改：

```text
Changed
    资金费率价格从 K 线 close 改为结算时刻 mark price

Fixed
    修复翻仓时浮点残余仓位问题

Breaking
    修改强平价格计算模型
```

---

# 9. 推荐的修改顺序

## 第一阶段：立即修复

这些问题直接影响研究可信度。（状态见 1.1 节）

1. ✅ 将数据指纹绑定到 `RunResult`；
2. ✅ 增加不可变 `RunManifest`；
3. ❌ 修复高周期资金费率使用未来收盘价的问题；（= P0-2，未做）
4. ✅ 修复资金费率全局最短周期推断；
5. ✅ 修复 `_upsert()` 新增数量统计；
6. ✅ 统一仓位 epsilon 判断；
7. 🟡 将 RunResult 中的可变对象替换为不可变快照。（仅 `RunManifest` frozen，`RunResult` 本体仍可变）

---

## 第二阶段：模拟盘运行前完成

这些问题直接影响实时系统可靠性。

1. Engine 真正接入统一 Feed；
2. 定义统一 Broker 接口；
3. LiveFeed 增加持久化水位；
4. 支持离线后的分页恢复；
5. 实现事件幂等；
6. 增加 Engine 状态持久化；
7. 增加版本化 InstrumentSpec；
8. 增加数据库迁移；
9. 增加行情缺口检测；
10. 增加故障停止和报警机制。

---

## 第三阶段：实盘前完成

1. 对接交易所订单状态机；
2. 处理订单状态未知问题；
3. 处理部分成交；
4. 处理撤单与成交竞态；
5. 对账交易所实际仓位；
6. 对账资金费率；
7. 对账账户余额；
8. 支持逐仓和全仓；
9. 支持保证金档位；
10. 增加 Kill Switch；
11. 增加最大亏损和最大仓位限制；
12. 增加人工接管机制。

---

## 第四阶段：长期维护

1. 增加数据血缘；
2. 增加行情修订记录；
3. 增加属性测试；
4. 增加故障注入测试；
5. 增加 Golden Test；
6. 完善 CLI；
7. 完善 CI；
8. 完善研究文档；
9. 持续积累 Forward Holdout；
10. 达到预设观察周期后再评价策略有效性。
