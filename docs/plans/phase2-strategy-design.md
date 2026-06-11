# Phase 2: Strategy Framework — 详细设计文档

> **版本:** 1.0 | **日期:** 2026-06-10 | **作者:** Hermes + Roler

---

## 1. 概述

Phase 2 构建策略框架层，定义策略的标准接口、提供通用技术指标库、以及一个示例策略验证全链路。

```
Phase 1 (Data) 输出                  Phase 2 消耗
    DataCache.get_ohlcv()  ──────────▶  Strategy.generate_signal(df)
                                          │
                                          ▼
                                      pd.Series 信号数组
                                      (1=buy, -1=sell, 0=hold)
```

策略层只做一件事：**输入 DataFrame → 输出信号**。不接触账户、不下单、不知道资金量。纯粹的数据变换。

---

## 2. 架构总览

```
┌────────────────────────────────────────────────────────────┐
│                    策略使用者                                │
│          Backtest Engine / Live Engine                      │
└────────────────────────┬───────────────────────────────────┘
                         │ df ──▶ signal
                         ▼
┌────────────────────────────────────────────────────────────┐
│                    Strategy (ABC)                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ generate_signal(df) → pd.Series                      │  │
│  │   ├── preprocess(df)       # 可选：数据预处理         │  │
│  │   ├── compute_indicators() # 计算指标                  │  │
│  │   └── compute_signal()     # 生成信号                  │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ signals.py — 技术指标工具库                           │  │
│  │  sma, ema, atr, adx, rsi, bollinger, ...             │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

**设计原则：**

| 原则 | 说明 |
|------|------|
| 无状态 | Strategy 实例不保存市场数据，每次 `generate_signal()` 独立 |
| 纯函数 | 技术指标函数不修改输入，返回新 Series/DataFrame |
| 参数化 | 所有阈值、周期等通过 `params: dict` 注入，不硬编码 |
| 可组合 | 指标函数互相独立，策略可自由组合调用 |

---

## 3. Strategy 基类设计 (base.py)

### 3.1 类图

```
┌─────────────────────────────────────────────────────────┐
│                   Strategy (ABC)                         │
├─────────────────────────────────────────────────────────┤
│ + params: dict                                          │
│ + name: str (property, abstract)                        │
│ + timeframe: str (class var, default "1h")              │
│ + min_bars: int (class var, default 100)                │
│ + version: str (class var, default "1.0.0")             │
├─────────────────────────────────────────────────────────┤
│ + generate_signal(df) → pd.Series     (abstract)        │
│ + validate_params() → bool                               │
│ + get_param(key, default) → Any                          │
│ + preprocess(df) → pd.DataFrame       (可覆写)           │
│ + __repr__() → str                                       │
└─────────────────────────────────────────────────────────┘
```

### 3.2 完整实现

```python
# cryptoquant/strategy/base.py
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from cryptoquant.exceptions import StrategyError


class Strategy(ABC):
    """量化策略基类。

    所有策略必须实现 generate_signal() 和 name 属性。

    信号约定:
        1  → 做多 (long entry)
       -1  → 做空 (short entry) — 仅合约模式可用，spot 下忽略
        0  → 无操作 (hold / flat)

    子类通过 params dict 注入参数，避免硬编码。
    """

    # 类变量：子类可覆写
    timeframe: str = "1h"       # 默认 K 线周期
    min_bars: int = 100          # 生成信号所需最少 K 线数
    version: str = "1.0.0"       # 策略版本号

    DEFAULT_PARAMS: dict[str, Any] = {}

    def __init__(self, params: dict[str, Any] | None = None):
        """初始化策略。

        Args:
            params: 策略参数字典。子类通过 DEFAULT_PARAMS 提供默认值，
                    此处传入的值会覆盖默认值。
        """
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        self.validate_params()

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称，用于日志、报告、持久化。必须唯一。"""
        ...

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """从 OHLCV DataFrame 生成交易信号。

        Args:
            df: OHLCV DataFrame，列: [open, high, low, close, volume]
                索引: DatetimeIndex (UTC)

        Returns:
            pd.Series，与 df 等长，索引对齐。
            值: 1=buy, -1=sell, 0=hold

        Raises:
            ValueError: df 行数不足 min_bars 时
            KeyError:   df 缺少必需列时
        """
        ...

    def validate_params(self) -> bool:
        """验证参数合法性。子类可覆写添加自定义校验。

        Returns:
            True 表示验证通过

        Raises:
            StrategyError: 参数不合法时
        """
        return True

    def get_param(self, key: str, default: Any = None) -> Any:
        """安全获取参数值。"""
        return self.params.get(key, default)

    def preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        """数据预处理钩子。子类可覆写。

        用途举例:
            - 过滤异常成交量
            - 去除极端价格跳空
            - 添加辅助列

        默认实现：检查必要列存在 + 行数足够。
        """
        required = ["open", "high", "low", "close", "volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise StrategyError(f"DataFrame missing required columns: {missing}")

        if len(df) < self.min_bars:
            raise StrategyError(
                f"Need at least {self.min_bars} bars, got {len(df)}"
            )

        return df

    def __repr__(self) -> str:
        params_str = ", ".join(
            f"{k}={v}" for k, v in self.params.items()
        )
        return f"{self.name}({params_str})"
```

### 3.3 信号语义详解

```
信号值约定:
┌──────┬──────────────────────────────────────────┐
│  1   │ 开多 (buy to open)                       │
│ -1   │ 开空 (sell to open) — 仅合约模式          │
│  0   │ 无操作 (no action)                       │
└──────┴──────────────────────────────────────────┘

注意: Spot 模式下 -1 信号被引擎忽略（OKX spot 不支持裸卖空）。
      平仓由反向信号或引擎止损/止盈逻辑触发，策略无需显式发出平仓信号。

信号连续性规则（回测引擎负责校验）:
  - 已是多头时收到 1 → 忽略（不能重复开多）
  - 已是多头时收到 -1 → 平多（spot 下仅平仓，不开空）
  - 已是空头时收到 -1 → 忽略（不能重复开空）
  - 策略本身不保证信号连续性，这是引擎的职责
```

### 3.4 策略生命周期

```
实例化 ──▶ validate_params() ──▶ 就绪
   │
   │  (每个 tick / 每根 bar)
   ▼
generate_signal(df) ──▶ 信号数组
   │
   │  内部流程:
   ├── preprocess(df)
   ├── compute_indicators(df)  ← 子类实现
   └── compute_signal(df)      ← 子类实现
```

**实例化成本应该很低** — 不加载数据、不初始化连接。一个 `Strategy()` 应该 < 1ms。

---

## 4. 信号工具库 (signals.py)

### 4.1 设计哲学

- **纯 NumPy / pandas 实现，零外部依赖**（不依赖 TA-Lib）
- **输入是 Series/DataFrame，输出是 Series**
- **NaN 安全** — 不足周期的位置返回 NaN，不抛异常
- **可链式调用** — 风格一致，方便组合

### 4.2 公开 API 一览

```python
# === 趋势指标 ===
def sma(series: pd.Series, period: int) -> pd.Series:
    """简单移动平均"""
def ema(series: pd.Series, period: int) -> pd.Series:
    """指数移动平均"""
def wma(series: pd.Series, period: int) -> pd.Series:
    """加权移动平均"""

# === 波动率指标 ===
def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """平均真实波幅 (Average True Range)"""
def bollinger_bands(
    df: pd.DataFrame, period: int = 20, std: float = 2.0
) -> pd.DataFrame:
    """布林带。返回列: [middle, upper, lower, width, pct_b]"""
def historical_volatility(
    series: pd.Series, period: int = 20, annualize: bool = True
) -> pd.Series:
    """历史波动率（对数收益率标准差）"""

# === 动量指标 ===
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """相对强弱指数 (RSI, 0-100)"""
def macd(
    series: pd.Series,
    fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """MACD。返回列: [macd, signal, histogram]"""
def stochastic(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3
) -> pd.DataFrame:
    """随机指标。返回列: [k, d]"""

# === 趋势强度指标 ===
def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """平均趋向指数。返回列: [adx, pdi, mdi]"""
def aroon(df: pd.DataFrame, period: int = 25) -> pd.DataFrame:
    """Aroon 指标。返回列: [aroon_up, aroon_down]"""

# === 成交量指标 ===
def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """成交量 SMA"""
def volume_profile_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """当前成交量 / 过去 N 期平均成交量"""

# === 工具函数 ===
def crossover(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """A 上穿 B 返回 1，下穿返回 -1，否则 0"""
def crossunder(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """A 下穿 B 返回 1，否则 0"""
def rolling_max(series: pd.Series, period: int) -> pd.Series:
def rolling_min(series: pd.Series, period: int) -> pd.Series:
def pct_change_rolling(series: pd.Series, period: int) -> pd.Series:
```

### 4.3 关键指标详细实现

#### ATR — 必须用 `true_range` 而非 `high-low`

```python
def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — RMA smoothing method (Wilder's).

    True Range = max(
        high - low,
        |high - prev_close|,
        |low - prev_close|
    )
    ATR = RMA(TR, period)
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # RMA (Wilder's smoothing) = EMA with alpha = 1/period
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
```

#### ADX — 三步计算

```python
def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average Directional Index.

    Returns DataFrame with columns [adx, pdi, mdi].
    """
    high, low, close = df["high"], df["low"], df["close"]

    # Step 1: True Range
    tr = atr(df, period=1)  # single-period TR

    # Step 2: Directional Movement
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)

    mask_plus = (up_move > down_move) & (up_move > 0)
    mask_minus = (down_move > up_move) & (down_move > 0)

    plus_dm[mask_plus] = up_move[mask_plus]
    minus_dm[mask_minus] = down_move[mask_minus]

    # Step 3: Smooth with RMA
    atr_smooth = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_smooth
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_smooth

    # Step 4: ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx_val = dx.ewm(alpha=1 / period, adjust=False).mean()

    return pd.DataFrame({"adx": adx_val, "pdi": plus_di, "mdi": minus_di}, index=df.index)
```

#### Bollinger Bands — 带辅助列

```python
def bollinger_bands(
    df: pd.DataFrame, period: int = 20, std: float = 2.0
) -> pd.DataFrame:
    """Bollinger Bands.

    Returns columns:
        middle: SMA(period)
        upper:  middle + std * std_dev
        lower:  middle - std * std_dev
        width:  (upper - lower) / middle  (归一化带宽)
        pct_b:  (close - lower) / (upper - lower)  (%B 指标)
    """
    close = df["close"]
    middle = close.rolling(period).mean()
    std_dev = close.rolling(period).std()

    upper = middle + std * std_dev
    lower = middle - std * std_dev
    width = (upper - lower) / middle
    pct_b = (close - lower) / (upper - lower)

    return pd.DataFrame(
        {"middle": middle, "upper": upper, "lower": lower, "width": width, "pct_b": pct_b},
        index=df.index,
    )
```

#### MACD — 标准三线

```python
def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD indicator.

    MACD Line = EMA(fast) - EMA(slow)
    Signal Line = EMA(MACD Line, signal)
    Histogram = MACD Line - Signal Line
    """
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "histogram": histogram},
        index=series.index,
    )
```

### 4.4 工具函数

```python
def crossover(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """Detect when series_a crosses ABOVE series_b.

    Returns:
        pd.Series: 1 at crossover points, 0 elsewhere
    """
    above = series_a > series_b
    cross = above & (~above.shift(1))
    return cross.astype(int)


def crossunder(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """Detect when series_a crosses BELOW series_b.

    Returns:
        pd.Series: -1 at crossunder points, 0 elsewhere
        (与 crossover 返回值对称：上穿=1, 下穿=-1)
    """
    below = series_a < series_b
    cross = below & (~below.shift(1))
    return (-cross).astype(int)
```

### 4.5 公共约定

所有指标函数遵循：

```python
def indicator_name(input, period=14, **kwargs) -> pd.Series | pd.DataFrame:
    """
    Args:
        input: pd.Series (价格序列) 或 pd.DataFrame (OHLCV)
        period: 计算窗口
        **kwargs: 指标特定参数

    Returns:
        pd.Series (单值指标) 或 pd.DataFrame (多值指标，如 ADX 有 adx/pdi/mdi)
        索引与输入对齐
        前 period-1 个值为 NaN

    Raises:
        不抛异常 — 输入不足时优雅降级为 NaN
    """
```

---

## 5. 示例策略：双均线交叉 (ma_cross.py)

### 5.1 设计

```python
# strategies/example/ma_cross.py
"""双均线交叉策略 — 最简示例，验证整个框架跑通。"""
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, crossover, crossunder


class MACrossover(Strategy):
    """双 EMA 交叉策略。

    金叉（快线上穿慢线）→ 做多
    死叉（快线下穿慢线）→ 做空

    Parameters:
        fast: int = 12   快速 EMA 周期
        slow: int = 26   慢速 EMA 周期
        signal_type: str = "both"  交易方向: "long_only" | "short_only" | "both"
    """

    timeframe = "1h"
    min_bars = 100
    DEFAULT_PARAMS = {"fast": 12, "slow": 26, "signal_type": "both"}

    @property
    def name(self) -> str:
        return "MACrossover"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        close = df["close"]

        fast_ema = ema(close, self.params["fast"])
        slow_ema = ema(close, self.params["slow"])

        signal = pd.Series(0, index=df.index, dtype=int)

        signal_type = self.params["signal_type"]

        if signal_type in ("long_only", "both"):
            signal[crossover(fast_ema, slow_ema) == 1] = 1

        if signal_type in ("short_only", "both"):
            signal[crossunder(fast_ema, slow_ema) == -1] = -1

        return signal
```

### 5.2 测试

```python
# tests/test_ma_cross.py
import pandas as pd
import pytest

from strategies.example.ma_cross import MACrossover


@pytest.fixture
def strategy():
    return MACrossover()


@pytest.fixture
def sample_data():
    """构造一段有明显趋势的假数据来验证金叉/死叉。"""
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    # 前 100 根横盘，后 100 根上涨
    close = pd.Series(
        [100.0] * 50 + [101.0] * 50 + list(range(102, 152)),
        index=dates,
        dtype=float,
    )
    df = pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1000.0,
        },
        index=dates,
    )
    return df


def test_generates_signal_with_correct_index(strategy, sample_data):
    signal = strategy.generate_signal(sample_data)
    assert isinstance(signal, pd.Series)
    assert len(signal) == len(sample_data)
    assert (signal.index == sample_data.index).all()


def test_signal_values_are_valid(strategy, sample_data):
    signal = strategy.generate_signal(sample_data)
    assert signal.isin([-1, 0, 1]).all()


def test_insufficient_bars_raises(strategy):
    df = pd.DataFrame(
        {"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]}
    )
    with pytest.raises(ValueError, match="at least"):
        strategy.generate_signal(df)


def test_long_only_no_short_signals():
    strategy = MACrossover({"fast": 5, "slow": 15, "signal_type": "long_only"})
    # 构造下跌数据产生死叉
    n = 150
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = pd.Series(list(range(100, 100 - n, -1)), index=dates, dtype=float)
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1000.0},
        index=dates,
    )
    signal = strategy.generate_signal(df)
    assert (signal >= 0).all()  # 不应该有 -1
```

---

## 6. 策略参数管理最佳实践

### 6.1 参数模式

```python
class MyStrategy(Strategy):
    timeframe = "4h"
    min_bars = 200
    version = "2.1.0"
    DEFAULT_PARAMS = {
        "fast": 12,
        "slow": 26,
        "stop_loss_pct": 3.0,
        "take_profit_pct": 5.0,
        "max_hold_bars": 24,
    }
```

### 6.2 参数扫掠友好

策略必须支持通过 `params` 注入任意参数，以便回测引擎做参数优化：

```python
# 回测引擎可以这样扫参数
for fast in [8, 12, 21]:
    for slow in [21, 34, 55]:
        strategy = MACrossover({"fast": fast, "slow": slow})
        result = backtest(df, strategy)
        # 记录 Sharpe...
```

**策略内部永远用 `self.params["key"]` 或 `self.get_param("key")`，不读类常量。**

### 6.3 参数校验

```python
def validate_params(self) -> bool:
    """覆写以添加自定义校验。"""
    if self.params["fast"] >= self.params["slow"]:
        raise StrategyError(
            f"fast ({self.params['fast']}) must be < slow ({self.params['slow']})"
        )
    if self.params["stop_loss_pct"] <= 0:
        raise StrategyError("stop_loss_pct must be positive")
    return True
```

---

## 7. 策略注册与发现

### 7.1 策略注册表（显式注册，避免导入时副作用）

```python
# cryptoquant/strategy/registry.py
from cryptoquant.strategy.base import Strategy
from cryptoquant.exceptions import StrategyError

_REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    """显式注册策略类。

    与装饰器注册不同，显式注册在模块加载后由调用方主动触发，
    避免 import 时的隐式副作用和循环依赖问题。

    Usage:
        from strategies.example.ma_cross import MACrossover
        register(MACrossover)
    """
    instance = cls()
    name = instance.name
    if name in _REGISTRY:
        existing_version = _REGISTRY[name].version
        new_version = cls.version
        if new_version > existing_version:
            _REGISTRY[name] = cls  # 高版本覆盖低版本
        else:
            raise StrategyError(
                f"Duplicate strategy name: {name} "
                f"(existing v{existing_version}, new v{new_version})"
            )
    else:
        _REGISTRY[name] = cls
    return cls


def register_all(*classes: type[Strategy]) -> None:
    """批量注册多个策略。"""
    for cls in classes:
        register(cls)


def auto_discover(strategy_dirs: list[str] | None = None) -> None:
    """自动发现并注册策略。

    扫描指定目录下的所有 .py 文件，导入并注册其中的 Strategy 子类。
    使用 importlib 动态加载，避免在 __init__.py 中手动 import。

    Args:
        strategy_dirs: 策略目录列表，默认 ["strategies/"]
    """
    import importlib.util
    from pathlib import Path

    if strategy_dirs is None:
        strategy_dirs = ["strategies"]

    for dir_path in strategy_dirs:
        for py_file in Path(dir_path).rglob("*.py"):
            if py_file.name.startswith("_"):
                continue
            module_name = py_file.stem
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, Strategy)
                        and attr is not Strategy
                    ):
                        register(attr)


def get_strategy(name: str) -> type[Strategy]:
    """按名称获取策略类。"""
    if name not in _REGISTRY:
        raise StrategyError(f"Unknown strategy: {name}. Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]


def list_strategies() -> list[dict]:
    """列出所有已注册策略名称及版本。"""
    return [
        {"name": name, "version": cls.version, "timeframe": cls.timeframe}
        for name, cls in _REGISTRY.items()
    ]


def clear_registry() -> None:
    """清空注册表。用于测试隔离。"""
    _REGISTRY.clear()
```

### 7.2 使用方式

**方式 A：显式注册（推荐，无隐式副作用）**

```python
# 回测引擎或 CLI 中
from cryptoquant.strategy.registry import register, auto_discover
from strategies.example.ma_cross import MACrossover

register(MACrossover)
strategy_cls = get_strategy("MACrossover")
strategy = strategy_cls({"fast": 8, "slow": 21})
```

**方式 B：自动发现（适合策略数量多的场景）**

```python
from cryptoquant.strategy.registry import auto_discover, get_strategy

auto_discover(["strategies/"])
strategy_cls = get_strategy("MACrossover")
```

**方式 C：装饰器注册（保持向后兼容，但需注意导入顺序）**

```python
# strategies/example/ma_cross.py
from cryptoquant.strategy.registry import register

@register
class MACrossover(Strategy):
    ...
```

### 7.3 策略版本管理

每个策略通过 `version` 类变量声明版本，注册时自动处理版本冲突：

```python
class MACrossover(Strategy):
    version = "1.2.0"
    # ...
```

**版本规则：**
- 注册同名策略时，高版本自动覆盖低版本
- 版本相同时抛出 `StrategyError`，防止意外重复注册
- 回测结果中记录 `strategy_version`，确保可追溯

### 7.4 目录约定

```
strategies/
├── example/
│   ├── __init__.py
│   └── ma_cross.py    ← MACrossover v1.2.0
├── trend/
│   └── turtle.py      ← TurtleTrading v1.0.0
└── mean_reversion/
    └── wick.py        ← WickInversion v0.9.0
```

---

## 8. 指标计算注意事项

### 8.1 前视偏差 (Look-ahead Bias)

**绝对不能**在信号计算中使用未来数据：

```python
# 错误 — shift(-1) 使用了未来数据
signal = (close.shift(-1) > close).astype(int)

# 正确 — 使用当前和过去数据
signal = (close > close.shift(1)).astype(int)
```

所有 pandas `.shift()` 必须是正数或 0（过去或当前），`.rolling()` 永远只含过去数据。

### 8.2 NaN 处理

```python
# 所有指标前 period-1 个值为 NaN
rsi_14 = rsi(df["close"], 14)  # 前 13 个值是 NaN

# 在信号生成时必须处理 NaN
signal = pd.Series(0, index=df.index)
mask = rsi_14.notna()  # 或者直接比较，NaN > 30 返回 False
signal[mask & (rsi_14 < 30)] = 1
```

### 8.3 大数计算精度

价格可能很大（BTC ~100000），计算 `high - low` 等差值时用 `float64` 精度足够。不要用 `float32`。

---

## 9. 测试策略

### 9.1 指标单元测试

| 测试 | 说明 |
|------|------|
| `test_sma_basic` | 手动算 3 期 SMA，对照结果 |
| `test_sma_first_n_are_nan` | 前 period-1 个值应为 NaN |
| `test_ema_vs_sma_first_value` | EMA 第一期 = SMA 第一期 |
| `test_atr_bullish_bar` | 已知输入 → 验证 TR 和 ATR |
| `test_atr_gap_up` | 跳空高开场景 |
| `test_rsi_all_up` | 连续上涨 → RSI 应接近 100 |
| `test_rsi_all_down` | 连续下跌 → RSI 应接近 0 |
| `test_rsi_range` | 所有 RSI 值在 [0, 100] |
| `test_adx_during_trend` | 强趋势中 ADX > 25 |
| `test_adx_during_range` | 震荡中 ADX < 20 |
| `test_crossover_exact` | 精确控制交叉点验证 |
| `test_bollinger_bands_width` | 带宽 = (upper - lower) / middle |
| `test_macd_histogram_sign` | histogram = macd - signal |

### 9.2 策略测试

| 测试 | 说明 |
|------|------|
| `test_generates_valid_signal` | 信号值 ∈ {-1, 0, 1} |
| `test_signal_index_matches_input` | 索引对齐 |
| `test_insufficient_bars_raises` | 数据不足抛异常 |
| `test_no_future_data_leak` | shift 都是正数方向 |
| `test_params_override_default` | params 正确覆盖 DEFAULT_PARAMS |
| `test_invalid_params_raises` | 非法参数抛 ValidationError |
| `test_long_only_never_shorts` | signal_type="long_only" 只产生 ≥0 信号 |

### 9.3 测试 fixtures

```python
# tests/conftest.py — 共享 fixtures
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def ohlcv_synthetic():
    """生成 500 根 1h OHLCV 合成数据。

    模式:
        [0:100]   横盘 (100)
        [100:200] 上涨 (100→120)
        [200:300] 下跌 (120→90)
        [300:400] 横盘 (90)
        [400:500] 恢复上涨 (90→110)

    可以用一个 fixture 覆盖多种市场状态。
    """
    n = 500
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    np.random.seed(42)

    close = np.zeros(n)
    close[:100] = 100.0
    close[100:200] = np.linspace(100, 120, 100)
    close[200:300] = np.linspace(120, 90, 100)
    close[300:400] = 90.0
    close[400:500] = np.linspace(90, 110, 100)

    # 加少量噪声
    close += np.random.normal(0, 0.5, n)

    high = close + np.abs(np.random.normal(0, 1, n))
    low = close - np.abs(np.random.normal(0, 1, n))
    open_price = close + np.random.normal(0, 0.3, n)

    return pd.DataFrame(
        {"open": open_price, "high": high, "low": low, "close": close, "volume": 1000.0},
        index=dates,
    )
```

---

## 10. 文件清单

| 文件 | 行数估算 | 职责 |
|------|---------|------|
| `cryptoquant/strategy/__init__.py` | ~5 | 导出 Strategy |
| `cryptoquant/strategy/base.py` | ~80 | 策略抽象基类 |
| `cryptoquant/strategy/signals.py` | ~250 | 技术指标函数库 (15+ 指标) |
| `cryptoquant/strategy/registry.py` | ~80 | 策略注册表 + 显式注册 + 自动发现 + 版本管理 |
| `strategies/example/ma_cross.py` | ~50 | 双均线示例策略 |
| `tests/test_signals.py` | ~200 | 指标单元测试 |
| `tests/test_strategy_base.py` | ~40 | 基类行为测试 |
| `tests/test_ma_cross.py` | ~50 | 示例策略测试 |
| `tests/test_registry.py` | ~60 | 注册表测试（含版本冲突、自动发现） |
| `tests/conftest.py` | ~30 | 共享 fixtures |

---

## 11. 实现顺序

```
Task 2.1: Strategy base class          (base.py + 测试)
    ↓
Task 2.2: Signal indicators library    (signals.py + 测试)
    ↓
Task 2.3: Example strategy             (ma_cross.py + 测试)
```

Task 2.2 不依赖 2.1（signals.py 是纯函数库），但 2.3 依赖 2.1 + 2.2。

---

## 12. Phase 2 完成检查清单

策略框架开发完成后，验证以下场景全部通过：

- [ ] 创建 Strategy 子类只需实现 `name` + `generate_signal()`
- [ ] `preprocess()` 默认检查必需列 + 最少行数
- [ ] `params` 正确覆盖 `DEFAULT_PARAMS`
- [ ] `validate_params()` 在 `__init__` 时自动调用
- [ ] 所有指标函数前 period-1 值为 NaN
- [ ] 指标函数不修改输入
- [ ] 信号值只有 -1, 0, 1
- [ ] 信号索引与输入索引对齐
- [ ] 合成数据测试覆盖横盘 / 上涨 / 下跌三种市场状态
- [ ] 无前视偏差（所有 shift 为正方向）
