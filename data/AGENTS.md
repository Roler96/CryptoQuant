# CryptoQuant Data Knowledge Base

**Module:** Data management layer  
**Purpose:** Exchange API access, data models, SQLite storage, data validation

## OVERVIEW

OKX exchange integration via ccxt. Core OHLCV candle model with SQLite-backed
unified repository for persistence. Standalone validation module for data quality.

## STRUCTURE

```
data/
├── models.py          # OHLCVCandle dataclass (frozen, Decimal precision)
├── manager.py         # OKXClient: OKX API wrapper (ccxt + retry)
├── validation.py      # Data quality validation (timestamps, prices, volume)
├── repository/        # Unified data access layer
│   ├── __init__.py    # Singleton factory (get_repository / reset_repository)
│   ├── base.py        # DataRepository abstract interface
│   └── sqlite.py      # SQLite implementation
└── __init__.py        # Public exports (OHLCVCandle, get_repository)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Candle model | `models.py:OHLCVCandle` | Frozen dataclass, fields match DB 1:1 |
| Fetch OHLCV | `manager.py:OKXClient.fetch_ohlcv()` | ccxt wrapper, retry with backoff |
| Save/load | `repository/sqlite.py:SQLiteRepository` | Composite PK dedup |
| Validate data | `validation.py:validate_ohlcv_data()` | DataFrame-based quality checks |
| Per-candle validation | `validation.py:validate_candle()` | Single candle sanity check |
| API errors | `manager.py:OKXAPIError` hierarchy | Retry on rate limit/timeout/network |

## CONVENTIONS

**Data Model:**
```python
from data.models import OHLCVCandle

candle = OHLCVCandle(
    pair="BTC/USDT",
    timeframe="1h",
    timestamp=1715522400000,  # ms
    open=Decimal("67000.00"),
    high=Decimal("67500.00"),
    low=Decimal("66500.00"),
    close=Decimal("67200.00"),
    volume=Decimal("1234.56"),
)
```

- `frozen=True` dataclass (immutable)
- Timestamps in **milliseconds** (Unix epoch)
- All prices/volumes use `Decimal`
- `iso_time` property returns UTC ISO 8601 string
- Field names match DB columns exactly: `open`, `high`, `low`, `close`

**Repository:**
```python
from data.repository import get_repository

repo = get_repository()

# Save candles (upsert by composite PK)
repo.save_candles(candles, "BTC/USDT", "1h")

# Load as DataFrame (for Backtrader)
df = repo.load_as_dataframe("BTC/USDT", "1h")

# Load as candle objects
candles = repo.load_candles("BTC/USDT", "1h", limit=100)

# Check what's available
stats = repo.get_stats("BTC/USDT", "1h")
all_data = repo.list_all()
```

**API Calls:**
- Rate limited via ccxt built-in `enableRateLimit=True`
- Retry on rate limit, timeout, network errors
- Sandbox mode by default
- No pagination inside client -- caller must loop

## ANTI-PATTERNS

**FORBIDDEN:**
- Using `float` for prices (precision loss, must use `Decimal`)
- Hardcoding API credentials (use `.env` + python-dotenv)
- Calling `reset_repository()` in production code (tests only)

**WARNINGS:**
- `fetch_ohlcv()` returns ms timestamps
- OKX `fetch_ohlcv` max 100 candles per call -- caller must paginate
- Sandbox mode by default

## DATABASE SCHEMA

Single table `candles` with composite primary key:
```sql
CREATE TABLE candles (
    pair        TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,
    iso_time    TEXT NOT NULL,
    open        NUMERIC(20, 8) NOT NULL,
    high        NUMERIC(20, 8) NOT NULL,
    low         NUMERIC(20, 8) NOT NULL,
    close       NUMERIC(20, 8) NOT NULL,
    volume      NUMERIC(20, 8) NOT NULL,
    PRIMARY KEY (pair, timeframe, timestamp)
);
```

- WAL mode for concurrent read/write
- NUMERIC(20, 8) preserves Decimal precision
- Composite PK naturally deduplicates on upsert

## EXCEPTIONS

| Exception | When | Handling |
|-----------|------|----------|
| `OKXRateLimitError` | Rate limit exceeded | Retry with backoff |
| `OKXTimeoutError` | API timeout | Retry with backoff |
| `OKXNetworkError` | Connection lost | Retry with backoff |
| `OKXAuthenticationError` | Bad credentials | Fail immediately |

## COMMANDS

```python
from data.manager import OKXClient
from data.models import OHLCVCandle
from data.repository import get_repository
from data.validation import validate_candle, validate_ohlcv_data

# Fetch data
client = OKXClient(sandbox=True)
candles = client.fetch_ohlcv("BTC/USDT", "1h", limit=100)

# Validate single candle
if not validate_candle(candle):
    print(f"Invalid: {candle}")

# Save to SQLite
repo = get_repository()
repo.save_candles(candles, "BTC/USDT", "1h")

# Load and validate full dataset
df = repo.load_as_dataframe("BTC/USDT", "1h")
report = validate_ohlcv_data(df, "BTC/USDT", "1h")
print(report.status)  # PASS / WARN / FAIL
```
