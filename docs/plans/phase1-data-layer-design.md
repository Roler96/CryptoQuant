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

### 3.3 代码默认值（硬编码兜底）

```python
DEFAULTS = {
    "exchange": {"default": "okx"},
    "data": {
        "db_path": "data/cryptoquant.db",
        "cache": {"max_size": 128, "ttl_seconds": 300},
        "fetch": {"max_candles_per_request": 300, "chunk_days": 7},
    },
    "trading": {"default_quote": "USDT", "min_order_usdt": 10.0},
    "logging": {"level": "INFO", "dir": "logs/"},
}
```

### 3.4 公开 API

```python
def load_config(config_path: str | None = None) -> dict:
    """加载完整配置（YAML + .env overlay）。

    Args:
        config_path: YAML 路径，默认 <project_root>/config.yaml

    Returns:
        合并后的配置字典。交易所 API Key 等敏感值通过 .env 注入，
        以环境变量名（如 'OKX_API_KEY'）作为顶级 key。
    """

def get_data_config(config: dict | None = None) -> dict:
    """提取 data 子配置，带默认值回填。
    便捷方法，避免上层到处写 config.get("data", {}).get("db_path", "...").
    """
```

### 3.5 线程安全

`load_config()` 每次调用重新读取文件 — **无状态，天然线程安全**。不需要单例或锁。

---

## 4. Fetcher 设计 (fetcher.py)

### 4.1 类图

```
┌─────────────────────────────────────────┐
│            OHLCVFetcher                  │
├─────────────────────────────────────────┤
│ - exchange: ccxt.Exchange               │
│ - exchange_name: str                    │
│ - max_candles: int                      │
├─────────────────────────────────────────┤
│ + fetch(symbol, timeframe, limit, since)│
│   → pd.DataFrame                        │
│ + fetch_range(symbol, tf, start, end)   │
│   → pd.DataFrame                        │
│ + available_timeframes() → list[str]    │
│ + available_symbols() → list[str]       │
└─────────────────────────────────────────┘
```

### 4.2 核心方法详细设计

#### `fetch()` — 单次拉取

```python
def fetch(
    self,
    symbol: str,           # "BTC/USDT"
    timeframe: str,        # "1m"|"5m"|"15m"|"30m"|"1h"|"4h"|"1d"|"1w"
    limit: int = 300,      # 1-300
    since: int | None = None,  # Unix ms
) -> pd.DataFrame:
```

**返回值规格：**
- 列: `["open", "high", "low", "close", "volume"]`
- 索引: `DatetimeIndex`（UTC，无时区）
- 类型: 所有价格为 `float64`，volume 为 `float64`
- 排序: 按时间升序
- 空结果: 返回空 DataFrame（保留列名）

**错误处理表：**

| 异常 | 来源 | 处理方式 |
|------|------|---------|
| `ccxt.BadSymbol` | 无效交易对 | 转为 `ValueError("Invalid symbol: ...")` |
| `ccxt.NetworkError` | 网络超时 | 转为 `ConnectionError`，附带原始信息 |
| `ccxt.RateLimitExceeded` | 触发限速 | 转为 `RuntimeError`，提示等待 |
| `ccxt.ExchangeNotAvailable` | 交易所维护 | 转为 `RuntimeError` |

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
    df = fetch(symbol, timeframe, limit=max_candles, since=cursor)
    if df.empty:
        break
    chunks.append(df)
    cursor = df.index[-1].timestamp() * 1000 + 1  # ms, next candle
    sleep(rate_limit_pause)  # 避免触发限速
return concat + dedup + sort
```

**关键细节：**
- `cursor` 推进使用 `df.index[-1] + 1ms`，避免重复拉取同一根 K 线
- 每次 fetch 之间 `sleep(0.2)` 尊重 rate limit
- 最终去重（`drop_duplicates`）以 index 为准

### 4.3 ccxt 实例化

```python
def __init__(self, exchange: str = "okx", testnet: bool = True):
    exchange_class = getattr(ccxt, exchange)
    self.exchange = exchange_class({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    if testnet:
        self.exchange.set_sandbox_mode(True)
```

**注意：** Phase 1 不需要 API Key。ccxt 公开接口（OHLCV）对大多数交易所无需认证。

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
def _table_name(exchange: str, symbol: str, timeframe: str) -> str:
    """BTC/USDT → BTC_USDT"""
    safe = symbol.replace("/", "_").replace("-", "_")
    return f"ohlcv_{exchange}_{safe}_{timeframe}"
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

**实现（executemany 批量写入）：**

```python
table = _table_name(exchange, symbol, timeframe)
self._ensure_table(table)

rows = []
for ts, row in df.iterrows():
    ts_ms = int(ts.timestamp() * 1000)
    rows.append((ts_ms, row["open"], row["high"], row["low"], row["close"], row["volume"]))

sql = f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?, ?, ?, ?)"
with self.conn:
    self.conn.executemany(sql, rows)
return len(rows)
```

**性能考虑：**
- `executemany` + 单事务 → 10 万行 ~0.5 秒
- 外层的 `with self.conn:` 自动 COMMIT/ROLLBACK

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
    if lookback is not None:
        latest = self.store.get_latest(exchange, symbol, tf)
        if latest is None:
            return False
        # 计算 lookback 对应的起始时间
        expected_start = _lookback_to_start(tf, lookback)
        oldest = self.store.get_range(exchange, symbol, tf)[0]
        return oldest <= expected_start
    elif start is not None:
        db_start, db_end = self.store.get_range(exchange, symbol, tf)
        return db_start <= start and db_end >= end
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

    def _get_l1(self, key: CacheKey) -> pd.DataFrame | None:
        """查 L1，检查 TTL。过期返回 None 并删除。"""
        entry = self._l1.get(key)
        if entry is None:
            return None
        if self._ttl > 0 and time.time() - entry.cached_at > self._ttl:
            del self._l1[key]
            return None
        # LRU: 移到末尾
        self._l1.move_to_end(key)
        return entry.df

    def _set_l1(self, key: CacheKey, df: pd.DataFrame):
        """写入 L1，超出 max_size 时淘汰最旧条目。"""
        if key in self._l1:
            del self._l1[key]
        elif len(self._l1) >= self._max_size:
            self._l1.popitem(last=False)  # FIFO 淘汰
        self._l1[key] = CacheEntry(
            df=df.copy(),  # 浅拷贝，避免外部修改污染缓存
            cached_at=time.time(),
            latest_ts=int(df.index[-1].timestamp() * 1000) if len(df) > 0 else None,
        )
```

**为什么用 `df.copy()`？**
- DataFrame 是可变的。如果调用者拿到缓存引用后做了 `df["close"] *= 2`，缓存就被污染了。
- `.copy()` 创建新的 DataFrame 对象，但内部 numpy 数组共享内存（copy-on-write），所以几乎无性能损失。

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
| `cryptoquant/config.py` | ~60 | YAML + .env 配置加载 |
| `cryptoquant/data/__init__.py` | ~10 | 导出 DataCache |
| `cryptoquant/data/fetcher.py` | ~80 | ccxt 封装，fetch + fetch_range |
| `cryptoquant/data/store.py` | ~120 | SQLite CRUD，表管理 |
| `cryptoquant/data/cache.py` | ~150 | 三级缓存，统一入口 |
| `tests/test_config.py` | ~30 | 配置加载测试 |
| `tests/test_fetcher.py` | ~60 | Fetcher 集成测试 |
| `tests/test_store.py` | ~80 | Store 单元测试 |
| `tests/test_cache.py` | ~100 | Cache 集成测试（mock L3） |
| `config.yaml` | ~30 | 用户配置 |
| `.env.example` | ~8 | API Key 模板 |
| `pyproject.toml` | ~35 | 项目依赖 |

---

## 9. 依赖关系

```
pyproject.toml
  ├── ccxt >= 4.0.0        ← fetcher
  ├── pandas >= 2.0.0      ← fetcher, store, cache
  ├── numpy >= 1.24.0      ← pandas 依赖
  ├── pyyaml >= 6.0        ← config
  ├── python-dotenv >= 1.0 ← config
  └── loguru >= 0.7.0      ← Phase 5 正式使用，Phase 1 先安装
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
