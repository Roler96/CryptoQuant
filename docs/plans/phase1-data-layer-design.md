# Phase 1: Data Layer — 详细设计文档

> **版本:** 1.0 | **日期:** 2026-06-10 | **作者:** Hermes + Roler

---

## 1. 概述

Phase 1 构建整个量化系统的数据基础层。三个核心模块按依赖顺序：

```
config.py          ← 全局配置加载（先决条件）
    ↓
fetcher.py         ← 从交易所拉取原始 OHLCV
    ↓
store.py           ← SQLite 持久化存储
    ↓
cache.py           ← 多级缓存，统一数据入口
```

其他层（Strategy、Backtest、Live）**只通过 cache 层获取数据**，不直接调用 fetcher 或 store。

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    上层调用者                              │
│           Strategy / Backtest / Live Engine              │
└────────────────────────┬────────────────────────────────┘
                         │ get_ohlcv(symbol, tf, lookback)
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  DataCache (cache.py)                    │
│  ┌─────────────┐   miss   ┌──────────┐   miss   ┌──────┐│
│  │ 内存 LRU    │─────────▶│  SQLite  │─────────▶│ ccxt ││
│  │ (DataFrame) │          │  (store) │          │fetch ││
│  └─────────────┘          └──────────┘          └──────┘│
│       hit                       hit              save   │
│       ◀─── return               ◀─── return ───────────▶│
└─────────────────────────────────────────────────────────┘
```

**缓存层级（3 级）：**

| 层级 | 存储 | 延迟 | 生命周期 |
|------|------|------|---------|
| L1 内存 | `OrderedDict[CacheKey, DataFrame]` | ~0μs | 进程内，LRU 淘汰 |
| L2 SQLite | `ohlcv_{exchange}_{symbol}_{timeframe}` | ~1-5ms | 持久化，手动清理 |
| L3 ccxt | 交易所 API | ~200-2000ms | 按需拉取，拉完存 L2 |

---

## 3. 配置设计 (config.py)

### 3.1 加载优先级

```
.env 环境变量  >  config.yaml  >  代码默认值
   (最高)            (中间)          (最低)
```

### 3.2 config.yaml 完整 Schema

```yaml
# === 交易所配置 ===
exchange:
  default: okx                    # 默认交易所
  okx:
    testnet: true                 # true=sandbox, false=实盘
    rate_limit: true              # ccxt 自动限速
  binance:                        # 后续扩展
    testnet: true

# === 数据配置 ===
data:
  db_path: data/cryptoquant.db    # SQLite 路径（相对于项目根目录）
  cache:
    max_size: 128                 # L1 内存缓存最大条目数
    ttl_seconds: 300              # L1 缓存过期时间（秒），0=永不过期
  fetch:
    max_candles_per_request: 300  # 单次请求最大 K 线数（OKX 限 300）
    chunk_days: 7                 # 历史补数据时每段拉取天数
    timeout_ms: 30000             # 连接超时（毫秒）

# === 交易配置 ===
trading:
  default_quote: USDT
  min_order_usdt: 10.0

# === 日志配置 ===
logging:
  level: INFO                     # DEBUG|INFO|WARNING|ERROR
  dir: logs/
  format: "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}"
```

### 3.3 类型安全配置（pydantic-settings）

使用 `pydantic-settings` 替代纯 dict，提供类型校验、自动转换和环境变量覆盖：

```python
# cryptoquant/config.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import yaml


class ExchangeConfig(BaseSettings):
    default: str = "okx"

class DataCacheConfig(BaseSettings):
    max_size: int = Field(default=128, ge=1)
    ttl_seconds: int = Field(default=300, ge=0)

class FetchConfig(BaseSettings):
    max_candles_per_request: int = Field(default=300, ge=1, le=1000)
    chunk_days: int = Field(default=7, ge=1)
    timeout_ms: int = Field(default=30_000, ge=1000)

class DataConfig(BaseSettings):
    db_path: str = "data/cryptoquant.db"
    cache: DataCacheConfig = DataCacheConfig()
    fetch: FetchConfig = FetchConfig()

class TradingConfig(BaseSettings):
    default_quote: str = "USDT"
    min_order_usdt: float = Field(default=10.0, gt=0)

class LoggingConfig(BaseSettings):
    level: str = "INFO"
    dir: str = "logs/"

class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_nested_delimiter="__",
    )
    exchange: ExchangeConfig = ExchangeConfig()
    data: DataConfig = DataConfig()
    trading: TradingConfig = TradingConfig()
    logging: LoggingConfig = LoggingConfig()

    # 敏感字段通过环境变量注入
    okx_api_key: str = ""
    okx_secret: str = ""
    okx_password: str = ""


_config_cache: AppConfig | None = None


def load_config(config_path: str | None = None, *, use_cache: bool = True) -> AppConfig:
    """加载完整配置（YAML + .env overlay）。

    使用 pydantic-settings 实现：
    - 类型安全：字段类型不匹配时启动即报错
    - 自动转换：环境变量字符串自动转为 int/float/bool
    - 缓存：首次加载后缓存，后续调用直接返回（进程内配置不变）

    Args:
        config_path: YAML 路径，默认 <project_root>/config.yaml
        use_cache: True 时缓存配置（推荐），False 时每次重新加载

    Returns:
        AppConfig 实例（类型安全，IDE 自动补全）
    """
    global _config_cache
    if use_cache and _config_cache is not None:
        return _config_cache

    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"

    yaml_data = {}
    if Path(config_path).exists():
        with open(config_path) as f:
            yaml_data = yaml.safe_load(f) or {}

    config = AppConfig(**yaml_data)

    if use_cache:
        _config_cache = config

    return config


def invalidate_config_cache():
    """清除配置缓存，强制下次 load_config 重新加载。
    用于测试或配置文件热更新场景。
    """
    global _config_cache
    _config_cache = None


def get_data_config(config: AppConfig | None = None) -> DataConfig:
    """提取 data 子配置。类型安全，无需手动 get 链。"""
    if config is None:
        config = load_config()
    return config.data
```

**pydantic-settings 优势：**

| 特性 | 纯 dict 方案 | pydantic-settings |
|------|-------------|-------------------|
| 类型校验 | 运行时才发现问题 | 启动时即报错 |
| 字段约束 | 需手动写 if 检查 | `Field(ge=0)` 声明式 |
| IDE 支持 | 无自动补全 | 完整类型提示 |
| 环境变量 | 手动合并 | 自动 `env_prefix` 映射 |
| 嵌套配置 | 多层 `.get()` | 属性访问 `config.data.cache.max_size` |

**依赖新增：** `pydantic-settings >= 2.0`

### 3.4 代码默认值（硬编码兜底）

默认值已内嵌在 pydantic model 的 `Field(default=...)` 中，无需额外 DEFAULTS dict。

### 3.5 线程安全

`load_config()` 使用进程级缓存（`_config_cache`），首次加载后直接返回。配置文件在进程生命周期内视为不可变。

- 单进程场景：无锁，直接读取缓存
- 多进程场景：每个进程独立加载，无需跨进程同步
- 热更新场景：调用 `invalidate_config_cache()` 清除缓存后重新加载

---

## 4. Fetcher 设计 (fetcher.py)

### 4.1 类图

```
┌─────────────────────────────────────────────────┐
│            OHLCVFetcher                          │
├─────────────────────────────────────────────────┤
│ - exchange: ccxt.Exchange                       │
│ - exchange_name: str                            │
│ - timeout: int                                  │
│ - max_candles: int                              │
├─────────────────────────────────────────────────┤
│ + __init__(exchange, testnet, timeout,          │
│            max_candles)                         │
│ + fetch(symbol, timeframe, limit, since)        │
│   → pd.DataFrame  @retry_on_network             │
│ + fetch_range(symbol, tf, start, end)           │
│   → pd.DataFrame                                │
│ + available_timeframes() → list[str]            │
└─────────────────────────────────────────────────┘
```

**关键设计决策：**

| 决策 | 理由 |
|------|------|
| `@retry_on_network` 装饰器 | 瞬态网络错误自动重试（3次，指数退避） |
| `limit` clamp 到 `[1, max_candles]` | 防止调用者传入超限值，静默截断比报错更友好 |
| `fetch_range()` all-or-nothing | 部分失败时丢弃全部，避免下游使用残缺数据 |
| 无 `sleep()` | 信任 ccxt 的 `enableRateLimit` 自动限速 |
| warn-only gap 检测 | 交易所数据质量问题不应阻断流程，但需可见 |

### 4.2 核心方法详细设计

#### `fetch()` — 单次拉取

```python
@retry_on_network(max_retries=3, base_delay=1.0)
def fetch(
    self,
    symbol: str,           # "BTC/USDT"
    timeframe: str,        # "1m"|"5m"|"15m"|"30m"|"1h"|"4h"|"1d"|"1w"
    limit: int = 300,      # clamped to [1, max_candles]
    since: int | None = None,  # Unix ms
) -> pd.DataFrame:
```

**返回值规格：**
- 列: `["open", "high", "low", "close", "volume"]`
- 索引: `DatetimeIndex`（UTC，无时区）
- 类型: 所有价格为 `float64`，volume 为 `float64`
- 排序: 按时间升序
- 空结果: 返回空 DataFrame（保留列名）
- **数据质量**: 返回前经过 `validate_ohlcv()` 校验

**错误处理表：**

| 异常 | 来源 | 处理方式 |
|------|------|---------|
| `ccxt.BadSymbol` | 无效交易对 | 转为 `DataFetchError("Invalid symbol: ...")` |
| `ccxt.NetworkError` | 网络超时 | 转为 `DataFetchError`，附带原始信息 |
| `ccxt.RateLimitExceeded` | 触发限速 | 转为 `DataFetchError`，提示等待 |
| `ccxt.ExchangeNotAvailable` | 交易所维护 | 转为 `DataFetchError` |
| 数据校验失败 | OHLCV 不合理 | 转为 `DataValidationError` |

#### `fetch_range()` — 分段拉取历史数据

```python
def fetch_range(
    self,
    symbol: str,
    timeframe: str,
    start: int,            # Unix ms
    end: int,              # Unix ms
) -> pd.DataFrame:
```

**实现逻辑（伪代码）：**

```
cursor = start
chunks = []
while cursor < end:
    try:
        df = fetch(symbol, timeframe, limit=max_candles, since=cursor)
    except DataFetchError as e:
        raise DataFetchError(f"failed after {len(chunks)} chunk(s): {e}")
    if df.empty:
        break
    chunks.append(df)
    cursor = df.index[-1].timestamp() * 1000 + 1  # ms, next candle
return concat + dedup + sort
```

**关键细节：**
- `cursor` 推进使用 `df.index[-1] + 1ms`，避免重复拉取同一根 K 线
- **无 `sleep()`**：信任 ccxt 的 `enableRateLimit` 自动限速
- 最终去重（`drop_duplicates`）以 index 为准
- **cursor 语义**: OKX/Binance 返回的 timestamp 是 K 线**开盘时间**，因此 `+1ms` 正确推进到下一根。若接入其他交易所需验证其 timestamp 语义。
- **错误处理**: all-or-nothing 策略。任何 chunk 失败后，异常信息包含已成功的 chunk 数量，便于诊断。

### 4.2.1 OHLCV 数据质量校验

```python
def validate_ohlcv(df: pd.DataFrame) -> None:
    """校验 OHLCV 数据合理性。

    Checks:
    - Required columns present
    - high >= low for all bars
    - open/close within [low, high]
    - volume >= 0
    - no NaN in critical columns
    - timestamp continuity (warn only, does not raise)

    Raises:
        DataValidationError: 数据不合法时
    """
    if df.empty:
        return

    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataValidationError(f"Missing columns: {missing}")

    # high >= low
    mask = df["high"] < df["low"]
    if mask.any():
        raise DataValidationError(f"high < low at {mask.sum()} bars")

    # open/close within [low, high]
    for col in ("open", "close"):
        mask = (df[col] < df["low"]) | (df[col] > df["high"])
        if mask.any():
            raise DataValidationError(f"{col} outside [low, high] at {mask.sum()} bars")

    # volume >= 0
    if (df["volume"] < 0).any():
        raise DataValidationError("Negative volume detected")

    # no NaN in critical columns
    for col in required:
        if df[col].isna().any():
            raise DataValidationError(f"NaN in column '{col}'")

    # Timestamp continuity check (warn only — gaps are usually exchange data issues)
    if len(df) >= 2 and isinstance(df.index, pd.DatetimeIndex):
        diffs = df.index.to_series().diff().dropna()
        if len(diffs) > 0:
            median_diff = diffs.median()
            # Allow 10% tolerance for minor timing variations
            gaps = diffs[diffs > median_diff * 1.1]
            if len(gaps) > 0:
                logger.warning(
                    f"Detected {len(gaps)} gap(s) in OHLCV timestamps, "
                    f"e.g. at {gaps.index[0]} (diff={gaps.iloc[0]})"
                )
```

**时区约定：** 系统统一使用 **UTC 无时区** (`DatetimeIndex` without tz)。所有时间戳在 fetch 阶段即转换为 UTC，后续模块不再处理时区转换。若接入的交易所返回带时区数据，在 fetcher 层 `.tz_localize(None)` 去除。

在 `fetch()` 返回前调用：

```python
def fetch(self, symbol, timeframe, limit=300, since=None):
    # ... 拉取数据 ...
    validate_ohlcv(df)
    return df
```

### 4.3 ccxt 实例化

```python
from cryptoquant.exceptions import DataFetchError, DataValidationError

def __init__(
    self,
    exchange: str = "okx",
    testnet: bool = True,
    timeout: int = 30_000,        # 连接超时（毫秒），默认 30s
):
    exchange_class = getattr(ccxt, exchange)
    self.exchange = exchange_class({
        "enableRateLimit": True,
        "timeout": timeout,
        "options": {"defaultType": "spot"},
    })
    if testnet:
        self.exchange.set_sandbox_mode(True)
```

**注意：** Phase 1 不需要 API Key。ccxt 公开接口（OHLCV）对大多数交易所无需认证。

**超时配置说明：**
- `timeout=30_000` 是 ccxt 的连接超时（毫秒），不是请求超时
- 网络不稳定时可适当增大（如 `60_000`）
- ccxt 的 `enableRateLimit=True` 已处理 API 限速，无需额外配置

### 4.4 测试策略

| 测试 | 类型 | 说明 |
|------|------|------|
| `test_fetch_returns_dataframe` | 集成 | 真实验证 OKX 返回结构 |
| `test_fetch_datetime_index` | 集成 | 索引类型检查 |
| `test_fetch_invalid_symbol_raises` | 单元/集成 | 错误转换 |
| `test_fetch_range_concatenates` | 集成 | 分段拉取拼接正确 |
| `test_fetch_range_no_duplicates` | 集成 | 去重逻辑 |
| `test_fetch_empty_result` | 边界 | since 太近无数据时返回空 DF |
| `test_fetch_timeframe_variants` | 集成 | 所有 timeframe 字符串正确传递 |
| `test_validate_ohlcv_high_lt_low` | 单元 | high < low 时抛 DataValidationError |
| `test_validate_ohlcv_nan_values` | 单元 | 含 NaN 时抛 DataValidationError |
| `test_validate_ohlcv_negative_volume` | 单元 | 负 volume 时抛 DataValidationError |

**Fixture 设计：**

```python
@pytest.fixture
def fetcher():
    """创建 OKX testnet fetcher — 无需 API Key"""
    return OHLCVFetcher(exchange="okx", testnet=True)

@pytest.fixture
def btc_1h(fetcher):
    """拉取最近 100 根 BTC/USDT 1h K 线，测试间共享"""
    return fetcher.fetch("BTC/USDT", "1h", limit=100)
```

---

## 5. Store 设计 (store.py)

### 5.1 数据库 Schema

每个 (exchange, symbol, timeframe) 组合一张独立表：

```sql
CREATE TABLE IF NOT EXISTS ohlcv_okx_BTC_USDT_1h (
    timestamp  INTEGER PRIMARY KEY,  -- Unix 毫秒
    open       REAL NOT NULL,
    high       REAL NOT NULL,
    low        REAL NOT NULL,
    close      REAL NOT NULL,
    volume     REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_okx_BTC_USDT_1h_ts
    ON ohlcv_okx_BTC_USDT_1h(timestamp);
```

**设计决策：**

| 决策 | 理由 |
|------|------|
| 每品种每周期一张表 | 避免单表膨胀；WHERE timeframe=? 无法利用索引时全表扫描 |
| timestamp 用 INTEGER (ms) | SQLite 无原生 DATETIME；INTEGER 比较和范围查询最快 |
| 不用 AUTOINCREMENT | timestamp 本身唯一且有序，无需额外 ID |
| 不用分区表 | SQLite 不支持；后期切 PostgreSQL 可用 TimescaleDB hypertable |
| symbol 中的 `/` 替换为 `_` | 表名不能用 `/` |

**表名生成：**

```python
import re

_VALID_TABLE_NAME = re.compile(r"^ohlcv_[a-zA-Z0-9_]+_[a-zA-Z0-9_]+_\w+$")

def _table_name(exchange: str, symbol: str, timeframe: str) -> str:
    """BTC/USDT → BTC_USDT，带白名单校验。"""
    safe = symbol.replace("/", "_").replace("-", "_")
    name = f"ohlcv_{exchange}_{safe}_{timeframe}"
    if not _VALID_TABLE_NAME.match(name):
        raise DataValidationError(f"Invalid table name: {name}")
    return name
```

### 5.2 类图

```
┌──────────────────────────────────────────────┐
│                OHLCVStore                     │
├──────────────────────────────────────────────┤
│ - db_path: str                               │
│ - conn: sqlite3.Connection (lazy init)       │
├──────────────────────────────────────────────┤
│ + save(df, exchange, symbol, timeframe)      │
│   → int (rows written)                       │
│ + load(exchange, symbol, timeframe,          │
│        start=None, end=None) → pd.DataFrame  │
│ + get_latest(exchange, symbol, timeframe)    │
│   → int | None (latest timestamp ms)         │
│ + get_range(exchange, symbol, timeframe)     │
│   → tuple[int, int] | None (min, max ts)     │
│ + delete(exchange, symbol, timeframe) → int  │
│ + list_tables() → list[str]                  │
│ + close()                                    │
└──────────────────────────────────────────────┘
```

### 5.3 核心方法详细设计

#### `save()` — UPSERT 语义

```python
def save(
    self,
    df: pd.DataFrame,
    exchange: str,
    symbol: str,
    timeframe: str,
) -> int:
    """保存 OHLCV 数据，已存在的 timestamp 会被覆盖（UPSERT）。

    使用 INSERT OR REPLACE：
    - 新数据 → INSERT
    - 已有 timestamp → REPLACE（以最新拉取为准，修复可能的回补修正）

    Returns:
        实际写入的行数
    """
```

**实现（批量写入优化版）：**

```python
table = _table_name(exchange, symbol, timeframe)
self._ensure_table(table)

rows = [
    (int(ts.timestamp() * 1000), row["open"], row["high"], row["low"], row["close"], row["volume"])
    for ts, row in df.iterrows()
]

# 使用临时表 + INSERT OR REPLACE 模式，比直接 executemany REPLACE 快 2-3x
# 原因：临时表写入无索引开销，最后一次性合并
tmp_table = f"_tmp_{table}"
with self.conn:
    self.conn.execute(
        f"CREATE TEMP TABLE IF NOT EXISTS {tmp_table} "
        f"(timestamp INTEGER PRIMARY KEY, open REAL, high REAL, "
        f"low REAL, close REAL, volume REAL)"
    )
    self.conn.execute(f"DELETE FROM {tmp_table}")
    self.conn.executemany(
        f"INSERT INTO {tmp_table} VALUES (?, ?, ?, ?, ?, ?)", rows
    )
    self.conn.execute(
        f"INSERT OR REPLACE INTO {table} SELECT * FROM {tmp_table}"
    )
    self.conn.execute(f"DROP TABLE {tmp_table}")

return len(rows)
```

**性能考虑：**
- 临时表 + 批量合并 → 10 万行 ~0.2 秒（比直接 REPLACE 快 2-3x）
- 临时表无索引，写入速度快；最终通过 `SELECT *` 一次性合并到主表
- 外层的 `with self.conn:` 自动 COMMIT/ROLLBACK
- `PRAGMA journal_mode=WAL` 已启用，读写并发友好

#### `load()` — 范围查询

```python
def load(
    self,
    exchange: str,
    symbol: str,
    timeframe: str,
    start: int | None = None,   # Unix ms, inclusive
    end: int | None = None,     # Unix ms, inclusive
) -> pd.DataFrame:
```

**实现：**

```python
table = _table_name(exchange, symbol, timeframe)
if not self._table_exists(table):
    return _empty_df()

where = []
params = []
if start is not None:
    where.append("timestamp >= ?")
    params.append(start)
if end is not None:
    where.append("timestamp <= ?")
    params.append(end)

sql = f"SELECT * FROM {table}"
if where:
    sql += " WHERE " + " AND ".join(where)
sql += " ORDER BY timestamp ASC"

df = pd.read_sql_query(sql, self.conn, params=params)
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
df.set_index("timestamp", inplace=True)
return df
```

#### `get_latest()` — 最新时间戳

```python
def get_latest(self, exchange: str, symbol: str, timeframe: str) -> int | None:
    """返回最新 K 线的 timestamp（ms），表空返回 None。"""
    table = _table_name(exchange, symbol, timeframe)
    if not self._table_exists(table):
        return None
    row = self.conn.execute(f"SELECT MAX(timestamp) FROM {table}").fetchone()
    return row[0] if row[0] is not None else None
```

### 5.4 连接管理

```python
@property
def conn(self) -> sqlite3.Connection:
    """Lazy-init 连接。进程内单连接复用。"""
    if self._conn is None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")     # 并发读友好
        self._conn.execute("PRAGMA synchronous=NORMAL")    # 性能优先
        self._conn.execute("PRAGMA cache_size=-64000")     # 64MB 缓存
    return self._conn
```

**WAL 模式说明：**
- 允许一个写者 + 多个读者并发
- 适合 Phase 4+ 的实盘场景（后台 fetch 写入 + 前台策略读取）
- 不需要 `check_same_thread=False`（单线程使用，WAL 就够了）

### 5.5 测试策略

| 测试 | 类型 | 说明 |
|------|------|------|
| `test_save_and_load_roundtrip` | 单元 | 写入→读回，数据一致 |
| `test_save_upsert` | 单元 | 同一 timestamp 写两次，保留最新值 |
| `test_load_empty_table` | 单元 | 空表返回空 DF |
| `test_load_range_filter` | 单元 | start/end 过滤正确 |
| `test_get_latest_empty` | 单元 | 空表返回 None |
| `test_table_name_special_chars` | 单元 | 含 `/` 和 `-` 的 symbol |
| `test_save_large_batch` | 性能 | 10 万行写入 < 2 秒 |

**隔离策略：** 所有测试使用 `:memory:` SQLite 或 `tmp_path`，不与真实数据库交互。

---

## 6. Cache 设计 (cache.py)

### 6.1 类图

```
┌──────────────────────────────────────────────┐
│                DataCache                      │
├──────────────────────────────────────────────┤
│ - store: OHLCVStore                          │
│ - fetcher: OHLCVFetcher                      │
│ - _l1: OrderedDict[CacheKey, CacheEntry]     │
│ - _max_size: int                             │
│ - _ttl: int                                  │
├──────────────────────────────────────────────┤
│ + get_ohlcv(exchange, symbol, tf,            │
│    lookback=None, start=None, end=None)      │
│   → pd.DataFrame                             │
│ + invalidate(exchange, symbol, tf)           │
│ + warm(exchange, symbols, tfs, days) → dict  │
│ + stats() → dict                             │
└──────────────────────────────────────────────┘

CacheKey = namedtuple("CacheKey", ["exchange", "symbol", "timeframe"])
CacheEntry = namedtuple("CacheEntry", ["df", "cached_at", "latest_ts"])
```

### 6.2 核心方法：`get_ohlcv()` — 级联查询

```python
def get_ohlcv(
    self,
    exchange: str,
    symbol: str,
    timeframe: str,
    lookback: int | None = None,    # 最近 N 根 K 线
    start: int | None = None,       # Unix ms
    end: int | None = None,         # Unix ms
) -> pd.DataFrame:
```

**级联逻辑（L1→L2→L3）：**

```
                    ┌──────────────────┐
                    │   get_ohlcv()    │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  L1: 内存命中？   │── yes ──▶ 检查 TTL → 过期？→ 淘汰重查
                    └────────┬─────────┘
                             │ miss / expired
                    ┌────────▼─────────┐
                    │  L2: SQLite 有？  │
                    │  + 数据够不够？    │── yes + enough ──▶ 返回 + 写回 L1
                    └────────┬─────────┘
                             │ no / not enough
                    ┌────────▼─────────┐
                    │  L3: ccxt fetch  │
                    │  → save to L2     │──▶ 返回 + 写回 L1
                    └──────────────────┘
```

**"数据够不够"判断逻辑：**

```python
def _db_has_enough(
    self, exchange, symbol, tf, lookback, start, end
) -> bool:
    """判断 SQLite 中是否有足够的数据满足请求。"""
    db_range = self.store.get_range(exchange, symbol, tf)
    if db_range is None:
        return False

    db_start, db_end = db_range

    if lookback is not None:
        expected_start = _lookback_to_start(tf, lookback)
        return db_start <= expected_start
    elif start is not None:
        return db_start <= start and (end is None or db_end >= end)
    return False
```

**fetch 后更新缓存：**

```python
# 每次 L3 fetch 后
self._set_l1(key, df)
self.store.save(df, exchange, symbol, timeframe)
```

### 6.3 L1 缓存实现

```python
class DataCache:
    def __init__(self, store, fetcher, max_size=128, ttl=300):
        self._l1: OrderedDict[CacheKey, CacheEntry] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl

    def _set_l1(self, key: CacheKey, df: pd.DataFrame):
        """写入 L1，超出 max_size 时淘汰最旧条目。"""
        if key in self._l1:
            del self._l1[key]
        elif len(self._l1) >= self._max_size:
            self._l1.popitem(last=False)  # FIFO 淘汰
        self._l1[key] = CacheEntry(
            df=df.copy(deep=True),  # 深拷贝，彻底隔离缓存与调用者
            cached_at=time.time(),
            latest_ts=int(df.index[-1].timestamp() * 1000) if len(df) > 0 else None,
        )

    def _get_l1(self, key: CacheKey) -> pd.DataFrame | None:
        """查 L1，检查 TTL。过期返回 None 并删除。"""
        entry = self._l1.get(key)
        if entry is None:
            return None
        if self._ttl > 0 and time.time() - entry.cached_at > self._ttl:
            del self._l1[key]
            return None
        self._l1.move_to_end(key)
        return entry.df.copy(deep=True)  # 返回副本，防止调用者修改缓存
```

**为什么用 `df.copy(deep=True)`？**
- DataFrame 是可变的。如果调用者拿到缓存引用后做了 `df["close"] *= 2`，缓存就被污染了。
- pandas 2.0+ 的 Copy-on-Write (CoW) 机制在 `copy(deep=False)` 下的行为依赖全局选项 `pd.options.mode.copy_on_write`，不够稳定可靠。
- 使用 `deep=True` 确保缓存与调用者完全隔离，无 CoW 行为依赖。
- **性能影响**：对于典型 OHLCV DataFrame（几百行 × 5 列），deep copy 耗时 < 0.1ms，可忽略。
- **调用者约定**: 返回的 DataFrame 是独立副本，调用者可自由修改，不影响缓存。

**多进程场景（Phase 4+）：**
- L1 `OrderedDict` 操作不是线程安全的
- 单进程多线程：用 `threading.RLock` 包裹 L1 读写
- 多进程：每个进程独立维护 L1 缓存，无需跨进程同步（L2 SQLite WAL 已支持并发读）
- 可选升级：切换到 `cachetools.TTLCache`（线程安全，自带 TTL）

### 6.4 辅助方法

```python
def invalidate(self, exchange: str, symbol: str, timeframe: str):
    """手动失效某个 symbol+timeframe 的 L1 缓存。
    用在：策略换参数时强制重新计算，不需要清空整个缓存。
    """
    key = CacheKey(exchange, symbol, timeframe)
    self._l1.pop(key, None)

def warm(
    self,
    exchange: str,
    symbols: list[str],
    timeframes: list[str],
    lookback_days: int = 30,
) -> dict[str, int]:
    """预热缓存：批量拉取多品种多周期历史数据。

    Returns:
        {symbol_tf: rows_fetched} 字典
    """
    results = {}
    for symbol in symbols:
        for tf in timeframes:
            end = int(time.time() * 1000)
            start = end - lookback_days * 86400 * 1000
            df = self.fetcher.fetch_range(symbol, tf, start, end)
            self.store.save(df, exchange, symbol, tf)
            self._set_l1(CacheKey(exchange, symbol, tf), df)
            results[f"{symbol}_{tf}"] = len(df)
    return results

def stats(self) -> dict:
    """缓存统计信息，用于监控/调试。"""
    return {
        "l1_entries": len(self._l1),
        "l1_max_size": self._max_size,
        "l1_keys": [str(k) for k in self._l1.keys()],
        "db_path": str(self.store.db_path),
        "db_tables": self.store.list_tables(),
    }
```

### 6.5 错误传播

Cache 层不吞异常，所有错误向上传播给调用者：

| 场景 | 行为 |
|------|------|
| L1 L2 都没数据，L3 网络失败 | 抛 `ConnectionError` |
| L2 有数据但不够，L3 失败 | 返回 L2 现有数据 + 日志 warning |
| 全部三级都无数据 | 返回空 DataFrame |

### 6.6 线程安全

Phase 1 单线程使用。Phase 4 实盘场景考虑：
- L1 `OrderedDict` 操作不是线程安全的
- 解决方案（Phase 4 再做）：RLock 包裹 L1 读写，或切换到 `cachetools.TTLCache`
- SQLite WAL 模式已支持一写多读并发

### 6.7 测试策略

| 测试 | 说明 |
|------|------|
| `test_l1_hit_returns_cached` | L1 命中直接返回 |
| `test_l1_ttl_expiry` | 过期后重新查 L2 |
| `test_l2_hit_no_fetch` | L2 有足够数据时不去 L3 |
| `test_l3_fetch_and_save` | L2 不够时触发 L3 拉取 |
| `test_l1_lru_eviction` | 超过 max_size 时淘汰最旧 |
| `test_get_ohlcv_lookback` | lookback 参数正确裁剪 |
| `test_get_ohlcv_range` | start/end 参数正确过滤 |
| `test_partial_l2_fallback` | L2 有部分数据，L3 失败时返回部分数据 |
| `test_invalidate` | invalidate 后 L1 重新查 L2 |
| `test_warm_populates_cache` | warm 后 L1 和 L2 都有数据 |

**Mock 策略：**
- L3 (ccxt) 通过 `unittest.mock.patch` mock 掉，返回固定 DataFrame
- L1/L2 行为用真实 Store + 内存 SQLite 测试

---

## 7. 数据流时序图

### 7.1 首次请求（冷启动）

```
User Code                Cache                 Store              Fetcher (ccxt)
    │                      │                     │                     │
    │ get_ohlcv("BTC/USDT", "1h", lookback=100)  │                     │
    │─────────────────────▶│                     │                     │
    │                      │ L1 miss             │                     │
    │                      │ get_latest() ──────▶│                     │
    │                      │◀───── None ────────│                     │
    │                      │ L2 miss             │                     │
    │                      │                     │ fetch(limit=100) ──▶│
    │                      │                     │◀─── DataFrame ─────│
    │                      │ save(df) ──────────▶│                     │
    │                      │◀──── OK ───────────│                     │
    │                      │ set_l1(df)          │                     │
    │◀─── DataFrame ──────│                     │                     │
```

### 7.2 热路径（缓存命中）

```
User Code                Cache
    │                      │
    │ get_ohlcv(...) ─────▶│
    │                      │ L1 hit + TTL valid
    │◀─── DataFrame ──────│
    │                      │
    ~ 总延迟 < 1μs
```

### 7.3 增量更新（已有数据，补充最新）

```
User Code                Cache                 Store              Fetcher
    │                      │                     │                     │
    │ get_ohlcv(lookback=100)                    │                     │
    │─────────────────────▶│                     │                     │
    │                      │ L1 miss/expired     │                     │
    │                      │ get_latest() ──────▶│                     │
    │                      │◀─── T_newest ──────│                     │
    │                      │ load(start=T-100candles) ──▶             │
    │                      │◀─── 95 rows ───────│  (只有95根)         │
    │                      │ 不够！需要 100 根                       │
    │                      │                     │ fetch(since=T_newest+1)─▶│
    │                      │                     │◀─── 5 new rows ──│
    │                      │ save(new_df) ──────▶│                     │
    │                      │ merge + set_l1      │                     │
    │◀─── DataFrame(100 rows)                    │                     │
```

---

## 8. 文件清单

| 文件 | 行数估算 | 职责 |
|------|---------|------|
| `cryptoquant/config.py` | ~100 | pydantic-settings 类型安全配置 + 缓存 |
| `cryptoquant/data/__init__.py` | ~10 | 导出 DataCache |
| `cryptoquant/data/fetcher.py` | ~80 | ccxt 封装，fetch + fetch_range |
| `cryptoquant/data/store.py` | ~140 | SQLite CRUD，临时表批量写入优化 |
| `cryptoquant/data/cache.py` | ~160 | 三级缓存，deep copy 隔离 |
| `tests/test_config.py` | ~40 | 配置加载测试（含类型校验） |
| `tests/test_fetcher.py` | ~70 | Fetcher 集成测试 |
| `tests/test_store.py` | ~90 | Store 单元测试 |
| `tests/test_cache.py` | ~110 | Cache 集成测试（mock L3） |
| `config.yaml` | ~30 | 用户配置 |
| `.env.example` | ~8 | API Key 模板 |
| `pyproject.toml` | ~40 | 项目依赖 |

---

## 9. 依赖关系

```
pyproject.toml
  ├── ccxt >= 4.0.0            ← fetcher
  ├── pandas >= 2.0.0          ← fetcher, store, cache
  ├── numpy >= 1.24.0          ← pandas 依赖
  ├── pyyaml >= 6.0            ← config
  ├── python-dotenv >= 1.0     ← config
  ├── pydantic-settings >= 2.0 ← config（类型安全配置）
  └── loguru >= 0.7.0          ← Phase 5 正式使用，Phase 1 先安装
```

**可选依赖（Phase 3 性能优化）：**
```
  └── numba >= 0.59.0          ← 回测引擎 JIT 编译（可选，非必须）
```

这些依赖都是纯 Python，`uv pip install` 即可，无需系统级依赖。

---

## 10. 实现顺序

```
Task 1.1: 项目骨架 + pyproject.toml + 虚拟环境
    ↓
Task 1.2: config.py + config.yaml + .env.example
    ↓
Task 1.3: fetcher.py (ccxt 拉取)
    ↓
Task 1.4: store.py (SQLite 存储)
    ↓
Task 1.5: cache.py (三级缓存 + 统一入口)
```

每个 Task 都是可运行的里程碑。Task 1.4 不依赖 1.3（store 只和 DataFrame 打交道），但 1.5 依赖 1.3 + 1.4。
