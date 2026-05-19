# CryptoQuant Data Knowledge Base

**Module:** Data management layer  
**Purpose:** Exchange API access, data models, SQLite storage, data validation, historical download  
**Lines of Code:** ~2,000 (models 48, manager 474, validation 722, downloader 426, repository 359)

## OVERVIEW

OKX exchange integration via ccxt. Core OHLCV candle model with SQLite-backed
unified repository for persistence. Standalone validation module for data quality.
CLI-based downloader supports incremental, full, and backfill modes with automatic
pagination and since-probing.

## STRUCTURE

```
data/
├── __init__.py           # Public exports (27 lines)
├── models.py             # OHLCVCandle dataclass (48 lines)
├── manager.py            # OKXClient: OKX API wrapper (474 lines)
│                         #   - retry_with_backoff decorator
│                         #   - OKXAPIError exception hierarchy
│                         #   - fetch_ohlcv / fetch_ohlcv_history
│                         #   - since-probing mechanism
├── validation.py         # Data quality validation (722 lines)
│                         #   - validate_candle / validate_candles_batch
│                         #   - ValidationIssue / ValidationReport
│                         #   - check_missing_timestamps
│                         #   - check_price_anomalies
│                         #   - check_volume_validation
│                         #   - auto_repair_data
├── downloader.py         # Historical download orchestrator (426 lines)
│                         #   - download() function
│                         #   - DownloadResult dataclass
│                         #   - CLI entry point
├── verify_apikey.py      # 3-step API key verification (263 lines)
├── repository/           # Unified data access layer
│   ├── __init__.py       # Singleton factory (47 lines)
│   ├── base.py           # DataRepository abstract interface (207 lines)
│   └── sqlite.py         # SQLite implementation (359 lines)
│                         #   - WAL mode + PRAGMA optimizations
│                         #   - Upsert via INSERT OR REPLACE
└── cryptoquant.db        # SQLite database (gitignored)
```

## WHERE TO LOOK

| Task | Location | Lines | Notes |
|------|----------|-------|-------|
| **Data Model** |
| Candle model | `models.py:OHLCVCandle` | 17-39 | Frozen dataclass, fields match DB 1:1 |
| iso_time property | `models.py:42-48` | 6 | UTC ISO 8601 string derivation |
| **API Client** |
| Fetch single page | `manager.py:OKXClient.fetch_ohlcv()` | 202-269 | ccxt wrapper, retry, max 100 |
| Fetch full history | `manager.py:OKXClient.fetch_ohlcv_history()` | 350-458 | Auto-pagination + since-probing |
| Retry decorator | `manager.py:retry_with_backoff()` | 52-117 | Exponential backoff, max 3 retries |
| Since-probing | `manager.py:_probe_valid_since()` | 271-335 | Binary search for valid start |
| Symbol normalize | `manager.py:_normalize_symbol()` | 193-199 | BTCUSDT → BTC/USDT |
| Timeframe convert | `manager.py:_timeframe_to_ms()` | 338-348 | m/h/d/w → milliseconds |
| **Validation** |
| Single candle check | `validation.py:validate_candle()` | 32-64 | OHLC logic, positive prices |
| Batch validation | `validation.py:validate_candles_batch()` | 67-88 | Returns (valid, rejected) |
| Missing timestamps | `validation.py:check_missing_timestamps()` | 198-247 | Gap detection with tolerance |
| Price anomalies | `validation.py:check_price_anomalies()` | 250-321 | 20% threshold default |
| Volume validation | `validation.py:check_volume_validation()` | 324-386 | Negative/zero/NaN check |
| Full validation | `validation.py:validate_ohlcv_data()` | 389-564 | DataFrame → ValidationReport |
| Stored data check | `validation.py:validate_stored_data()` | 567-599 | Load + validate from repo |
| Auto-repair | `validation.py:auto_repair_data()` | 602-722 | Forward-fill gaps, flag anomalies |
| **Download** |
| Download function | `downloader.py:download()` | 80-211 | Incremental/full/backfill modes |
| Backfill download | `downloader.py:_download_backfill()` | 214-328 | Extend history backwards |
| Result dataclass | `downloader.py:DownloadResult` | 44-63 | Frozen, statistics |
| CLI entry | `downloader.py:main()` | 352-423 | argparse, result printing |
| **Repository** |
| Abstract interface | `repository/base.py:DataRepository` | 23-207 | All CRUD methods defined |
| SQLite impl | `repository/sqlite.py:SQLiteRepository` | 92-359 | WAL mode, upsert |
| ORM model | `repository/sqlite.py:CandleModel` | 44-89 | SQLAlchemy declarative |
| Upsert logic | `repository/sqlite.py:save_candles()` | 136-192 | INSERT OR REPLACE |
| DataFrame output | `repository/sqlite.py:load_as_dataframe()` | 234-272 | Backtrader-compatible |
| **API Key Verify** |
| Step 1: env check | `verify_apikey.py:check_env()` | 48-101 | .env file + key presence |
| Step 2: public test | `verify_apikey.py:check_public_connectivity()` | 136-163 | Server time endpoint |
| Step 3: private test | `verify_apikey.py:check_private_access()` | 168-220 | Balance endpoint |

---

## DATA MODEL

### OHLCVCandle (models.py)

```python
@dataclass(frozen=True)
class OHLCVCandle:
    pair: str            # Trading pair (e.g., "BTC/USDT")
    timeframe: str       # Candle interval (e.g., "1h", "4h", "1d")
    timestamp: int       # Unix timestamp in milliseconds
    open: Decimal        # Opening price
    high: Decimal        # Highest price during period
    low: Decimal         # Lowest price during period
    close: Decimal       # Closing price
    volume: Decimal      # Trading volume
    
    @property
    def iso_time(self) -> str:  # UTC ISO 8601 string
        ...
```

**Key characteristics:**
- `frozen=True` — immutable, prevents accidental mutation
- All prices/volumes use `Decimal` for exact precision (never float)
- Timestamps in **milliseconds** (Unix epoch)
- Field names match DB columns exactly: `open`, `high`, `low`, `close` (NOT `open_price`)
- `iso_time` property derives UTC ISO 8601 string from timestamp

**Creating candles:**
```python
from decimal import Decimal
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

# Access derived property
print(candle.iso_time)  # '2024-05-12T14:00:00+00:00'
```

---

## API CLIENT (manager.py)

### OKXClient

OKX API client using ccxt library with:

- **Built-in rate limiting**: `enableRateLimit=True`
- **Retry with exponential backoff**: `@retry_with_backoff` decorator
- **Environment-based credentials**: `.env` file
- **Sandbox mode support**: Testnet vs production
- **Proxy auto-detection**: HTTPS_PROXY / HTTP_PROXY env vars
- **Context manager**: `with OKXClient() as client: ...`

**Initialization:**
```python
from data.manager import OKXClient

# Sandbox mode (default)
client = OKXClient(sandbox=True)

# Production mode
client = OKXClient(sandbox=False)

# With explicit credentials
client = OKXClient(
    sandbox=False,
    api_key="your_key",
    api_secret="your_secret",
    passphrase="your_passphrase",
)
```

### fetch_ohlcv() — Single Page (≤100 candles)

Fetches one page of recent data. Use for real-time updates.

```python
candles = client.fetch_ohlcv(
    symbol="BTC/USDT",
    timeframe="1h",
    since=None,          # Optional: start timestamp in ms
    limit=100,           # Max 100 per call (OKX limit)
)
```

**Returns:** `List[OHLCVCandle]` sorted by timestamp ascending

### fetch_ohlcv_history() — Full History with Pagination

Fetches all historical data in range with automatic pagination and since-probing.

```python
candles = client.fetch_ohlcv_history(
    symbol="BTC/USDT",
    timeframe="1h",
    since=1700000000000,  # Required: start timestamp in ms
    until=None,           # Optional: end timestamp in ms
    page_size=100,        # Candles per request (default 100)
    sleep_between_pages=0.1,  # Delay between pages (default 0.1s)
)
```

**Key features:**
- Loops through pages until all data collected
- **Since-probing**: When first page returns empty (pair not listed yet), binary-searches for valid start
- Deduplicates timestamps across pages
- Filters by `until` boundary if specified

### Since-Probing Mechanism (_probe_valid_since)

OKX returns empty when `since` precedes a pair's listing date. The probing mechanism:

1. First page request returns empty
2. Binary search between `since` and `until` (or current time)
3. Finds earliest valid `since` that returns data
4. Resume normal pagination from discovered start

This makes `--backfill` (unlimited) work reliably across all pairs.

### retry_with_backoff Decorator

```python
@retry_with_backoff(
    max_retries=3,      # Maximum retry attempts
    base_delay=1.0,     # Initial delay in seconds
    max_delay=60.0,     # Maximum delay cap
)
def fetch_ohlcv(...): ...
```

**Retry behavior by exception type:**

| Exception Type | Behavior |
|----------------|----------|
| Network/Timeout errors | Retry with exponential backoff |
| Rate limit exceeded | Retry with 2x longer backoff |
| Authentication error | Fail immediately (no retry) |
| Other exchange errors | Fail immediately |

### Supported Timeframes

| Timeframe | Unit | Milliseconds |
|-----------|------|--------------|
| `1m`, `5m`, `15m` | minutes | 60_000, 300_000, 900_000 |
| `1h`, `4h` | hours | 3_600_000, 14_400_000 |
| `1d`, `1w` | days/weeks | 86_400_000, 604_800_000 |

### Exception Hierarchy

```python
OKXAPIError(Exception)            # Base class
  ├── OKXAuthenticationError      # Invalid credentials → fail immediately
  ├── OKXRateLimitError           # Rate exceeded → retry with longer delay
  ├── OKXTimeoutError             # Request timeout → retry with backoff
  └── OKXNetworkError             # Connection lost → retry with backoff
```

---

## VALIDATION (validation.py)

### Constants

```python
VALIDATION_PASS = "PASS"   # No issues
VALIDATION_WARN = "WARN"   # Minor issues (gaps, anomalies)
VALIDATION_FAIL = "FAIL"   # Critical issues (negative volume, empty data)

DEFAULT_PRICE_ANOMALY_THRESHOLD = 0.20  # 20% price change
DEFAULT_GAP_THRESHOLD_MS = 1.1          # 10% tolerance on expected interval
```

### validate_candle() — Single Candle Sanity Check

```python
from data.validation import validate_candle

is_valid, reason = validate_candle(candle)
# Returns: (True, None) or (False, "error message")
```

**Checks performed:**
- `open > 0` and `close > 0` — positive prices
- `high >= low` — price range sanity
- `high >= open` and `high >= close` — high is highest
- `low <= open` and `low <= close` — low is lowest
- `volume >= 0` — non-negative volume

### validate_candles_batch() — Batch Validation

```python
from data.validation import validate_candles_batch

valid, rejected = validate_candles_batch(candles)
# valid: List[OHLCVCandle] — passed candles
# rejected: List[Tuple[OHLCVCandle, str]] — (candle, reason) pairs
```

### ValidationIssue Dataclass

```python
@dataclass
class ValidationIssue:
    issue_type: str       # "missing_timestamp", "price_anomaly", "volume_issue"
    severity: str         # "ERROR", "WARNING", "INFO"
    message: str          # Human-readable description
    timestamp: Optional[int] = None   # Affected timestamp
    details: Dict[str, Any] = {}       # Additional context
```

### ValidationReport Dataclass

```python
@dataclass
class ValidationReport:
    status: str               # "PASS", "WARN", or "FAIL"
    pair: str                 # Trading pair validated
    timeframe: str            # Timeframe validated
    total_rows: int           # Total data rows
    issues: List[ValidationIssue]  # All issues found
    missing_timestamps: int   # Count of missing timestamps
    price_anomalies: int      # Count of price anomalies
    volume_issues: int        # Count of volume issues
    start_timestamp: Optional[int]  # First timestamp
    end_timestamp: Optional[int]    # Last timestamp
    data_gaps_ms: List[int]   # Gap durations in milliseconds
    
    def to_dict(self) -> Dict[str, Any]: ...
```

### check_missing_timestamps() — Gap Detection

```python
missing_timestamps, gap_durations = check_missing_timestamps(
    df,                    # DataFrame with 'timestamp' column
    timeframe="1h",        # Expected interval
    tolerance=1.1,         # 10% tolerance (default)
)
```

**Returns:**
- `missing_timestamps`: List of specific missing timestamps
- `gap_durations`: List of gap durations in milliseconds

### check_price_anomalies() — Unrealistic Price Jumps

```python
anomalies = check_price_anomalies(
    df,
    threshold=0.20,  # 20% default
)
```

**Detects:**
- Open-to-close change exceeds threshold
- High-to-low range exceeds 2x threshold (extreme volatility)

**Returns:** List of anomaly dicts with timestamp, prices, and issue details

### check_volume_validation() — Volume Sanity

```python
issues = check_volume_validation(df)
```

**Checks:**
- Negative volume → ERROR
- Zero volume → WARNING
- NaN/Inf volume → ERROR

### validate_ohlcv_data() — Full DataFrame Validation

```python
from data.validation import validate_ohlcv_data

report = validate_ohlcv_data(
    df,                    # DataFrame with OHLCV columns
    pair="BTC/USDT",
    timeframe="1h",
    price_threshold=0.20,  # Optional override
)
print(report.status)  # "PASS" / "WARN" / "FAIL"
```

**Validation sequence:**
1. Check DataFrame not empty
2. Verify required columns present
3. Detect missing timestamps
4. Check price anomalies
5. Validate volume data
6. Build ValidationReport with all issues

### validate_stored_data() — Validate from Repository

```python
from data.validation import validate_stored_data

report = validate_stored_data(
    pair="BTC/USDT",
    timeframe="1h",
    price_threshold=0.20,
)
# Loads from SQLite, runs validation, returns dict
```

### auto_repair_data() — Fix Minor Issues

```python
from data.validation import auto_repair_data

repaired_df, repair_report = auto_repair_data(
    df,
    pair="BTC/USDT",
    timeframe="1h",
    fill_missing=True,     # Forward-fill gaps
    flag_anomalies=True,  # Add anomaly_flag column
)
```

**Repair actions:**
- Fills missing timestamps with placeholder rows
- Forward-fills OHLC prices from prior candle
- Sets missing volume to 0
- Adds `anomaly_flag` column (0=normal, 1=anomaly)

---

## REPOSITORY (repository/)

### DataRepository Abstract Interface (base.py)

```python
class DataRepository(ABC):
    # Core CRUD methods
    @abstractmethod
    def save_candles(candles, pair, timeframe) -> int
    @abstractmethod
    def load_candles(pair, timeframe, since, until, limit) -> List[OHLCVCandle]
    @abstractmethod
    def load_as_dataframe(pair, timeframe, since, until) -> pd.DataFrame
    @abstractmethod
    def get_latest_timestamp(pair, timeframe) -> Optional[int]
    @abstractmethod
    def get_earliest_timestamp(pair, timeframe) -> Optional[int]
    @abstractmethod
    def count(pair, timeframe) -> int
    @abstractmethod
    def exists(pair, timeframe) -> bool
    @abstractmethod
    def delete(pair, timeframe, since, until) -> int
    @abstractmethod
    def list_pairs_timeframes() -> List[tuple]
    
    # Convenience methods
    def get_stats(pair, timeframe) -> Dict[str, Any]
    def list_all() -> List[Dict[str, Any]]
    def close() -> None
```

### SQLiteRepository Implementation (sqlite.py)

```python
from data.repository import get_repository

repo = get_repository()  # Singleton SQLiteRepository instance
```

**SQLite optimizations:**
```sql
PRAGMA journal_mode=WAL;      -- Concurrent read/write
PRAGMA synchronous=NORMAL;    -- Balance safety/speed
PRAGMA cache_size=-64000;     -- 64MB cache
PRAGMA busy_timeout=5000;     -- 5s wait on lock
```

**Upsert semantics:**
- Composite primary key: `(pair, timeframe, timestamp)`
- `INSERT OR REPLACE` on conflict
- New candles inserted, existing candles updated

**Usage:**
```python
from data.repository import get_repository

repo = get_repository()

# Save candles (upsert)
repo.save_candles(candles, "BTC/USDT", "1h")

# Load as DataFrame (for Backtrader)
df = repo.load_as_dataframe("BTC/USDT", "1h")

# Load as candle objects
candles = repo.load_candles("BTC/USDT", "1h", limit=100)

# Time-range query
candles = repo.load_candles("BTC/USDT", "1h", 
    since=1700000000000, 
    until=1710000000000)

# Statistics
stats = repo.get_stats("BTC/USDT", "1h")
# Returns: {pair, timeframe, count, min_timestamp, max_timestamp}

# List all stored data
all_data = repo.list_all()

# Time boundaries
latest = repo.get_latest_timestamp("BTC/USDT", "1h")
earliest = repo.get_earliest_timestamp("BTC/USDT", "1h")

# Delete data
deleted = repo.delete("BTC/USDT", "1h", since=1700000000000)

# Cleanup
repo.close()
```

### Singleton Factory (__init__.py)

```python
from data.repository import get_repository, reset_repository

repo = get_repository()        # Returns singleton instance
reset_repository()             # Reset for testing (DO NOT use in production)
```

---

## DOWNLOADER (downloader.py)

### DownloadResult Dataclass

```python
@dataclass(frozen=True)
class DownloadResult:
    pair: str              # Trading pair
    timeframe: str         # Candle interval
    total_fetched: int     # Total candles from API
    valid_count: int       # Passed validation
    rejected_count: int    # Failed validation
    start_time: str        # First candle time (human-readable)
    end_time: str          # Last candle time (human-readable)
    mode: str              # "incremental" | "full" | "backfill"
```

### download() Function

```python
from data.downloader import download

result = download(
    pair="BTC/USDT",
    timeframe="1h",
    days=365,              # Number of days (default 365)
    since=None,            # Override: "YYYY-MM-DD" format
    incremental=True,      # Only fetch new data (default)
    backfill=None,         # None, -1 (unlimited), or N days
    sandbox=True,          # Use sandbox environment
)
```

### Download Modes

| Mode | Flag | Behavior |
|------|------|----------|
| **Incremental** | (default) | Fetch data after `latest_timestamp` in DB |
| **Full** | `--full` | Re-download from `--since` or `now - --days` |
| **Backfill N** | `--backfill N` | Fetch N days before `earliest_timestamp` |
| **Backfill unlimited** | `--backfill` | Fetch from beginning of available data |

**Key behaviors:**
- `--backfill` requires existing data in DB (errors if none found)
- `--backfill` without argument auto-probes for earliest valid `since`
- `--days` default is 365 regardless of timeframe
- `--since YYYY-MM-DD` overrides `--days`
- Three modes are mutually exclusive

---

## API KEY VERIFICATION (verify_apikey.py)

### 3-Step Verification Process

```bash
python -m data.verify_apikey            # Test production keys
python -m data.verify_apikey --sandbox  # Test sandbox keys
```

**Step 1: Environment Check (`check_env`)**
- Verify `.env` file exists
- Check required keys non-empty: `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_PASSPHRASE`
- Sandbox mode: checks `OKX_SANDBOX_*` with fallback to production keys

**Step 2: Public Connectivity (`check_public_connectivity`)**
- Fetch OKX server time without authentication
- Tests network + OKX status
- Detects proxy from environment

**Step 3: Private Access (`check_private_access`)**
- Fetch account balance with credentials
- Verifies API key/secret/passphrase are valid
- Shows non-zero balances

---

## DATABASE SCHEMA

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

CREATE INDEX idx_candles_pair_tf ON candles(pair, timeframe);
```

**Key design:**
- Composite primary key → natural deduplication
- NUMERIC(20, 8) → preserves Decimal precision (8 decimal places)
- iso_time column → human-readable UTC timestamp
- WAL mode → concurrent read/write

---

## PUBLIC API (data/__init__.py)

```python
from data import (
    OHLCVCandle,
    get_repository,
    reset_repository,
    validate_candle,
    validate_candles_batch,
    validate_stored_data,
    validate_ohlcv_data,
)
```

---

## CLI COMMANDS

### Download Data

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

### Verify API Key

```bash
python -m data.verify_apikey --sandbox  # Test sandbox keys
python -m data.verify_apikey             # Test production keys
```

---

## PROGRAMMATIC USAGE

```python
# Fetch data
from data.manager import OKXClient
client = OKXClient(sandbox=True)
candles = client.fetch_ohlcv("BTC/USDT", "1h", limit=100)
candles = client.fetch_ohlcv_history("BTC/USDT", "1h", since=1700000000000)
client.close()

# Validate data
from data.validation import validate_candle, validate_candles_batch, validate_ohlcv_data
is_valid, reason = validate_candle(candle)
valid, rejected = validate_candles_batch(candles)
report = validate_ohlcv_data(df, "BTC/USDT", "1h")

# Save/load from SQLite
from data.repository import get_repository
repo = get_repository()
repo.save_candles(valid, "BTC/USDT", "1h")
df = repo.load_as_dataframe("BTC/USDT", "1h")
stats = repo.get_stats("BTC/USDT", "1h")

# Download via orchestrator
from data.downloader import download
result = download(pair="BTC/USDT", timeframe="1h", days=365, sandbox=True)
print(result)  # DownloadResult(...)
```

---

## ANTI-PATTERNS

**FORBIDDEN:**
- Using `float` for prices/volumes (precision loss, MUST use `Decimal`)
- Hardcoding API credentials (use `.env` + python-dotenv)
- Calling `reset_repository()` in production code (tests only)
- Using `xxx_price` field names (e.g. `close_price`) — use `open/high/low/close`
- Using `OrderBook`/`Ticker` from `data.models` (not defined, use `Optional[Dict[str, Any]]`)

**WARNINGS:**
- `fetch_ohlcv()` returns ms timestamps (not seconds)
- OKX `fetch_ohlcv` max 100 candles per call — use `fetch_ohlcv_history()` for bulk
- OKX returns **empty** when `since` precedes listing date — probing handles this
- Sandbox has limited historical data
- Production credentials must be in `.env` before `--no-sandbox`

---

## NOTES

- **Security:** API keys in `.env` (never committed). See `.env.example` template
- **Data Storage:** SQLite at `data/cryptoquant.db` (WAL mode, single `candles` table)
- **Exchange:** OKX only (ccxt allows others but not implemented)
- **Proxy:** WSL/corporate environments need `HTTPS_PROXY=http://host:port`
- **Mode:** Sandbox default (use `--no-sandbox` for production)
- **Since-probing:** Handles OKX's empty response for pre-listing dates
- **Dedup:** Composite PK + upsert = true deduplication (no duplicate timestamps)