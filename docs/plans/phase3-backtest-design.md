# Phase 3: Backtesting Engine — 详细设计文档

> **版本:** 1.0 | **日期:** 2026-06-10 | **作者:** Hermes + Roler

---

## 1. 概述

Phase 3 构建向量化回测引擎。输入 OHLCV 数据 + 策略，输出完整回测结果（逐笔交易 + 绩效指标 + 权益曲线）。

**权益曲线模型**: 采用**复利模型** — 每笔交易的收益率基于当前权益（而非初始资金）计算。
这意味着如果第一笔赚 10%、第二笔赚 10%，最终权益是 `initial * 1.1 * 1.1 = initial * 1.21`（+21%），
而非 `initial * 1.2`（+20%）。这与实盘满仓交易的行为一致。

**Spot 模式限制**: 默认仅支持 long-only。策略发出 -1（做空）信号时，
引擎在 spot 模式下仅执行平仓操作（如有持仓），不开新空仓。

```
DataCache.get_ohlcv() ──▶ DataFrame
                              │
Strategy.generate_signal() ──▶ pd.Series (信号)
                              │
         ┌────────────────────▼────────────────────┐
         │         BacktestEngine.run()             │
         │                                          │
         │  信号 → 仓位状态机 → 模拟成交 → 记录交易   │
         │                                          │
         └────────────────────┬────────────────────┘
                              ▼
                     BacktestResult
            ├── trades: list[Trade]
            ├── metrics: PerformanceMetrics
            ├── equity_curve: pd.Series
            └── monthly_returns: pd.Series
```

---

## 2. 为什么是向量化而不是事件驱动？

| | 向量化 (vectorized) | 事件驱动 (event-driven) |
|---|---|---|
| 速度 | 秒级（100 万行 ~2s） | 分钟级 |
| 复杂度 | 低 | 高（事件队列、回放） |
| 精度 | 开高低收可用，支持止损 | 完美模拟逐笔成交 |
| 适合 | 分钟/小时/日线策略 | Tick 级高频 |
| Phase 3 选择 | ✅ | 留给 L2 高频 |

对于 K 线级别策略（1m / 5m / 15m / 1h / 4h / 1d），向量化回测精度足够且快得多。

---

## 3. 数据结构设计

### 3.1 Trade — 单笔交易记录

```python
# cryptoquant/engine/types.py
from dataclasses import dataclass, field


@dataclass
class Trade:
    """单笔交易的完整生命周期记录。"""

    # === 标识 ===
    id: int                          # 交易序号，从 1 开始

    # === 开仓 ===
    symbol: str                      # "BTC/USDT"
    side: str                        # "long" | "short"
    entry_time: int                  # Unix 毫秒
    entry_price: float               # 成交价
    entry_signal: int                # 触发信号 (1 或 -1)

    # === 平仓 ===
    exit_time: int                   # Unix 毫秒
    exit_price: float                # 成交价
    exit_reason: str                 # "take_profit" | "stop_loss" | "time_exit" | "signal_reverse" | "end_of_data"

    # === 结果 ===
    pnl_pct: float                   # 收益率（%）：long = (exit/entry-1)*100
    pnl_abs: float                   # 绝对收益（USDT）
    hold_bars: int                   # 持仓 K 线数
    hold_hours: float                # 持仓时长（小时）

    # === 风控 ===
    mae_pct: float                   # Maximum Adverse Excursion (%)，持仓期间最大浮亏
    mfe_pct: float                   # Maximum Favorable Excursion (%)，持仓期间最大浮盈

    # === 市场状态（Phase 4+） ===
    regime: dict = field(default_factory=dict)
    # 例如: {"above_sma200": True, "adx": 28.3, "vol24": 0.045}
```

**关键字段解释：**

- **MAE (Maximum Adverse Excursion):** 从开仓到最低点的最大亏损百分比。衡量这笔交易"最惨的时候亏了多少"。
- **MFE (Maximum Favorable Excursion):** 从开仓到最高点的最大盈利百分比。衡量"曾经最多赚了多少"。
- MAE/MFE 比值可以判断是止盈太早还是止损太宽。

### 3.2 PerformanceMetrics — 绩效指标

```python
@dataclass
class PerformanceMetrics:
    """回测绩效指标集合。"""

    # === 收益 ===
    total_return_pct: float          # 总收益率（%）
    annualized_return_pct: float     # 年化收益率（%）
    monthly_returns: pd.Series       # 月收益率序列

    # === 风险 ===
    sharpe_ratio: float              # 年化 Sharpe（假设无风险利率=0）
    sortino_ratio: float             # 年化 Sortino（下行标准差）
    max_drawdown_pct: float          # 最大回撤（%）
    max_drawdown_days: int           # 最长回撤持续天数
    volatility_annual_pct: float     # 年化波动率（%）
    var_95_pct: float                # 95% VaR（%）
    cvar_95_pct: float               # 95% CVaR（%）

    # === 交易统计 ===
    total_trades: int                # 总交易次数
    win_rate_pct: float              # 胜率（%）
    profit_factor: float             # 盈亏比（总盈利/总亏损）
    avg_win_pct: float               # 平均盈利（%）
    avg_loss_pct: float              # 平均亏损（%）
    avg_hold_hours: float            # 平均持仓时长

    # === 回撤细节 ===
    drawdown_periods: list[dict]     # 每次回撤 [{"start", "end", "depth_pct", "days"}]
```

### 3.3 BacktestResult — 回测结果

```python
@dataclass
class BacktestResult:
    """回测完整结果。"""

    strategy_name: str
    strategy_version: str            # 策略版本号（用于结果追溯）
    symbol: str
    timeframe: str
    start_time: int                  # 回测开始（ms）
    end_time: int                    # 回测结束（ms）

    initial_capital: float           # 初始资金
    final_equity: float              # 最终权益

    trades: list[Trade]              # 所有交易
    metrics: PerformanceMetrics      # 绩效指标
    equity_curve: pd.Series          # 权益曲线（每个 bar）
    drawdown_curve: pd.Series        # 回撤曲线（每个 bar）

    config: dict                     # 回测配置快照（commission, slippage 等）
```

---

## 4. 引擎设计

### 4.1 类图

```
┌──────────────────────────────────────────────────────────┐
│                   BacktestEngine                          │
├──────────────────────────────────────────────────────────┤
│ - commission: float          # 手续费率，默认 0.001 (0.1%)│
│ - slippage: float            # 滑点率，默认 0.0005 (0.05%)│
│ - initial_capital: float     # 初始资金，默认 10000       │
│ - use_lows_for_stops: bool   # 止损用 low 而非 close      │
├──────────────────────────────────────────────────────────┤
│ + run(df, strategy) → BacktestResult                     │
│ - _simulate_positions(df, signals) → list[Trade]         │
│ - _check_stop_loss(df, i, position) → bool               │
│ - _check_take_profit(df, i, position) → bool             │
│ - _check_time_exit(position, i, max_bars) → bool         │
│ - _calculate_metrics(trades, equity) → PerformanceMetrics│
│ - _compute_equity_curve(trades, df) → pd.Series          │
└──────────────────────────────────────────────────────────┘
```

### 4.2 核心参数

```python
PERIODS_PER_YEAR = {
    "1m": 365 * 24 * 60,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
    "1w": 52,
}

BAR_HOURS = {tf: (365 * 24) / p for tf, p in PERIODS_PER_YEAR.items()}


class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 10_000,
        commission: float = 0.001,         # 0.1% — OKX spot taker fee
        slippage: float = 0.0005,          # 0.05% — 保守估计
        use_lows_for_stops: bool = True,   # 强烈建议 True
    ):
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.use_lows_for_stops = use_lows_for_stops
        self._bars_to_hours: float = 1.0  # 由 run() 根据 timeframe 设置
```

**为什么默认 `use_lows_for_stops=True`：**
参考 quant-strategy-development skill：用 `closes[i]` 检查止损会严重低估止损触发率，因为止损在 bar 中间就可能触发，不必等到收盘。这能让 Sharpe 3.15 变成 -4.02。

### 4.3 持仓状态机

```python
@dataclass
class _Position:
    """回测内部持仓状态。"""
    side: str                         # "long" | "short"
    entry_time: int                   # 入场时间戳 (ms)
    entry_price: float                # 入场价
    entry_signal: int                 # 触发信号
    entry_idx: int                    # 入场 bar 索引
    stop_loss_price: float | None     # 止损价（可选）
    take_profit_price: float | None   # 止盈价（可选）
    max_hold_bars: int | None         # 最大持仓 bar 数（可选）
    high_since_entry: float           # 入场后最高价（用于 MAE/MFE）
    low_since_entry: float            # 入场后最低价
```

**状态转换：**

```
                ┌──────────────────────────────────────┐
                │              FLAT (空仓)              │
                └──────┬───────────────────┬───────────┘
                 1/-1  │                   │
           ┌───────────▼──────┐   ┌────────▼──────────┐
           │   LONG (多头)    │   │   SHORT (空头)     │
           └──────┬───────────┘   └────────┬──────────┘
                  │                         │
       -1/stop/tp/time/end       1/stop/tp/time/end
                  │                         │
                  ▼                         ▼
                ┌──────────────────────────────────────┐
                │              FLAT (空仓)              │
                └──────────────────────────────────────┘

     注意：同向信号不叠加
      - 已 LONG 时收到 1 → 忽略（不能重复开多）
      - 已 LONG 时收到 -1 → 平多 + 开空（反转）
      - LONG 中途触发止损 → 平多，回到 FLAT
      - LONG 中途触发时间出场 → 平多，回到 FLAT
```

### 4.4 主循环：`_simulate_positions()`

```python
def _simulate_positions(
    self,
    df: pd.DataFrame,
    signals: pd.Series,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    max_hold_bars: int | None = None,
) -> list[Trade]:
    """核心回测循环。

    逐 bar 遍历，根据信号和当前持仓状态做出决策。

    关键时序约定（避免 look-ahead bias）：
    - 信号在 bar i 收盘后计算（基于 bar i 的 close）
    - 入场在 bar i+1 的 open 执行（下一根 bar 开盘）
    - 出场在同一 bar i 内根据 high/low 判断是否触发
    - 使用 pending_signal 延迟一根 bar 入场
    """

    trades: list[Trade] = []
    position: _Position | None = None
    trade_id = 0
    pending_signal: int = 0  # 待执行信号（延迟一根 bar 入场）

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    timestamps_ms = (df.index.astype("int64") // 1_000_000).values

    n = len(df)

    for i in range(n):

        # === 0. 执行挂单入场（上一根 bar 的信号，本根 bar 开盘执行）===
        if position is None and pending_signal != 0:
            position = _Position(
                side="long" if pending_signal == 1 else "short",
                entry_time=timestamps_ms[i],
                entry_price=opens[i],  # 本根 bar 开盘入场（无 look-ahead）
                entry_signal=pending_signal,
                entry_idx=i,
                stop_loss_price=(
                    opens[i] * (1 - stop_loss_pct / 100) if stop_loss_pct
                    else None
                ),
                take_profit_price=(
                    opens[i] * (1 + take_profit_pct / 100) if take_profit_pct
                    else None
                ),
                max_hold_bars=max_hold_bars,
                high_since_entry=highs[i],
                low_since_entry=lows[i],
            )
            pending_signal = 0

        # === 1. 有持仓时：检查出场条件 ===
        if position is not None:
            exit_triggered = False
            exit_reason = ""

            # 1a. 止损检查（用 low/high，不是 close！）
            if self._check_stop_loss(
                highs[i], lows[i], position, stop_loss_pct
            ):
                exit_triggered = True
                exit_reason = "stop_loss"

            # 1b. 止盈检查
            elif self._check_take_profit(
                highs[i], lows[i], position, take_profit_pct
            ):
                exit_triggered = True
                exit_reason = "take_profit"

            # 1c. 时间出场
            elif self._check_time_exit(position, i, max_hold_bars):
                exit_triggered = True
                exit_reason = "time_exit"

            # 1d. 反向信号
            elif int(signals.iloc[i]) != 0 and int(signals.iloc[i]) != position.entry_signal:
                exit_triggered = True
                exit_reason = "signal_reverse"

            if exit_triggered:
                trade_id += 1
                exit_price = self._get_exit_price(
                    opens[i], exit_reason, position
                )
                trade = self._create_trade(
                    trade_id, position, i, timestamps_ms[i],
                    exit_price, exit_reason, highs, lows,
                )
                trades.append(trade)
                position = None

                # 信号反转：将反向信号挂起，下一根 bar 入场
                if exit_reason == "signal_reverse":
                    pending_signal = int(signals.iloc[i])

        # === 2. 无持仓时：记录信号（延迟到下一根 bar 执行）===
        if position is None and pending_signal == 0:
            sig = int(signals.iloc[i])
            if sig in (1, -1):
                pending_signal = sig

        # === 3. 更新持仓 MAE/MFE ===
        if position is not None:
            position.high_since_entry = max(position.high_since_entry, highs[i])
            position.low_since_entry = min(position.low_since_entry, lows[i])

    # === 数据结束时强制平仓 ===
    if position is not None:
        trade_id += 1
        trade = self._create_trade(
            trade_id, position, n - 1, timestamps_ms[n - 1],
            closes[n - 1], "end_of_data", highs, lows,
        )
        trades.append(trade)

    return trades
```

**时序说明（修复 look-ahead bias）：**

```
旧实现（有 bias）：
  bar i: signal=1 → 立即以 opens[i] 入场
  问题：signal 基于 bar i 的 close 计算，但 opens[i] 在 close 之前已知

新实现（无 bias）：
  bar i: signal=1 → pending_signal=1（挂起）
  bar i+1: 以 opens[i+1] 入场（下一根 bar 开盘）
  正确：signal 在 bar i close 时确定，entry 在 bar i+1 open 执行

出场不受影响：
  止损/止盈用 bar i 的 high/low 检查 — 如果 bar i 内价格触及止损，
  出场是合理的（不依赖 bar i 的 close）
  反向信号出场同理 — bar i 内出现反向信号时立即平仓
```

### 4.5 止损/止盈检查 — 关键实现

```python
def _check_stop_loss(
    self,
    bar_high: float,
    bar_low: float,
    position: _Position,
    stop_loss_pct: float | None,
) -> bool:
    """检查止损是否触发。

    核心原则：用 low/high 检查，不用 close。
    止损触发意味着价格曾经到达止损价 — 不一定是在收盘时。
    """
    if stop_loss_pct is None or position.stop_loss_price is None:
        return False

    if position.side == "long":
        if self.use_lows_for_stops:
            return bar_low <= position.stop_loss_price
        else:
            return False  # close 检查在上层做，这里不重复
    else:  # short
        if self.use_lows_for_stops:
            # 空头止损：价格涨到止损价以上
            return bar_high >= position.stop_loss_price
        else:
            return False


def _check_take_profit(
    self,
    bar_high: float,
    bar_low: float,
    position: _Position,
    take_profit_pct: float | None,
) -> bool:
    """检查止盈是否触发。

    同样用 high/low 检查：
    多头：bar 内 high >= 止盈价 → 触发
    空头：bar 内 low <= 止盈价 → 触发
    """
    if take_profit_pct is None or position.take_profit_price is None:
        return False

    if position.side == "long":
        return bar_high >= position.take_profit_price
    else:
        return bar_low <= position.take_profit_price
```

### 4.6 成交价计算

```python
def _get_exit_price(
    self,
    bar_open: float,
    exit_reason: str,
    position: _Position,
) -> float:
    """计算出场成交价。

    止损/止盈：以触发价成交（加滑点）
    反转信号：本 bar 开盘价成交（信号在 bar 收盘确认，但出场在 bar 内触发）
    时间出场 / 数据结束：本 bar 开盘价成交（加滑点）

    注意：所有出场价格都基于 bar 内的可用价格（open/high/low/close），
    不使用未来 bar 的数据。
    """
    if exit_reason == "stop_loss":
        price = position.stop_loss_price
        # 滑点方向：多头止损卖在更低，空头止损买在更高
        if position.side == "long":
            price *= (1 - self.slippage)
        else:
            price *= (1 + self.slippage)
        return price

    elif exit_reason == "take_profit":
        price = position.take_profit_price
        if position.side == "long":
            price *= (1 - self.slippage)
        else:
            price *= (1 + self.slippage)
        return price

    elif exit_reason == "signal_reverse":
        # 信号在 bar i 收盘后确认，但回测假设在 bar i 开盘时执行
        # 这是一种简化：实际应在 bar i+1 开盘执行，但出场用 bar i open 近似
        if position.side == "long":
            return bar_open * (1 - self.slippage)
        else:
            return bar_open * (1 + self.slippage)

    else:  # time_exit / end_of_data
        # 时间出场：以本 bar 开盘价成交（加滑点）
        if position.side == "long":
            return bar_open * (1 - self.slippage)
        else:
            return bar_open * (1 + self.slippage)
```

### 4.7 Trade 创建

```python
def _create_trade(
    self,
    trade_id: int,
    position: _Position,
    exit_idx: int,
    exit_time_ms: int,
    exit_price: float,
    exit_reason: str,
    highs: np.ndarray,
    lows: np.ndarray,
) -> Trade:
    """从持仓状态创建 Trade 记录，计算 MAE/MFE。"""

    hold_bars = exit_idx - position.entry_idx
    hold_hours = hold_bars * self._bars_to_hours

    # 入场费
    entry_cost = position.entry_price * self.commission
    exit_cost = exit_price * self.commission

    if position.side == "long":
        pnl_pct = (exit_price / position.entry_price - 1) * 100
        mae_pct = (min(lows[position.entry_idx:exit_idx + 1]) / position.entry_price - 1) * 100
        mfe_pct = (max(highs[position.entry_idx:exit_idx + 1]) / position.entry_price - 1) * 100
    else:  # short
        pnl_pct = (1 - exit_price / position.entry_price) * 100
        mae_pct = (1 - max(highs[position.entry_idx:exit_idx + 1]) / position.entry_price) * 100
        mfe_pct = (1 - min(lows[position.entry_idx:exit_idx + 1]) / position.entry_price) * 100

    return Trade(
        id=trade_id,
        symbol="",   # 由 run() 填充
        side=position.side,
        entry_time=position.entry_time,
        entry_price=position.entry_price,
        entry_signal=position.entry_signal,
        exit_time=exit_time_ms,
        exit_price=exit_price,
        exit_reason=exit_reason,
        pnl_pct=round(pnl_pct, 4),
        pnl_abs=0.0,  # 由 run() 按资金量计算
        hold_bars=hold_bars,
        hold_hours=round(hold_hours, 2),
        mae_pct=round(mae_pct, 4),
        mfe_pct=round(mfe_pct, 4),
    )
```

---

## 5. 权益曲线计算

### 5.1 算法

```python
def _compute_equity_curve(
    self,
    trades: list[Trade],
    df: pd.DataFrame,
) -> pd.Series:
    """从交易列表构建每 bar 权益曲线。

    算法（简化版，复利模型）：
    1. 将每笔交易的 exit_time 映射到 bar index
    2. 在 exit bar 处乘以 (1 + pnl_pct/100)
    3. 用 forward-fill 填充中间 bar
    """
    if not trades:
        return pd.Series(self.initial_capital, index=df.index, dtype=float)

    # 构建 exit_time → cumulative return factor 映射
    exit_times = []
    factors = []
    for trade in trades:
        exit_times.append(pd.Timestamp(trade.exit_time, unit="ms"))
        factors.append(1 + trade.pnl_pct / 100)

    # 在 exit 时间点构建权益跳变序列
    equity_jumps = pd.Series(factors, index=exit_times, dtype=float)
    equity_jumps.sort_index(inplace=True)

    # 累积乘积 → 每笔交易后的权益倍数
    cumulative = equity_jumps.cumprod()

    # 映射到完整 bar 索引：forward-fill
    curve = pd.Series(self.initial_capital, index=df.index, dtype=float)
    for ts, factor in cumulative.items():
        mask = df.index >= ts
        if mask.any():
            curve[mask] = self.initial_capital * factor

    return curve
```

**优化说明：** 上述实现避免了逐 bar 的 Python for 循环。对于 N 笔交易 + M 根 bar，
复杂度从 O(M) 逐 bar 遍历降为 O(N log M) 的时间映射 + O(M) 的向量化赋值。
对于 100 万行数据和 1 万笔交易，性能提升约 5-10x。

### 5.2 回撤曲线

```python
def _compute_drawdown_curve(equity_curve: pd.Series) -> pd.Series:
    """从权益曲线计算回撤曲线。

    drawdown[i] = (equity[i] / running_max - 1) * 100
    """
    running_max = equity_curve.cummax()
    drawdown = (equity_curve / running_max - 1) * 100
    return drawdown
```

---

## 6. 绩效指标计算

### 6.1 `_calculate_metrics()`

```python
def _calculate_metrics(
    self,
    trades: list[Trade],
    equity_curve: pd.Series,
    df: pd.DataFrame,
) -> PerformanceMetrics:
    """从交易列表 + 权益曲线计算全部绩效指标。"""

    if not trades:
        return PerformanceMetrics(
            total_return_pct=0.0,
            annualized_return_pct=0.0,
            monthly_returns=pd.Series(dtype=float),
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown_pct=0.0,
            max_drawdown_days=0,
            volatility_annual_pct=0.0,
            var_95_pct=0.0,
            cvar_95_pct=0.0,
            total_trades=0,
            win_rate_pct=0.0,
            profit_factor=0.0,
            avg_win_pct=0.0,
            avg_loss_pct=0.0,
            avg_hold_hours=0.0,
            drawdown_periods=[],
        )

    # 基本统计
    total_return_pct = (equity_curve.iloc[-1] / self.initial_capital - 1) * 100

    # 年化收益（根据 timeframe 动态计算）
    total_years = len(df) / self._periods_per_year
    if total_years > 0:
        annualized_return_pct = ((1 + total_return_pct / 100) ** (1 / total_years) - 1) * 100
    else:
        annualized_return_pct = 0.0

    # 日收益率
    daily_returns = equity_curve.resample("1D").last().pct_change().dropna()

    # Sharpe ratio
    if daily_returns.std() > 0:
        sharpe_ratio = daily_returns.mean() / daily_returns.std() * np.sqrt(365)
    else:
        sharpe_ratio = 0.0

    # Sortino ratio
    downside = daily_returns[daily_returns < 0]
    if len(downside) > 0 and downside.std() > 0:
        sortino_ratio = daily_returns.mean() / downside.std() * np.sqrt(365)
    else:
        sortino_ratio = 0.0

    # 最大回撤
    drawdown_curve = _compute_drawdown_curve(equity_curve)
    max_drawdown_pct = abs(drawdown_curve.min())

    # 交易统计
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]

    win_rate_pct = len(wins) / len(trades) * 100 if trades else 0
    avg_win_pct = np.mean([t.pnl_pct for t in wins]) if wins else 0
    avg_loss_pct = np.mean([t.pnl_pct for t in losses]) if losses else 0

    total_wins = sum(t.pnl_pct for t in wins)
    total_losses = abs(sum(t.pnl_pct for t in losses))
    profit_factor = total_wins / total_losses if total_losses > 0 else float("inf")

    avg_hold_hours = np.mean([t.hold_hours for t in trades])

    # VaR / CVaR (95%)
    if len(daily_returns) > 0:
        var_95_pct = float(np.percentile(daily_returns, 5)) * 100
        cvar_95_pct = float(daily_returns[daily_returns <= np.percentile(daily_returns, 5)].mean()) * 100
    else:
        var_95_pct = 0.0
        cvar_95_pct = 0.0

    # 年化波动率
    volatility_annual_pct = float(daily_returns.std() * np.sqrt(365) * 100) if len(daily_returns) > 0 else 0.0

    # 回撤周期详情
    drawdown_curve = _compute_drawdown_curve(equity_curve)
    drawdown_periods = _find_drawdown_periods(drawdown_curve, df.index)

    # 最大回撤持续天数
    max_drawdown_days = max((dd["days"] for dd in drawdown_periods), default=0)

    # 月收益率
    monthly_returns = equity_curve.resample("ME").last().pct_change().dropna() * 100

    return PerformanceMetrics(
        total_return_pct=round(total_return_pct, 4),
        annualized_return_pct=round(annualized_return_pct, 4),
        monthly_returns=monthly_returns,
        sharpe_ratio=round(sharpe_ratio, 4),
        sortino_ratio=round(sortino_ratio, 4),
        max_drawdown_pct=round(max_drawdown_pct, 4),
        max_drawdown_days=max_drawdown_days,
        volatility_annual_pct=round(volatility_annual_pct, 4),
        var_95_pct=round(var_95_pct, 4),
        cvar_95_pct=round(cvar_95_pct, 4),
        total_trades=len(trades),
        win_rate_pct=round(win_rate_pct, 2),
        profit_factor=round(profit_factor, 4),
        avg_win_pct=round(avg_win_pct, 4),
        avg_loss_pct=round(avg_loss_pct, 4),
        avg_hold_hours=round(avg_hold_hours, 2),
        drawdown_periods=drawdown_periods,
    )
```

**辅助函数：**

```python
def _find_drawdown_periods(drawdown_curve: pd.Series, index: pd.DatetimeIndex) -> list[dict]:
    """从回撤曲线提取每次回撤周期的详细信息。"""
    periods = []
    in_drawdown = False
    start_idx = 0

    for i in range(len(drawdown_curve)):
        if drawdown_curve.iloc[i] < 0 and not in_drawdown:
            in_drawdown = True
            start_idx = i
        elif drawdown_curve.iloc[i] >= 0 and in_drawdown:
            in_drawdown = False
            dd_slice = drawdown_curve.iloc[start_idx:i]
            periods.append({
                "start": int(index[start_idx].timestamp() * 1000),
                "end": int(index[i - 1].timestamp() * 1000),
                "depth_pct": round(float(abs(dd_slice.min())), 4),
                "days": max(1, (index[i - 1] - index[start_idx]).days),
            })

    # 处理未恢复的回撤
    if in_drawdown:
        dd_slice = drawdown_curve.iloc[start_idx:]
        periods.append({
            "start": int(index[start_idx].timestamp() * 1000),
            "end": int(index[-1].timestamp() * 1000),
            "depth_pct": round(float(abs(dd_slice.min())), 4),
            "days": max(1, (index[-1] - index[start_idx]).days),
        })

    return sorted(periods, key=lambda x: x["depth_pct"], reverse=True)
```

### 6.2 日历年化假设

`PERIODS_PER_YEAR` 和 `BAR_HOURS` 已在模块顶部定义（见 §4.2），在 `run()` 中根据 `strategy.timeframe` 动态选用。

---

## 7. `run()` 方法 — 统一入口

```python
def run(
    self,
    df: pd.DataFrame,
    strategy: Strategy,
    symbol: str = "",
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    max_hold_bars: int | None = None,
) -> BacktestResult:
    """执行完整回测。

    Args:
        df: OHLCV DataFrame
        strategy: 策略实例
        symbol: 交易对名称
        stop_loss_pct: 止损百分比（None=无止损）
        take_profit_pct: 止盈百分比（None=无止盈）
        max_hold_bars: 最大持仓时间（None=无限）

    Returns:
        BacktestResult 包含 trades, metrics, equity_curve
    """
    # 0. 设置 timeframe 相关参数
    tf = getattr(strategy, "timeframe", "1h")
    self._bars_to_hours = BAR_HOURS.get(tf, 1.0)
    self._periods_per_year = PERIODS_PER_YEAR.get(tf, 365 * 24)

    # 1. 生成信号
    signals = strategy.generate_signal(df)

    # 2. 模拟持仓
    trades = self._simulate_positions(
        df, signals, stop_loss_pct, take_profit_pct, max_hold_bars
    )

    # 3. 填充 symbol + pnl_abs
    for trade in trades:
        trade.symbol = symbol
        capital_per_trade = self.initial_capital  # 简化：满仓交易
        trade.pnl_abs = capital_per_trade * trade.pnl_pct / 100

    # 4. 计算权益曲线
    equity_curve = self._compute_equity_curve(trades, df)

    # 5. 计算绩效指标
    metrics = self._calculate_metrics(trades, equity_curve, df)

    # 6. 计算回撤曲线
    drawdown_curve = _compute_drawdown_curve(equity_curve)

    return BacktestResult(
        strategy_name=strategy.name,
        strategy_version=getattr(strategy, "version", "unknown"),
        symbol=symbol,
        timeframe=strategy.timeframe,
        start_time=int(df.index[0].timestamp() * 1000),
        end_time=int(df.index[-1].timestamp() * 1000),
        initial_capital=self.initial_capital,
        final_equity=equity_curve.iloc[-1],
        trades=trades,
        metrics=metrics,
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        config={
            "commission": self.commission,
            "slippage": self.slippage,
            "initial_capital": self.initial_capital,
            "use_lows_for_stops": self.use_lows_for_stops,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "max_hold_bars": max_hold_bars,
        },
    )
```

---

## 8. 回测报告生成 (Task 3.2)

### 8.1 文本报告

```python
def generate_report(result: BacktestResult) -> str:
    """生成人类可读的回测文本报告。"""

    m = result.metrics
    lines = [
        f"{'='*60}",
        f"  Backtest Report: {result.strategy_name} v{result.strategy_version}",
        f"  Symbol: {result.symbol}",
        f"  Period: {_fmt_time(result.start_time)} → {_fmt_time(result.end_time)}",
        f"  Timeframe: {result.timeframe}",
        f"{'='*60}",
        "",
        "── PERFORMANCE ──",
        f"  Total Return:       {m.total_return_pct:+.2f}%",
        f"  Annualized Return:  {m.annualized_return_pct:+.2f}%",
        f"  Sharpe Ratio:       {m.sharpe_ratio:.2f}",
        f"  Sortino Ratio:      {m.sortino_ratio:.2f}",
        f"  Max Drawdown:       {m.max_drawdown_pct:.2f}%",
        f"  Volatility (ann):   {m.volatility_annual_pct:.2f}%",
        "",
        "── TRADES ──",
        f"  Total Trades:       {m.total_trades}",
        f"  Win Rate:           {m.win_rate_pct:.1f}%",
        f"  Profit Factor:      {m.profit_factor:.2f}",
        f"  Avg Win:            {m.avg_win_pct:+.2f}%",
        f"  Avg Loss:           {m.avg_loss_pct:+.2f}%",
        f"  Avg Hold:           {m.avg_hold_hours:.1f}h",
        "",
        "── EXIT BREAKDOWN ──",
    ]

    # 按出场原因统计
    from collections import Counter
    exit_counts = Counter(t.exit_reason for t in result.trades)
    for reason, count in exit_counts.most_common():
        lines.append(f"  {reason:20s}: {count:4d} ({count/m.total_trades*100:.0f}%)")

    lines.append("")
    lines.append("── DRAWDOWN PERIODS ──")
    for dd in m.drawdown_periods[:5]:  # 最严重的 5 次回撤
        lines.append(
            f"  {_fmt_time(dd['start'])} → {_fmt_time(dd['end'])}: "
            f"{dd['depth_pct']:.1f}% ({dd['days']}d)"
        )

    return "\n".join(lines)
```

### 8.2 逐笔交易导出

```python
def trades_to_dataframe(trades: list[Trade]) -> pd.DataFrame:
    """交易列表 → DataFrame，方便在 Jupyter 中分析。"""
    records = []
    for t in trades:
        records.append({
            "id": t.id,
            "side": t.side,
            "entry_time": pd.to_datetime(t.entry_time, unit="ms"),
            "entry_price": t.entry_price,
            "exit_time": pd.to_datetime(t.exit_time, unit="ms"),
            "exit_price": t.exit_price,
            "exit_reason": t.exit_reason,
            "pnl_pct": t.pnl_pct,
            "hold_hours": t.hold_hours,
            "mae_pct": t.mae_pct,
            "mfe_pct": t.mfe_pct,
        })
    return pd.DataFrame(records)
```

---

## 9. 引擎配置的合理默认值

```python
DEFAULT_ENGINE_CONFIG = {
    # OKX spot taker: 0.08% for most users, 0.1% conservative
    "commission": 0.001,         # 0.1% — 单边
    # Slippage: 0.01-0.15% for BTC on OKX, 0.05% conservative
    "slippage": 0.0005,          # 0.05%
    "use_lows_for_stops": True,  # 关键！参考 quant-strategy skill
}
```

---

## 10. 测试策略

### 10.1 引擎单元测试

| 测试 | 说明 |
|------|------|
| `test_no_signals_zero_trades` | 全是 0 信号 → 0 笔交易 |
| `test_single_buy_and_sell` | 一次买入一次卖出 |
| `test_stop_loss_triggered_by_low` | low 触发止损（高优先级） |
| `test_stop_loss_not_triggered_by_close_only` | close 穿透但 low 没到 → 不触发 |
| `test_take_profit_triggered_by_high` | high 触发止盈 |
| `test_time_exit` | 达到 max_hold_bars 出场 |
| `test_signal_reverse_exit` | 反向信号平仓 |
| `test_long_only_ignores_sell_signals` | long_only 策略忽略 -1 |
| `test_commission_reduces_pnl` | 有手续费的 PnL < 无手续费的 PnL |
| `test_slippage_applied_to_stop` | 止损价包含滑点 |
| `test_end_of_data_force_close` | 数据结束平掉所有持仓 |
| `test_equity_curve_monotonic_no_trades` | 无交易时权益不变 |
| `test_drawdown_during_losing_streak` | 连续亏损产生回撤 |

### 10.2 集成测试

| 测试 | 说明 |
|------|------|
| `test_full_backtest_with_ma_cross` | MACrossover 策略完整回测 |
| `test_backtest_result_structure` | 返回的 BacktestResult 包含所有必需字段 |
| `test_report_generation` | generate_report() 不抛异常 |
| `test_trades_to_dataframe` | 转换后列正确 |

### 10.3 已知场景验证

```python
def test_known_scenario_bull_market():
    """验证：纯上涨市场 + 做多策略 ≠ 空仓"""
    # 构造纯上涨数据 + 永远做多的策略
    # 预期：有交易、有盈利

def test_known_scenario_never_trades():
    """验证：永远返回 0 的策略 → 0 trades, 0 return"""
    # ...

def test_stop_loss_precision():
    """验证：止损价精确触发（浮点精度安全）"""
    # entry = 100, stop = 95, low = 95.0 → 触发
    # entry = 100, stop = 95, low = 95.01 → 不触发
```

### 10.4 性能测试

| 测试 | 说明 |
|------|------|
| `test_benchmark_1m_bars` | 100 万行 K 线 < 5 秒 |
| `test_benchmark_100k_trades` | 10 万笔交易 < 2 秒 |

---

## 11. 常见陷阱

| 陷阱 | 后果 | 解决方案 |
|------|------|---------|
| 用 close 检查止损 | Sharpe 虚高 2-3x | `use_lows_for_stops=True` |
| 忽略手续费 | 高频策略虚高 | 默认 0.1%，可调 |
| 忽略滑点 | 止损/止盈虚高 | 止损成交价加滑点 |
| 信号与持仓不对齐 | T+1 虚高 | entry 用下根 bar open |
| 止盈止损同时触发 | 哪边算？不明确 | 止损优先（保守） |
| 数据不足抛异常 | 测试崩溃 | 优雅降级，返回空结果 |
| 价格用 float32 | 精度损失 | 强制 float64 |
| NaN 传入信号 | 行为未定义 | preprocess 时清理 |

### 止盈止损同时触发的处理

当一根 bar 内 `high >= tp_price` 且 `low <= sl_price` 时（长影线 bar）：

```
优先级: 止损 > 止盈 > 时间出场 > 信号反转

理由：保守原则 — 止损是硬约束，止盈是软约束。
如果先触发了止盈，但实际上 bar 内先到的止损，
回测会高估绩效。
```

实际上，对于向量化回测，无法知道 bar 内先触发了哪个。**保守做法是止损优先。**

---

## 12. 性能优化

### 12.1 核心循环优化（Numba JIT 优先）

`_simulate_positions()` 是逐 bar 的 Python for 循环，包含状态机逻辑（持仓/空仓切换），
难以用纯 NumPy 向量化。**Numba JIT 是首选优化方案**，可将 Python 循环编译为机器码，
无需改写算法逻辑。

**策略 A（首选）: Numba JIT**

```python
from numba import njit
import numpy as np


@njit(cache=True)
def _simulate_positions_numba(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    timestamps: np.ndarray,
    signals: np.ndarray,
    commission: float,
    slippage: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_hold_bars: int,
    use_lows_for_stops: bool,
) -> tuple:
    """Numba 编译的核心回测循环。

    返回: (trade_count, entry_times, exit_times, entry_prices, exit_prices,
           pnl_pcts, exit_reasons, hold_bars_list, maes, mfes)
    """
    n = len(opens)
    # 预分配输出数组（最大可能交易数 = n // 2）
    max_trades = n // 2 + 1
    entry_times = np.empty(max_trades, dtype=np.int64)
    exit_times = np.empty(max_trades, dtype=np.int64)
    entry_prices = np.empty(max_trades, dtype=np.float64)
    exit_prices = np.empty(max_trades, dtype=np.float64)
    pnl_pcts = np.empty(max_trades, dtype=np.float64)
    exit_reasons = np.empty(max_trades, dtype=np.int32)  # 0-4 枚举
    hold_bars_arr = np.empty(max_trades, dtype=np.int64)
    maes = np.empty(max_trades, dtype=np.float64)
    mfes = np.empty(max_trades, dtype=np.float64)

    trade_count = 0
    in_position = False
    pending_signal = 0  # 延迟一根 bar 入场
    pos_side = 0  # 1=long, -1=short
    pos_entry_price = 0.0
    pos_entry_time = 0
    pos_entry_idx = 0
    pos_high = 0.0
    pos_low = 0.0
    pos_sl = 0.0
    pos_tp = 0.0

    for i in range(n):
        sig = int(signals[i])

        # 0. 执行挂单入场
        if not in_position and pending_signal != 0:
            in_position = True
            pos_side = pending_signal
            pos_entry_price = opens[i]
            pos_entry_time = timestamps[i]
            pos_entry_idx = i
            pos_high = highs[i]
            pos_low = lows[i]
            pos_sl = opens[i] * (1 - stop_loss_pct / 100) if stop_loss_pct > 0 else 0
            pos_tp = opens[i] * (1 + take_profit_pct / 100) if take_profit_pct > 0 else 0
            pending_signal = 0

        if in_position:
            exit_triggered = False
            reason = 0

            # 止损检查
            if stop_loss_pct > 0:
                if pos_side == 1 and use_lows_for_stops and lows[i] <= pos_sl:
                    exit_triggered, reason = True, 1
                elif pos_side == -1 and use_lows_for_stops and highs[i] >= pos_sl:
                    exit_triggered, reason = True, 1

            # 止盈检查
            if not exit_triggered and take_profit_pct > 0:
                if pos_side == 1 and highs[i] >= pos_tp:
                    exit_triggered, reason = True, 2
                elif pos_side == -1 and lows[i] <= pos_tp:
                    exit_triggered, reason = True, 2

            # 时间出场
            if not exit_triggered and max_hold_bars > 0:
                if (i - pos_entry_idx) >= max_hold_bars:
                    exit_triggered, reason = True, 3

            # 反向信号
            if not exit_triggered and sig != 0 and sig != pos_side:
                exit_triggered, reason = True, 4

            if exit_triggered:
                # 计算出场价
                if reason == 1:  # stop_loss
                    ep = pos_sl * (1 - slippage) if pos_side == 1 else pos_sl * (1 + slippage)
                elif reason == 2:  # take_profit
                    ep = pos_tp * (1 - slippage) if pos_side == 1 else pos_tp * (1 + slippage)
                else:  # signal_reverse / time_exit
                    ep = opens[i] * (1 - slippage) if pos_side == 1 else opens[i] * (1 + slippage)

                # 计算 PnL
                if pos_side == 1:
                    pnl = (ep / pos_entry_price - 1) * 100
                    mae = (pos_low / pos_entry_price - 1) * 100
                    mfe = (pos_high / pos_entry_price - 1) * 100
                else:
                    pnl = (1 - ep / pos_entry_price) * 100
                    mae = (1 - pos_high / pos_entry_price) * 100
                    mfe = (1 - pos_low / pos_entry_price) * 100

                # 扣除双边手续费
                pnl -= commission * 200  # 入场 + 出场

                idx = trade_count
                entry_times[idx] = pos_entry_time
                exit_times[idx] = timestamps[i]
                entry_prices[idx] = pos_entry_price
                exit_prices[idx] = ep
                pnl_pcts[idx] = pnl
                exit_reasons[idx] = reason
                hold_bars_arr[idx] = i - pos_entry_idx
                maes[idx] = mae
                mfes[idx] = mfe
                trade_count += 1

                in_position = False

                # 信号反转：挂起反向信号，下一根 bar 入场
                if reason == 4 and sig != 0:
                    pending_signal = sig

        # 无持仓时：记录信号（延迟到下一根 bar 执行）
        if not in_position and pending_signal == 0 and sig != 0:
            pending_signal = sig

        if in_position:
            if highs[i] > pos_high:
                pos_high = highs[i]
            if lows[i] < pos_low:
                pos_low = lows[i]

    # 数据结束强制平仓
    if in_position:
        ep = closes[-1] * (1 - slippage) if pos_side == 1 else closes[-1] * (1 + slippage)
        if pos_side == 1:
            pnl = (ep / pos_entry_price - 1) * 100
            mae = (pos_low / pos_entry_price - 1) * 100
            mfe = (pos_high / pos_entry_price - 1) * 100
        else:
            pnl = (1 - ep / pos_entry_price) * 100
            mae = (1 - pos_high / pos_entry_price) * 100
            mfe = (1 - pos_low / pos_entry_price) * 100
        pnl -= commission * 200

        idx = trade_count
        entry_times[idx] = pos_entry_time
        exit_times[idx] = timestamps[-1]
        entry_prices[idx] = pos_entry_price
        exit_prices[idx] = ep
        pnl_pcts[idx] = pnl
        exit_reasons[idx] = 5  # end_of_data
        hold_bars_arr[idx] = n - 1 - pos_entry_idx
        maes[idx] = mae
        mfes[idx] = mfe
        trade_count += 1

    return (
        trade_count, entry_times[:trade_count], exit_times[:trade_count],
        entry_prices[:trade_count], exit_prices[:trade_count],
        pnl_pcts[:trade_count], exit_reasons[:trade_count],
        hold_bars_arr[:trade_count], maes[:trade_count], mfes[:trade_count],
    )
```

**策略 B（备选）: NumPy 向量化止损/止盈检查**

当 Numba 不可用时（如某些平台不支持），用 NumPy 批量计算替代逐 bar 检查：

```python
if position is not None and stop_loss_pct is not None:
    if position.side == "long":
        sl_triggered = lows[position.entry_idx:exit_idx+1] <= position.stop_loss_price
    else:
        sl_triggered = highs[position.entry_idx:exit_idx+1] >= position.stop_loss_price

    if sl_triggered.any():
        first_trigger = np.argmax(sl_triggered)
        exit_idx = position.entry_idx + first_trigger
```

### 12.2 性能基准

| 数据规模 | 目标延迟 | 纯 Python | Numba JIT | 加速比 |
|----------|----------|-----------|-----------|--------|
| 10 万行 | < 0.1s | ~2s | ~0.05s | 40x |
| 100 万行 | < 0.5s | ~20s | ~0.3s | 67x |
| 1000 万行 | < 3s | ~200s | ~2s | 100x |

**注意：** Numba 首次调用有 JIT 编译开销（~1-2s），后续调用直接执行编译后代码。
使用 `cache=True` 可将编译结果缓存到磁盘，避免重复编译。

**依赖新增（可选）：** `numba >= 0.59.0` — 作为可选依赖，不影响核心功能

---

## 13. 文件清单

| 文件 | 行数估算 | 职责 |
|------|---------|------|
| `cryptoquant/engine/__init__.py` | ~5 | 导出 |
| `cryptoquant/engine/types.py` | ~120 | Trade, PerformanceMetrics, BacktestResult dataclass |
| `cryptoquant/engine/backtest.py` | ~450 | BacktestEngine 主逻辑 + Numba JIT 核心循环 |
| `cryptoquant/engine/backtest_numba.py` | ~200 | Numba JIT 编译的回测循环（可选） |
| `cryptoquant/engine/report.py` | ~150 | 报告生成 + 导出 |
| `tests/test_backtest_engine.py` | ~350 | 引擎单元 + 集成测试 |
| `tests/test_performance_metrics.py` | ~100 | 指标计算测试（含 VaR/CVaR） |
| `tests/test_report.py` | ~50 | 报告格式测试 |
| `tests/benchmarks/test_benchmark.py` | ~60 | 性能基准测试（Python vs Numba） |

---

## 14. 实现顺序

```
Task 3.1a: Trade / PerformanceMetrics / BacktestResult 数据类
Task 3.1b: BacktestEngine._simulate_positions() 持仓状态机
Task 3.1c: BacktestEngine._compute_equity_curve() 权益曲线
Task 3.1d: BacktestEngine.run() 统一入口 + 集成测试
Task 3.2a: _calculate_metrics() 绩效指标
Task 3.2b: generate_report() 文本报告
Task 3.2c: trades_to_dataframe() CSV 导出
```

Task 3.1 完成后就可以跑完整回测。Task 3.2 是锦上添花。
