# API Module Knowledge Base

**Purpose:** FastAPI backend for CryptoQuant web UI

## OVERVIEW

REST API exposing data, backtest, and download endpoints for frontend consumption.

## STRUCTURE

```
api/
├── __init__.py          # Exports app
├── main.py              # All endpoints + Pydantic models (388 lines)
└── routers/
    └── __init__.py      # Placeholder for future split
```

## WHERE TO LOOK

**Endpoints:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | Health check |
| `/api/pairs` | GET | List pairs with data |
| `/api/stats/{pair}/{timeframe}` | GET | Data statistics |
| `/api/candles/{pair}/{timeframe}` | GET | OHLCV candles (since, until, limit, order params) |
| `/api/strategies` | GET | List available strategies |
| `/api/backtest` | POST | Run backtest |
| `/api/download` | POST | Start background download |
| `/api/download/{task_id}` | GET | Check download status |

**Pydantic Models:**
- `CandleResponse` — OHLCV candle with iso_time
- `StatsResponse` — Data statistics (count, earliest, latest)
- `BacktestRequest` — Backtest params (strategy, pair, timeframe, days, dates, cash, commission, slippage)
- `BacktestResponse` — Backtest result (trades, equity curve, metrics)
- `DownloadRequest` — Download params (pair, timeframe, days, sandbox)
- `DownloadStatus` — Task status (task_id, status, message, progress)
- `StrategyInfo` — Strategy metadata (name, class_name, params)

**Integration Points:**
- `data.repository.get_repository()` — SQLite data access
- `backtest.engine.BacktestEngine` — Backtest execution
- `data.manager.OKXClient` — Exchange API (in background tasks)

**Key Functions:**
- `normalize_pair()` — Convert URL format (BTC-USDT) to DB format (BTC/USDT)
- `run_download_task()` — Background async download worker

## CONVENTIONS

**Pair Format:**
- URL: `BTC-USDT` (hyphen for URL safety)
- Database: `BTC/USDT` (slash for ccxt compatibility)
- Use `normalize_pair()` in endpoints

**Background Tasks:**
- `task_status` dict tracks async downloads
- `asyncio.to_thread()` wraps sync OKXClient calls
- Status: pending → running → completed/failed

**Error Handling:**
- `HTTPException(404, ...)` for missing data
- `HTTPException(400, ...)` for invalid params
- `HTTPException(500, ...)` for unexpected errors
- Log errors with structlog before raising

**CORS:**
- Origins: `localhost:5173`, `localhost:3000`
- Credentials enabled, all methods/headers allowed

## ANTI-PATTERNS

**FORBIDDEN:**
- Direct instantiation in endpoints (use dependency injection pattern when scaling)
- Blocking calls in async endpoints (use `asyncio.to_thread()`)
- Hardcoding CORS origins (should be config-driven)
- Missing error logging before HTTPException
- Using float for prices in Pydantic models (acceptable for API serialization, but Decimal in core)

**WARNINGS:**
- All endpoints in single file (split into routers when adding more)
- No authentication/authorization (add before production)
- No rate limiting (add for public deployment)
- Global `task_status` dict (use Redis for multi-worker deployment)