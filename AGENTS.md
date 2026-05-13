# CryptoQuant Knowledge Base

**Project:** Crypto Quant Trading Platform  
**Stack:** Python 3.10+, ccxt, backtrader, SQLAlchemy, structlog, pydantic, pandas  
**Purpose:** Quantitative cryptocurrency trading with backtesting and live execution  
**Status:** Data module complete; backtest engine needs repair (uses old `data.storage` import)

## OVERVIEW

A modular Python platform for quantitative crypto trading on OKX exchange. The data layer is fully operational (OKX API → SQLite with validation). Backtest engine and live trading modules exist but have integration issues — the backtest engine still imports from the deprecated `data.storage` module instead of the new `data.repository`.

## STRUCTURE

```
CryptoQuant/
├── data/                # ✅ Data management (fully operational)
│   ├── models.py        # OHLCVCandle dataclass (frozen, Decimal precision)
│   ├── manager.py       # OKXClient: ccxt + retry + proxy + pagination + since-probing
│   ├── downloader.py    # Historical download CLI (incremental/full/backfill)
│   ├── validation.py    # Data quality checks + auto-repair
│   ├── verify_apikey.py # 3-step API key verification
│   └── repository/      # SQLite data access layer (upsert, WAL mode)
│       ├── base.py      # DataRepository abstract interface
│       └── sqlite.py    # SQLite implementation
├── backtest/            # ⚠️ Needs repair
│   ├── engine.py        # Backtrader integration (BROKEN: imports data.storage)
│   └── metrics.py       # Performance metrics (Sharpe, drawdown)
├── strategy/            # Strategy framework
│   ├── base.py          # StrategyBase ABC, Signal, StrategyContext
│   ├── cta/
│   │   └── trend_following.py  # SMA crossover
│   └── stat_arb/
│       └── pair_trading.py     # Pair trading
├── live/                # Live trading
│   ├── trading.py       # Live trading engine
│   ├── paper_trading.py # Paper trading simulation
│   ├── order_manager.py # Order lifecycle management
│   └── kill_switch.py   # Emergency stop
├── risk/                # Risk management
│   ├── position_sizing.py  # Position size calculations
│   └── stop_loss.py        # Stop-loss + drawdown circuit breaker
├── config/              # Configuration
│   └── config.yaml      # Trading params, risk limits, DB settings
├── logs/                # Logging and audit
│   ├── audit.py         # Risk event audit trail
│   └── logger.py        # structlog + file rotation
├── scripts/             # Utility scripts (legacy, not part of core modules)
│   ├── db_manager.py         # Database status/validate/reset
│   ├── batch_fetch.py        # Batch download
│   ├── download_all_data.py  # Full download script
│   ├── enhance_data.py       # Data enhancement
│   ├── migrate_*.py          # Migration scripts
│   └── test_*.py             # Connection test scripts
├── tests/               # Pytest test suite
├── AGENTS.md            # This file
├── TODO.md              # Project progress tracker
└── requirements.txt     # Dependencies
```

## WHERE TO LOOK

**Data module (operational):**
- `data/models.py` — OHLCVCandle dataclass (frozen, Decimal precision)
- `data/manager.py` — OKXClient with retry, proxy, pagination, since-probing
- `data/downloader.py` — CLI download orchestrator (incremental/full/backfill)
- `data/verify_apikey.py` — `python -m data.verify_apikey`
- `data/repository/sqlite.py` — SQLiteRepository (upsert, WAL mode)
- `data/validation.py` — Data quality validation + auto-repair

**Backtest (needs repair):**
- `backtest/engine.py` — Backtrader integration (currently broken, uses old `data.storage`)
- `backtest/metrics.py` — Performance metrics

**Strategy:**
- `strategy/base.py` — StrategyBase ABC, Signal, SignalType, StrategyContext
- `strategy/cta/trend_following.py` — SMA crossover CTA strategy
- `strategy/stat_arb/pair_trading.py` — Pair trading strategy

**Live trading:**
- `live/trading.py` — Live trading engine
- `live/paper_trading.py` — Paper trading simulation
- `live/order_manager.py` — Order lifecycle management
- `live/kill_switch.py` — Emergency stop

**Risk:**
- `risk/position_sizing.py` — Fixed fractional, Kelly, volatility-based
- `risk/stop_loss.py` — Trailing stops, time stops, drawdown monitor

**Other:**
- `config/config.yaml` — Trading params, risk limits, DB settings
- `logs/audit.py` — Risk event audit trail
- `scripts/` — Legacy utility scripts (db_manager, batch_fetch, etc.)

## CODE MAP

**Data module:**
- `OKXClient` — `data/manager.py` — Exchange API client + pagination + since-probing
- `OHLCVCandle` — `data/models.py` — Frozen dataclass, Decimal precision
- `SQLiteRepository` — `data/repository/sqlite.py` — Upsert by composite PK, WAL mode
- `DataRepository` — `data/repository/base.py` — Abstract interface
- `DownloadResult` — `data/downloader.py` — Download operation result
- `validate_ohlcv_data()` — `data/validation.py` — DataFrame quality checks
- `validate_candle()` — `data/validation.py` — Single candle sanity check
- `auto_repair_data()` — `data/validation.py` — Forward-fill gaps, flag anomalies

**Strategy:**
- `StrategyBase` — `strategy/base.py` — ABC for all strategies
- `Signal` — `strategy/base.py` — Trading signal dataclass
- `SignalType` — `strategy/base.py` — LONG, SHORT, CLOSE_LONG, CLOSE_SHORT, HOLD
- `StrategyContext` — `strategy/base.py` — Market data + positions
- `TrendFollowingStrategy` — `strategy/cta/trend_following.py` — SMA crossover

**Risk:**
- `PositionSizer` — `risk/position_sizing.py` — Position size calculations
- `StopLossManager` — `risk/stop_loss.py` — Stop-loss + trailing + circuit breaker

**Exceptions:**
- `OKXAPIError` — `data/manager.py` — Base exception
- `OKXAuthenticationError` — Bad credentials (fail immediately)
- `OKXRateLimitError` — Rate limit exceeded (retry with backoff)
- `OKXTimeoutError` — API timeout (retry with backoff)
- `OKXNetworkError` — Connection lost (retry with backoff)

## CONVENTIONS

**Python Style:**
- Use `Decimal` for all price/quantity calculations (never float)
- `frozen=True` dataclasses for immutable data (candles, signals)
- Type hints required (mypy enforced)
- structlog for structured logging

**Import Pattern:**
```python
from decimal import Decimal  # REQUIRED for money math
from data.models import OHLCVCandle
from data.repository import get_repository
from data.manager import OKXClient
from data.validation import validate_candle, validate_ohlcv_data
from strategy.base import StrategyBase, Signal, SignalType
```

**Data Access Pattern (new — use this):**
```python
from data.repository import get_repository

repo = get_repository()
repo.save_candles(candles, "BTC/USDT", "1h")
df = repo.load_as_dataframe("BTC/USDT", "1h")
candles = repo.load_candles("BTC/USDT", "1h", limit=100)
stats = repo.get_stats("BTC/USDT", "1h")
```

**Error Handling:**
- Custom exceptions in `data/manager.py`: `OKXAPIError` hierarchy
- Retry with exponential backoff on API failures
- Proxy auto-detected from `HTTPS_PROXY`/`HTTP_PROXY` env vars

## ANTI-PATTERNS

**FORBIDDEN:**
- Hardcoding API credentials (use `.env` + python-dotenv)
- Using `float` for prices/quantities (precision loss)
- Committing `.env` files (gitignored by default)
- Skipping dry-run before live trading
- Using old `data.storage` module (deprecated, use `data.repository`)
- Calling `reset_repository()` in production code (tests only)

**WARNINGS:**
- Backtest engine is currently broken — imports from `data.storage` which no longer exists
- `strategy/base.py` imports `OrderBook, Ticker` from `data.models` — may not be defined yet
- OKX `fetch_ohlcv` max 100 candles per call — use `fetch_ohlcv_history()` for bulk
- OKX returns empty when `since` is before the pair's listing date — auto-probing handles this
- Sandbox default (use `--no-sandbox` for production)
- Live trading requires manual confirmation

## COMMANDS

```bash
# Setup
pip install -r requirements.txt
cp .env.example .env  # Add OKX API keys

# Download historical data (✅ working)
python -m data.downloader --pair BTC/USDT --timeframe 1h --days 365
python -m data.downloader --pair ETH/USDT --timeframe 4h --since 2024-01-01
python -m data.downloader --pair BTC/USDT --timeframe 1h --full --sandbox
python -m data.downloader --pair BTC/USDT --timeframe 1d --backfill

# Verify API key (✅ working)
python -m data.verify_apikey --sandbox

# Database management (via scripts)
python scripts/db_manager.py status
python scripts/db_manager.py validate
python scripts/db_manager.py reset

# Run backtest (⚠️ broken — engine imports data.storage)
# python -m cli.main backtest --strategy cta --pair BTC/USDT --timeframe 1h

# Run tests
pytest tests/ -v

# Format + lint
black . && ruff check . --fix && mypy . --ignore-missing-imports
```

## NOTES

- **Security:** API keys in `.env` (never committed). See `.env.example` template
- **Data Storage:** Historical OHLCV in `data/cryptoquant.db` (SQLite, WAL mode, single `candles` table)
- **Exchange:** OKX only (ccxt integration allows others)
- **Proxy:** WSL environment requires `HTTPS_PROXY=http://192.168.10.128:10808`
- **Mode:** Sandbox default (use `--no-sandbox` for production)
- **Since-probing:** `fetch_ohlcv_history()` auto-detects earliest valid `since` via binary search
- **Kill Switch:** Emergency stop closes all positions via `live/kill_switch.py`
- **Scripts vs Modules:** Utility scripts live in `scripts/`; core module tools (downloader, verify_apikey) live alongside their module in `data/`

## KNOWN ISSUES

1. **Backtest engine broken** — `backtest/engine.py` imports from `data.storage` (deleted). Needs update to use `data.repository.get_repository()` + `load_as_dataframe()`
2. **Strategy model imports** — `strategy/base.py` imports `OrderBook, Ticker` from `data.models` — these models may not exist yet
3. **No CLI entry point** — The `cli/` directory referenced in earlier design does not exist. Commands run via `python -m data.downloader` etc.

## MODULE GUIDES

- See `data/AGENTS.md` for data management (detailed and up-to-date)
- See `backtest/AGENTS.md` for backtesting (needs update after engine fix)
- See `live/AGENTS.md` for trading execution
- See `strategy/AGENTS.md` for strategy development
- See `risk/AGENTS.md` for risk controls
