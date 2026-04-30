# CryptoQuant Data Knowledge Base

**Module:** Data management layer  
**Purpose:** Exchange API access, data models, validation, storage

## OVERVIEW

OKX exchange integration via ccxt with rate limiting. Defines core data models (OHLCV, OrderBook, Ticker) and Parquet-based storage.

## STRUCTURE

```
data/
├── __init__.py       # Module exports
├── manager.py        # OKX API client (494 lines)
├── models.py         # Dataclasses (OHLCV, OrderBook, Ticker)
├── storage.py        # Parquet persistence (516 lines)
└── validation.py     # Data validation (650 lines)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Fetch OHLCV | `manager.py:OKXDataManager.fetch_ohlcv()` | Returns List[OHLCVCandle] |
| Rate limiting | `manager.py:RateLimiter` | Token bucket, 20 req/2s |
| Data models | `models.py` | All frozen dataclasses |
| Load/save data | `storage.py` | Parquet format |
| Validate data | `validation.py` | Schema validation |
| API errors | `manager.py:OKXAPIError` hierarchy | Retry decorators |

## CONVENTIONS

**Data Models:**
- All models use `frozen=True` dataclasses
- Timestamps in **milliseconds** (Unix epoch)
- Prices/quantities use `Decimal` type

**API Calls:**
- Rate limited via `@retry_with_backoff` decorator
- Max 20 requests per 2 seconds
- Retry on rate limit, timeout, network errors

## ANTI-PATTERNS

**FORBIDDEN:**
- Using float for prices (precision loss)
- Hardcoding API credentials (use .env)
- Ignoring rate limits (will get banned)

**WARNINGS:**
- `fetch_ohlcv()` returns ms timestamps
- Sandbox mode by default (`sandbox: true`)
- Always check for `OKXRateLimitError`

## UNIQUE STYLES

**Rate Limiting:**
```python
@retry_with_backoff(max_retries=3)
def fetch_ohlcv(self, pair: str, ...) -> List[OHLCVCandle]:
    self.rate_limiter.acquire()  # Wait if needed
    # ... API call
```

**Model Usage:**
```python
candle = OHLCVCandle(
    timestamp=1234567890000,  # ms
    open_price=Decimal('50000.00'),
    # ... all Decimal
)
```

## EXCEPTIONS

| Exception | When | Handling |
|-----------|------|----------|
| `OKXRateLimitError` | >20 req/2s | Retry with backoff |
| `OKXTimeoutError` | API timeout | Retry with backoff |
| `OKXNetworkError` | Connection lost | Retry with backoff |
| `OKXAuthenticationError` | Bad credentials | Fail immediately |

## COMMANDS

```python
from data.manager import OKXDataManager
from data.models import OHLCVCandle
from data.storage import load_historical_data, save_historical_data

# Fetch live data
manager = OKXDataManager(sandbox=True)
candles = manager.fetch_ohlcv("BTC/USDT", "1h", limit=100)

# Load historical
from data.storage import load_historical_data
df = load_historical_data("BTC/USDT", "1h")
```
