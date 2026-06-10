# CryptoQuant v1 — 量化交易系统实现计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 从零构建加密货币量化交易系统：回测引擎 + 实盘执行 + 完整流水线

**Architecture:** 分层架构 — Data Layer（数据获取/存储）→ Strategy Layer（策略信号）→ Engine Layer（回测/实盘）→ Execution Layer（交易所）→ Monitor Layer（风控/日志）。先 OKX，架构支持多交易所扩展。

**Tech Stack:** Python 3.11+, pandas/NumPy, ccxt, SQLite, pytest, loguru

---

## 项目结构（目标）

```
CryptoQuant/
├── cryptoquant/
│   ├── __init__.py
│   ├── data/              # 数据层
│   │   ├── __init__.py
│   │   ├── fetcher.py     # OHLCV 获取（ccxt 封装）
│   │   ├── store.py       # SQLite 读写
│   │   └── cache.py       # 内存缓存，减少 DB 查询
│   ├── strategy/          # 策略层
│   │   ├── __init__.py
│   │   ├── base.py        # 策略基类
│   │   └── signals.py     # 通用信号工具（ATR, RSI, ADX 等）
│   ├── engine/            # 引擎层
│   │   ├── __init__.py
│   │   ├── backtest.py    # 向量化回测引擎
│   │   └── live.py        # 实盘引擎
│   ├── execution/         # 执行层
│   │   ├── __init__.py
│   │   ├── broker.py      # 交易所抽象（ccxt 封装）
│   │   └── order.py       # 订单管理（限价/市价/止损）
│   ├── risk/              # 风控层
│   │   ├── __init__.py
│   │   ├── sizer.py       # 仓位计算
│   │   └── manager.py     # 风控检查（最大持仓、日亏损限制等）
│   ├── monitor/           # 监控层
│   │   ├── __init__.py
│   │   ├── logger.py      # 结构化日志（loguru）
│   │   └── reporter.py    # PnL 报告、交易统计
│   └── config.py          # 全局配置
├── strategies/            # 具体策略实现
│   └── example/
│       └── ma_cross.py    # 示例：双均线策略
├── tests/
├── docs/
│   └── plans/
├── config.yaml            # 用户配置
├── .env.example           # API Key 模板
├── pyproject.toml         # 项目配置 + 依赖
└── .gitignore
```

---

## Phase 1: 项目骨架 + 数据层

### Task 1.1: 初始化项目结构

**Objective:** 创建项目目录、pyproject.toml、uv 虚拟环境

**Files:**
- Create: `pyproject.toml`
- Create: `cryptoquant/__init__.py`
- Create: 所有子包的 `__init__.py`

**Steps:**

**Step 1: 创建 pyproject.toml**

```toml
[project]
name = "cryptoquant"
version = "0.1.0"
description = "Cryptocurrency quantitative trading system"
requires-python = ">=3.11"
dependencies = [
    "ccxt>=4.0.0",
    "pandas>=2.0.0",
    "numpy>=1.24.0",
    "pyyaml>=6.0",
    "loguru>=0.7.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "ruff>=0.1.0",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

**Step 2: 创建虚拟环境 + 安装依赖**

```bash
cd ~/Code/CryptoQuant
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

**Step 3: 创建所有 `__init__.py`**

```bash
touch cryptoquant/__init__.py
touch cryptoquant/data/__init__.py
touch cryptoquant/strategy/__init__.py
touch cryptoquant/engine/__init__.py
touch cryptoquant/execution/__init__.py
touch cryptoquant/risk/__init__.py
touch cryptoquant/monitor/__init__.py
mkdir -p strategies/example tests docs/plans
```

**Step 4: 创建 .env.example**

```bash
# 交易所 API
OKX_API_KEY=your_api_key
OKX_SECRET=your_secret
OKX_PASSWORD=your_passphrase

# 可选
BINANCE_API_KEY=
BINANCE_SECRET=
```

**Step 5: 创建 config.yaml**

```yaml
exchange:
  default: okx
  okx:
    testnet: true  # 先 testnet，实盘再切

data:
  db_path: data/cryptoquant.db
  cache_ttl: 300  # 秒

trading:
  default_quote: USDT
  min_order_usdt: 10.0

logging:
  level: INFO
  dir: logs/
```

**Step 6: 验证**

```bash
python -c "import cryptoquant; print('OK')"
pytest  # 0 tests, 但确保配置正确
```

**Step 7: Commit**

```bash
git add -A
git commit -m "feat: initialize project structure with uv/pyproject.toml"
```

---

### Task 1.2: 实现配置加载

**Objective:** `cryptoquant/config.py` 从 config.yaml + .env 加载配置

**Files:**
- Create: `cryptoquant/config.py`
- Create: `tests/test_config.py`

**Step 1: Write failing test**

```python
# tests/test_config.py
from cryptoquant.config import load_config


def test_load_config_returns_dict():
    config = load_config()
    assert isinstance(config, dict)
    assert "exchange" in config
    assert "data" in config


def test_default_exchange_is_okx():
    config = load_config()
    assert config["exchange"]["default"] == "okx"


def test_env_vars_loaded():
    import os
    os.environ["OKX_API_KEY"] = "test_key"
    config = load_config()
    assert config.get("OKX_API_KEY") == "test_key"
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_config.py -v
# Expected: FAIL — ModuleNotFoundError
```

**Step 3: Implement minimal config.py**

```python
# cryptoquant/config.py
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


def load_config(config_path: str | None = None) -> dict:
    """Load config from YAML file and overlay .env vars."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"

    # Load .env from project root
    load_dotenv(Path(__file__).parent.parent / ".env")

    config = {}
    if Path(config_path).exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    # Overlay env vars (flattened, for API keys etc.)
    for key, value in os.environ.items():
        if key.endswith(("_API_KEY", "_SECRET", "_PASSWORD")):
            config[key] = value

    return config
```

**Step 4: Run test**

```bash
pytest tests/test_config.py -v
# Expected: 3 PASS
```

**Step 5: Commit**

```bash
git add cryptoquant/config.py tests/test_config.py
git commit -m "feat: add config loader (YAML + .env)"
```

---

### Task 1.3: 实现 OHLCV 数据获取

**Objective:** `cryptoquant/data/fetcher.py` 通过 ccxt 获取 OKX OHLCV 数据

**Files:**
- Create: `cryptoquant/data/fetcher.py`
- Create: `tests/test_fetcher.py`

**Steps:**

**Step 1: Write failing test**

```python
# tests/test_fetcher.py
import pytest
from cryptoquant.data.fetcher import OHLCVFetcher


@pytest.fixture
def fetcher():
    return OHLCVFetcher(exchange="okx")


def test_fetch_ohlcv_returns_dataframe(fetcher):
    df = fetcher.fetch("BTC/USDT", timeframe="1h", limit=10)
    assert len(df) > 0
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_fetch_ohlcv_datetime_index(fetcher):
    df = fetcher.fetch("BTC/USDT", timeframe="1h", limit=10)
    import pandas as pd
    assert isinstance(df.index, pd.DatetimeIndex)


def test_invalid_symbol_raises(fetcher):
    with pytest.raises(ValueError):
        fetcher.fetch("INVALID/PAIR", timeframe="1h")
```

**Step 2: Implement fetcher.py**

```python
# cryptoquant/data/fetcher.py
import ccxt
import pandas as pd


class OHLCVFetcher:
    """Fetch OHLCV candles from exchange via ccxt."""

    def __init__(self, exchange: str = "okx", testnet: bool = True):
        exchange_class = getattr(ccxt, exchange)
        self.exchange = exchange_class({
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })
        if testnet:
            self.exchange.set_sandbox_mode(True)

    def fetch(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 500,
        since: int | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles and return as DataFrame.

        Args:
            symbol: Trading pair, e.g. 'BTC/USDT'
            timeframe: '1m', '5m', '15m', '1h', '4h', '1d'
            limit: Number of candles
            since: Unix timestamp in ms

        Returns:
            DataFrame with columns [open, high, low, close, volume],
            DatetimeIndex.
        """
        try:
            raw = self.exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, limit=limit, since=since
            )
        except ccxt.BadSymbol:
            raise ValueError(f"Invalid symbol: {symbol}")

        if not raw:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df[["open", "high", "low", "close", "volume"]]
```

**Step 3: Run tests**

```bash
pytest tests/test_fetcher.py -v
```

**Step 4: Commit**

---

### Task 1.4: 实现 SQLite 数据存储

**Objective:** `cryptoquant/data/store.py` 存储和读取 OHLCV 数据

**Files:**
- Create: `cryptoquant/data/store.py`
- Create: `tests/test_store.py`

**Key design:**
- 表名: `ohlcv_{exchange}_{symbol}_{timeframe}` (斜杠替换为下划线)
- 列: `timestamp INTEGER PRIMARY KEY, open, high, low, close, volume REAL`
- 方法: `save(df)`, `load(symbol, timeframe, start, end)`, `get_latest(symbol, timeframe)`

---

### Task 1.5: 实现数据缓存层

**Objective:** `cryptoquant/data/cache.py` 先查缓存→再查 DB→最后 fetch

**设计要点:**
- 内存 LRU 缓存（functools.lru_cache 或手动 dict）
- `get_ohlcv(symbol, timeframe, lookback)` — 统一入口
- 自动补充缺失数据（fill_gaps）

---

## Phase 2: 策略框架 + 信号

### Task 2.1: 策略基类

**Objective:** `cryptoquant/strategy/base.py` 定义策略接口

```python
class Strategy(ABC):
    """Base strategy class."""

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate trading signals. 1=buy, -1=sell, 0=hold."""
        ...

    @abstractmethod
    def name(self) -> str:
        """Strategy name."""
        ...
```

### Task 2.2: 通用信号工具

**Objective:** `cryptoquant/strategy/signals.py` 技术指标计算

实现:
- SMA, EMA
- ATR
- ADX (+DI, -DI)
- RSI
- BB (Bollinger Bands)
- 成交量加权

### Task 2.3: 示例策略 — 双均线

**Objective:** `strategies/example/ma_cross.py`

最简单的策略，验证整个流水线能跑通。

```python
class MACrossover(Strategy):
    def generate_signal(self, df):
        fast = df["close"].ewm(span=self.params["fast"]).mean()
        slow = df["close"].ewm(span=self.params["slow"]).mean()
        # 金叉=1, 死叉=-1, else 0
        ...
```

---

## Phase 3: 回测引擎

### Task 3.1: 向量化回测引擎

**Objective:** `cryptoquant/engine/backtest.py`

核心逻辑:
```python
def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    initial_capital: float = 10000,
    commission: float = 0.001,  # 0.1%
    slippage: float = 0.0005,
) -> BacktestResult:
```

**关键实现点:**
- 基于 lows[i] 检查止损（参考 quant-strategy-development skill）
- 计算 returns、Sharpe、max drawdown、win rate
- 返回 trades 列表 + 统计摘要
- BacktestResult 是 dataclass：`trades: list[Trade], metrics: dict, equity_curve: pd.Series`

### Task 3.2: 回测统计报告

**Objective:** 生成详细的回测报告

- 总收益率、年化收益率
- Sharpe ratio
- Max drawdown
- Win rate, profit factor
- 按月/按年分组收益
- 交易分布直方图

---

## Phase 4: 执行层 + 实盘

### Task 4.1: 交易所抽象层

**Objective:** `cryptoquant/execution/broker.py`

```python
class Broker:
    def __init__(self, exchange: str, config: dict):
        ...

    def get_balance(self, quote: str = "USDT") -> float: ...
    def market_buy(self, symbol: str, amount: float) -> Order: ...
    def market_sell(self, symbol: str, amount: float) -> Order: ...
    def get_position(self, symbol: str) -> Position | None: ...
    def cancel_all_orders(self, symbol: str): ...
```

### Task 4.2: 订单管理

**Objective:** `cryptoquant/execution/order.py`

Order/Position/Trade 数据类:
```python
@dataclass
class Order:
    id: str
    symbol: str
    side: str  # buy / sell
    type: str  # market / limit
    amount: float
    price: float | None
    status: str
    timestamp: int
```

### Task 4.3: 实盘引擎

**Objective:** `cryptoquant/engine/live.py`

```python
class LiveEngine:
    def __init__(self, broker, strategy, risk_manager):
        ...

    def tick(self):
        """One iteration: fetch data → generate signal → check risk → execute"""
        ...

    def run(self, interval: int = 60):
        """Loop tick() every `interval` seconds"""
        ...
```

---

## Phase 5: 风控 + 监控

### Task 5.1: 仓位计算

**Objective:** `cryptoquant/risk/sizer.py`

- 固定金额: `position = capital * risk_pct`
- Kelly criterion
- ATR-based 波动率调整

### Task 5.2: 风控管理

**Objective:** `cryptoquant/risk/manager.py`

- 单笔最大亏损限制
- 日亏损限制
- 最大持仓数限制
- 最大杠杆限制

### Task 5.3: 日志 + 报告

**Objective:** `cryptoquant/monitor/`

- loguru 结构化日志
- trade journal 记录每笔交易
- 每日 PnL 摘要
- 可选: Telegram 通知

---

## 执行顺序

```
Phase 1 (Data) → Phase 2 (Strategy) → Phase 3 (Backtest) → Phase 4 (Live) → Phase 5 (Risk/Monitor)
     ↓                  ↓                    ↓                   ↓                  ↓
  Task 1.1-1.5      Task 2.1-2.3        Task 3.1-3.2        Task 4.1-4.3       Task 5.1-5.3
```

每个 Phase 结束时有一个可运行的里程碑：
- Phase 1 结束 → 能 fetch + 存储 + 读取数据
- Phase 2 结束 → 能生成策略信号
- Phase 3 结束 → 能跑完整回测，出报告
- Phase 4 结束 → 能在 testnet 下单
- Phase 5 结束 → 完整系统可用

---

## 关键设计决策

1. **向量化回测，非事件驱动** — 对于分钟/小时级策略，向量化更快更简单。事件驱动留给 L2 做高频。
2. **策略与引擎解耦** — Strategy 只产出信号数组，不接触账户/订单。
3. **先 OKX Testnet** — Phase 4 在 testnet 验证，资金风险为零。
4. **SQLite 单文件数据库** — 轻量、无需运维，后期可切 PostgreSQL/TimescaleDB，因为存储层有抽象。
5. **ccxt 统一交易所接口** — 原生支持 100+ 交易所，扩展成本低。
