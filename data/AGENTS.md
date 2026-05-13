# CryptoQuant Data Knowledge Base

**Module:** Data management layer
**Purpose:** Exchange API access, data models, SQLite storage, data validation, historical download

## OVERVIEW

OKX exchange integration via ccxt. Core OHLCV candle model with SQLite-backed
unified repository for persistence. Standalone validation module for data quality.
CLI-based downloader supports incremental, full, and backfill modes with automatic
pagination and since-probing.

## STRUCTURE

```
data/
├── __init__.py           # Public exports (OHLCVCandle, get_repository, validation helpers)
├── models.py             # OHLCVCandle dataclass (frozen, Decimal precision)
├── manager.py            # OKXClient: OKX API wrapper (ccxt + retry + proxy + pagination)
├── validation.py         # Data quality validation (timestamps, prices, volume, auto-repair)
├── downloader.py         # Historical download orchestrator (incremental/full/backfill CLI)
├── verify_apikey.py      # 3-step API key verification (env → public → private)
├── repository/           # Unified data access layer
│   ├── __init__.py       # Singleton factory (get_repository / reset_repository)
│   ├── base.py           # DataRepository abstract interface
│   └── sqlite.py         # SQLite implementation (upsert, WAL mode)
└── cryptoquant.db        # SQLite database (gitignored)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Candle model | `models.py:OHLCVCandle` | Frozen dataclass, fields match DB 1:1 |
| Fetch single page | `manager.py:OKXClient.fetch_ohlcv()` | ccxt wrapper, retry with backoff, max 100 |
| Fetch full history | `manager.py:OKXClient.fetch_ohlcv_history()` | Auto-pagination + since-probing |
| Download data | `downloader.py:download()` | Incremental/full/backfill modes |
| Verify API key | `verify_apikey.py:main()` | `python -m data.verify_apikey` |
| Save/load | `repository/sqlite.py:SQLiteRepository` | Upsert by composite PK |
| Validate data | `validation.py:validate_ohlcv_data()` | DataFrame-based quality checks |
| Per-candle validation | `validation.py:validate_candle()` | Single candle sanity check |
| Batch validation | `validation.py:validate_candles_batch()` | Returns (valid, rejected) tuple |
| Auto-repair | `validation.py:auto_repair_data()` | Forward-fill gaps, flag anomalies |
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

# Get time boundaries
latest = repo.get_latest_timestamp("BTC/USDT", "1h")
earliest = repo.get_earliest_timestamp("BTC/USDT", "1h")
```

**API Calls:**
- Rate limited via ccxt built-in `enableRateLimit=True`
- 0.1s sleep between pagination pages
- Retry with exponential backoff on rate limit, timeout, network errors
- Proxy auto-detected from `HTTPS_PROXY` / `HTTP_PROXY` env vars
- Sandbox mode by default
- `fetch_ohlcv()` = single page (≤100 candles, for real-time)
- `fetch_ohlcv_history()` = auto-pagination + since-probing (for bulk download)

## ANTI-PATTERNS

**FORBIDDEN:**
- Using `float` for prices (precision loss, must use `Decimal`)
- Hardcoding API credentials (use `.env` + python-dotenv)
- Calling `reset_repository()` in production code (tests only)

**WARNINGS:**
- `fetch_ohlcv()` returns ms timestamps
- OKX `fetch_ohlcv` max 100 candles per call — use `fetch_ohlcv_history()` for bulk
- OKX returns **empty** when `since` is before the pair's listing date — `fetch_ohlcv_history` auto-probes to find valid start
- Sandbox environment has limited historical data
- Production API credentials must be set in `.env` before `--no-sandbox`

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
- Composite PK + `sqlite_upsert(on_conflict_do_update)` = true upsert (not skip-on-dup)

## EXCEPTIONS

| Exception | When | Handling |
|-----------|------|----------|
| `OKXAPIError` | Base class | — |
| `OKXAuthenticationError` | Bad credentials | Fail immediately |
| `OKXRateLimitError` | Rate limit exceeded | Retry with longer backoff |
| `OKXTimeoutError` | API timeout | Retry with backoff |
| `OKXNetworkError` | Connection lost | Retry with backoff |

## CLI COMMANDS

**Download data:**
```bash
# Incremental (default): fetch new data after latest stored
python -m data.downloader --pair BTC/USDT --timeframe 1h --days 365

# From specific date
python -m data.downloader --pair ETH/USDT --timeframe 4h --since 2024-01-01

# Full re-download from start date
python -m data.downloader --pair BTC/USDT --timeframe 1h --full --sandbox

# Backfill N days before earliest stored
python -m data.downloader --pair BTC/USDT --timeframe 1h --backfill 180

# Backfill to beginning of available data
python -m data.downloader --pair BTC/USDT --timeframe 1d --backfill

# Production environment
python -m data.downloader --pair BTC/USDT --timeframe 1h --days 365 --no-sandbox
```

**Verify API key:**
```bash
python -m data.verify_apikey --sandbox
python -m data.verify_apikey  # production (requires .env credentials)
```

## DOWNLOAD MODES

| Mode | Flag | Behavior |
|------|------|----------|
| Incremental | (default) | Fetch data after `latest_timestamp` in DB |
| Full | `--full` | Re-download from `--since` or `now - --days` |
| Backfill N | `--backfill N` | Fetch N days before `earliest_timestamp` in DB |
| Backfill unlimited | `--backfill` | Fetch from beginning of available data |

Key behaviors:
- `--backfill` requires existing data in DB (errors if none found)
- `--backfill` without argument auto-probes OKX for the earliest valid `since` (handles OKX returning empty for too-early dates)
- `--days` default is 365 regardless of timeframe
- `--since YYYY-MM-DD` overrides `--days`
- Three modes are mutually exclusive

## SINCE-PROBING MECHANISM

OKX returns an empty response when `since` precedes a pair's listing date.
`fetch_ohlcv_history()` handles this automatically:

1. First page request returns empty
2. Binary search between `since` and `until` (or current time) to find earliest valid `since`
3. Resume normal pagination from the discovered start point

This makes `--backfill` (unlimited) work reliably across all pairs and timeframes
without needing to know each pair's listing date in advance.

## PROGRAMMATIC USAGE

```python
from data.manager import OKXClient
from data.models import OHLCVCandle
from data.repository import get_repository
from data.validation import validate_candle, validate_candles_batch, validate_ohlcv_data
from data.downloader import download

# Fetch data (single page)
client = OKXClient(sandbox=True)
candles = client.fetch_ohlcv("BTC/USDT", "1h", limit=100)

# Fetch full history with pagination
candles = client.fetch_ohlcv_history("BTC/USDT", "1h", since=1700000000000)

# Validate single candle
is_valid, reason = validate_candle(candle)

# Validate batch (for downloader workflow)
valid, rejected = validate_candles_batch(candles)

# Save to SQLite
repo = get_repository()
repo.save_candles(valid, "BTC/USDT", "1h")

# Load and validate full dataset
df = repo.load_as_dataframe("BTC/USDT", "1h")
report = validate_ohlcv_data(df, "BTC/USDT", "1h")
print(report.status)  # PASS / WARN / FAIL

# Download via orchestrator
result = download(pair="BTC/USDT", timeframe="1h", days=365, sandbox=True)
print(result)  # DownloadResult(...)
```
