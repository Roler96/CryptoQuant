# CryptoQuant Knowledge Base

**Project:** Crypto Quant Trading Platform  
**Stack:** Python 3.12+, ccxt, backtrader, structlog, pydantic, pandas  
**Purpose:** Quantitative cryptocurrency trading with backtesting and live execution  
**Status:** Data + Backtest + Strategy modules operational; live/risk modules not yet integrated

## OVERVIEW

A modular Python platform for quantitative crypto trading on OKX exchange. Data layer, backtest engine, and strategy framework are all operational and integrated via `data.repository`. The full pipeline (download → SQLite → backtest) works end-to-end.

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
├── backtest/            # ✅ Backtesting (operational)
│   ├── engine.py        # Backtrader integration (BacktestEngine, PandasDataFeed)
│   ├── metrics.py       # Performance metrics (Sharpe, drawdown, win rate, etc.)
│   └── run.py           # CLI backtest runner
├── strategy/            # ✅ Strategy framework (operational)
│   ├── base.py          # StrategyBase ABC, Signal, StrategyContext
│   ├── cta/
│   │   └── trend_following.py  # SMA crossover + MA/RSI/ATR/ADX
│   ├── stat_arb/
│   │   └── pair_trading.py     # Pair trading
│   ├── quant/           # ✅ Quant strategies
│   │   ├── basis_strategy.py   # Basis mean reversion
│   │   └── funding_rate_arb.py # Cash-and-carry arbitrage
│   └── regime/          # ✅ Market regime detection
│       └── detector.py  # STRONG_TREND, RANGING, HIGH_VOLATILITY via ADX/CHOP/ATR
├── live/                # ⚠️ Not yet integrated with data.repository
│   ├── trading.py       # Live trading engine
│   ├── paper_trading.py # Paper trading simulation
│   ├── order_manager.py # Order lifecycle management
│   └── kill_switch.py   # Emergency stop
├── risk/                # ⚠️ Not yet integrated with data.repository
│   ├── position_sizing.py  # Position size calculations
│   └── stop_loss.py        # Stop-loss + drawdown circuit breaker
├── api/                 # ✅ FastAPI backend (operational)
│   ├── main.py          # REST endpoints (data, backtest, download)
│   └── routers/         # Placeholder for future split
├── frontend/            # ✅ React + TypeScript UI (operational)
│   └── src/
│       ├── App.tsx      # Main layout + state management
│       ├── api.ts       # Axios client + TypeScript interfaces
│       └── components/  # Chart, DataPanel, StrategyPanel, ResultsPanel, DownloadPanel
├── config/              # Configuration
│   └── config.yaml      # Trading params, risk limits, DB settings
├── logs/                # Logging and audit
│   ├── audit.py         # Risk event audit trail
│   └── logger.py        # structlog + file rotation
├── scripts/             # Utility scripts (legacy, not part of core modules)
├── tests/               # Pytest test suite
├── research/            # Strategy research documents
├── docs/                # Documentation + implementation plans
├── notebooks/           # Research notebooks (markdown)
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

**Backtest (operational):**
- `backtest/engine.py` — BacktestEngine + PandasDataFeed + BacktraderStrategyAdapter
- `backtest/metrics.py` — Performance metrics (Sharpe, drawdown, win rate, Calmar, etc.)

**Strategy (operational):**
- `strategy/base.py` — StrategyBase ABC, Signal, SignalType, StrategyContext
- `strategy/cta/trend_following.py` — SMA crossover CTA strategy
- `strategy/stat_arb/pair_trading.py` — Pair trading strategy

**Live trading (not yet integrated):**
- `live/trading.py` — Live trading engine
- `live/paper_trading.py` — Paper trading simulation
- `live/order_manager.py` — Order lifecycle management
- `live/kill_switch.py` — Emergency stop

**Risk (not yet integrated):**
- `risk/position_sizing.py` — Fixed fractional, Kelly, volatility-based
- `risk/stop_loss.py` — Trailing stops, time stops, drawdown monitor

**API (operational):**
- `api/main.py` — FastAPI backend with REST endpoints
- See `api/AGENTS.md` for endpoint details

**Frontend (operational):**
- `frontend/src/App.tsx` — Main React component
- `frontend/src/api.ts` — Axios client + TypeScript types
- See `frontend/AGENTS.md` for component details

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

**Backtest:**
- `BacktestEngine` — `backtest/engine.py` — High-level backtest orchestration
- `BacktestConfig` — `backtest/engine.py` — Cash, commission, slippage config
- `BacktestResult` — `backtest/engine.py` — Result dataclass (trades, equity, metrics)
- `PandasDataFeed` — `backtest/engine.py` — DataFrame → Backtrader feed (use `from_dataframe()`)
- `BacktraderStrategyAdapter` — `backtest/engine.py` — Bridges StrategyBase → Backtrader

**Strategy:**
- `StrategyBase` — `strategy/base.py` — ABC for all strategies
- `Signal` — `strategy/base.py` — Trading signal dataclass
- `SignalType` — `strategy/base.py` — LONG, SHORT, CLOSE_LONG, CLOSE_SHORT, HOLD
- `StrategyContext` — `strategy/base.py` — Market data + positions
- `TrendFollowingStrategy` — `strategy/cta/trend_following.py` — SMA crossover
- `MarketRegime` — `strategy/regime/detector.py` — STRONG_TREND, RANGING, HIGH_VOLATILITY

**Risk:**
- `PositionSizer` — `risk/position_sizing.py` — Position size calculations
- `StopLossManager` — `risk/stop_loss.py` — Stop-loss + trailing + circuit breaker

**API:**
- `app` — `api/main.py` — FastAPI application
- Endpoints: `/api/health`, `/api/pairs`, `/api/stats`, `/api/candles`, `/api/strategies`, `/api/backtest`, `/api/download`

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
from backtest.engine import BacktestEngine, BacktestConfig
```

**Data Access Pattern:**
```python
from data.repository import get_repository

repo = get_repository()
repo.save_candles(candles, "BTC/USDT", "1h")
df = repo.load_as_dataframe("BTC/USDT", "1h")
candles = repo.load_candles("BTC/USDT", "1h", limit=100)
stats = repo.get_stats("BTC/USDT", "1h")
```

**Backtest Pattern:**
```python
from backtest.engine import BacktestEngine, BacktestConfig

engine = BacktestEngine(BacktestConfig(initial_cash=10000, plot_results=False))
strategy = engine.load_strategy("cta")
result = engine.run_backtest(strategy, "BTC/USDT", "1h", days=90)
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
- Using old `data.storage` module (deleted, use `data.repository`)
- Calling `reset_repository()` in production code (tests only)
- Using `xxx_price` field names (e.g. `close_price`) — use `open/high/low/close`
- Using `OrderBook`/`Ticker` from `data.models` (not defined, use `Optional[Dict[str, Any]]`)
- Constructing `PandasDataFeed(dataframe=...)` directly — use `PandasDataFeed.from_dataframe()`

**WARNINGS:**
- OKX `fetch_ohlcv` max 100 candles per call — use `fetch_ohlcv_history()` for bulk
- OKX returns empty when `since` is before the pair's listing date — auto-probing handles this
- Sandbox default (use `--no-sandbox` for production)
- Live trading requires manual confirmation
- Backtrader `PandasData` subclass `__init__` cannot accept `dataname` as kwarg — use `from_dataframe()` class method

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

# Run backtest (✅ working — via Python API)
python -c "
from backtest.engine import BacktestEngine, BacktestConfig
engine = BacktestEngine(BacktestConfig(initial_cash=10000, plot_results=False))
strategy = engine.load_strategy('cta')
result = engine.run_backtest(strategy, 'BTC/USDT', '1h', days=90)
print(f'Return: {result.total_return:.2%}, Trades: {len(result.trades)}')
"

# Start API server (✅ working)
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# Start frontend (requires npm install first)
cd frontend && npm run dev

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
- **OHLCVCandle fields:** `pair, timeframe, timestamp, open, high, low, close, volume` (all Decimal except pair/timeframe)
- **DataFrame columns:** `timestamp, open, high, low, close, volume` (from `load_as_dataframe()`)
- **Frontend:** React 19 + TypeScript + Vite at `frontend/`, connects to API at `localhost:8000`
- **API:** FastAPI backend, CORS configured for `localhost:5173` and `localhost:3000`

## KNOWN ISSUES

1. **No pyproject.toml** — Using legacy `requirements.txt` instead of modern Python packaging (PEP 621)
2. **No unified CLI** — Commands run via `python -m data.downloader` or inline Python. A unified CLI would improve UX.
3. **No CI/CD pipeline** — No `.github/workflows/` directory; manual testing and linting only
4. **No pytest configuration** — Missing `conftest.py` for shared fixtures
5. **No pre-commit hooks** — `pre-commit` in requirements but not configured (`.pre-commit-config.yaml` missing)
6. **Live/Risk modules not integrated** — `live/` and `risk/` modules still reference old patterns (not tested against current data module)
7. **Backtest trade recording** — Only closed trades are recorded; open positions at backtest end are not captured
8. **API authentication** — No authentication/authorization on API endpoints (add before production)
9. **Config directory missing** — `config/config.yaml` mentioned but directory structure unclear

## MODULE GUIDES

- See `data/AGENTS.md` for data management (detailed and up-to-date)
- See `backtest/AGENTS.md` for backtesting
- See `strategy/AGENTS.md` for strategy development
- See `live/AGENTS.md` for trading execution
- See `risk/AGENTS.md` for risk controls
- See `api/AGENTS.md` for FastAPI backend
- See `frontend/AGENTS.md` for React UI
