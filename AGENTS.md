# CryptoQuant — Project Knowledge Base

**Generated:** 2026-06-30
**Branch:** dev

## OVERVIEW

Cryptocurrency quantitative trading system. Python 3.11+, ccxt for exchange connectivity, pandas/numpy for data, SQLite for persistence, loguru for logging. Supports backtesting and live trading with risk management. Production-ready with Docker, systemd, CI, and comprehensive monitoring.

## STRUCTURE

```
CryptoQuant/
├── cryptoquant/          # Core library (7 submodules)
│   ├── engine/           # Backtest + live execution engines
│   │   ├── backtest.py   # Vectorized backtest, compound returns
│   │   ├── live.py       # Tick-based real-time loop with reconciliation
│   │   ├── state.py      # StateManager — JSON + SHA-256 persistence
│   │   ├── types.py      # Trade, PerformanceMetrics, BacktestResult
│   │   ├── exit_logic.py # Exit checks: SL/TP/time/signal_reverse
│   │   ├── slippage.py   # Slippage models
│   │   ├── latency.py    # Latency simulation
│   │   └── commission.py # Commission calculation
│   ├── strategy/         # Strategy ABC + technical indicators
│   ├── execution/        # ccxt broker wrapper + order types
│   ├── data/             # OHLCV pipeline: SQLite → ccxt fetch + validation
│   ├── risk/             # Pre-trade checks + position sizing
│   ├── monitor/          # Logging, journaling, PnL reporting, log sanitization
│   ├── analysis/         # Post-trade analysis and trade analytics
│   └── config.py         # pydantic-settings: AppConfig, RiskConfig, TradingConfig
├── strategies/           # Concrete strategy implementations
├── research/             # Standalone backtest scripts (one per experiment)
├── tests/                # pytest suite (mirrors cryptoquant/ structure)
├── docs/                 # Operations manual + research literature
├── deploy/               # Deployment: systemd service + install script
├── data/                 # SQLite DB (gitignored)
├── logs/                 # Application logs (gitignored)
├── state/                # Engine state snapshots (gitignored)
├── config.yaml           # Runtime config (exchange, data, trading, risk, logging, alert)
├── live_runner.py        # Production entry point — full component wiring
├── demo_backtest.py      # Backtest demo entry point
├── Dockerfile            # Docker image (Python 3.11-slim + uv)
├── .dockerignore         # Docker build exclusions
├── .env.example          # API key template (never commit .env)
└── pyproject.toml        # uv-managed, ruff + pytest + pyright + coverage
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Run live trading | `live_runner.py` | Production entry point: config → broker → risk → engine |
| Run backtest | `demo_backtest.py` | Fetches OKX data → SQLite → BacktestEngine |
| Add new strategy | `strategies/` | Subclass `Strategy`, implement `generate_signal()` |
| Modify backtest logic | `cryptoquant/engine/backtest.py` | Vectorized backtest engine |
| Modify live trading | `cryptoquant/engine/live.py` | Tick loop with reconciliation, heartbeat, journaling |
| Change data pipeline | `cryptoquant/data/backtest_feed.py`, `cryptoquant/data/live_feed.py` | Backtest and live data feeds |
| Adjust risk rules | `cryptoquant/risk/manager.py` | Multi-tier drawdown, emergency stop, daily limits, adaptive risk |
| Add technical indicator | `cryptoquant/strategy/signals.py` | Pure numpy/pandas, no external deps |
| Run trade analysis | `cryptoquant/analysis/trade_analyzer.py` | `TradeAnalyzer` — metrics, curves, regime report |
| Run experiments | `research/` | Each file is standalone, not imported by core |
| Config reference | `config.yaml` + `cryptoquant/config.py` | pydantic-settings with RiskConfig, TradingConfig, etc. |
| Operations manual | `docs/operations.md` | Startup, monitoring, crash recovery, pre-live checklist |
| Deploy to server | `deploy/install.sh` | systemd service + directory setup |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `Strategy` | ABC | `cryptoquant/strategy/base.py` | Base class: `generate_signal(df) -> Series[1,0,-1]` |
| `BacktestEngine` | class | `cryptoquant/engine/backtest.py` | Vectorized backtest, compound returns |
| `LiveEngine` | class | `cryptoquant/engine/live.py` | Tick loop with reconciliation, heartbeat, journaling, daily reset |
| `BacktestDataFeed` | class | `cryptoquant/data/backtest_feed.py` | Historical OHLCV feed for backtests |
| `LiveDataFeed` | class | `cryptoquant/data/live_feed.py` | Real-time OHLCV feed for live trading |
| `OHLCVStore` | class | `cryptoquant/data/store.py` | SQLite WAL storage, one table per (exchange, symbol, tf) |
| `OHLCVFetcher` | class | `cryptoquant/data/fetcher.py` | ccxt wrapper, validates OHLCV integrity |
| `Broker` | class | `cryptoquant/execution/broker.py` | ccxt wrapper, retry on all methods, proxy support |
| `PaperBroker` | class | `cryptoquant/execution/paper_broker.py` | Simulated broker for paper trading |
| `RiskManager` | class | `cryptoquant/risk/manager.py` | Daily limits, 3-tier drawdown, emergency stop, daily reset, adaptive risk |
| `PositionSizer` | ABC | `cryptoquant/risk/sizer.py` | Fixed / Kelly / ATR sizing methods |
| `TradeAnalyzer` | class | `cryptoquant/analysis/trade_analyzer.py` | Post-trade metrics, equity curves, regime analysis |
| `AppConfig` | class | `cryptoquant/config.py` | Root config: exchange, data, trading, risk, paper, logging, alert |
| `RiskConfig` | class | `cryptoquant/config.py` | Risk parameters: limits, tiers, drawdown (YAML-configured) |
| `TradingConfig` | class | `cryptoquant/config.py` | Trading params: order limits, SL/TP, hold time, cooldown |
| `StateManager` | class | `cryptoquant/engine/state.py` | JSON + SHA-256 checksum, backup rotation (5 versions) |
| `TradeJournal` | class | `cryptoquant/monitor/journal.py` | JSONL trade records, thread-safe |
| `AlertHandler` | class | `cryptoquant/monitor/alerts.py` | Webhook alerts with rate limiting and deduplication |
| `HealthChecker` | class | `cryptoquant/monitor/health.py` | Exchange, balance, data freshness checks |
| `Trade` | dataclass | `cryptoquant/engine/types.py` | Trade lifecycle record (entry → exit + metrics) |
| `BacktestResult` | dataclass | `cryptoquant/engine/types.py` | Full backtest output (trades + metrics + curves) |

## CONVENTIONS

- **Signal convention**: `1` = long, `-1` = short, `0` = flat. Series same length as input DataFrame.
- **Timestamps**: Unix milliseconds everywhere. DataFrames use `DatetimeIndex` (UTC, no timezone).
- **Strategy params**: Injected via `params` dict in constructor, never hardcoded. Access via `self.params["key"]`.
- **Error hierarchy**: `CryptoQuantError` → `DataError` / `StrategyError` / `ExecutionError` / `RiskError`. See `cryptoquant/exceptions.py`.
- **Config**: pydantic-settings with YAML base + `.env` overlay. Use `load_config()` (cached singleton). All risk/trading params in typed config objects.
- **Logging**: loguru only. `setup_logging()` in `cryptoquant/monitor/logger.py`. Sanitize secrets via `SanitizingLogger`.
- **Testing**: pytest, one test file per module (`test_<module>.py`). Integration tests marked with `@pytest.mark.integration`.
- **Crash recovery**: Engine reconciles exchange state on startup (cancel stale orders + sync positions + restore risk state).
- **Daily reset**: RiskManager auto-resets daily stats at midnight UTC via `check_daily_reset()`.
- **Order tracking**: Active order IDs tracked and persisted in state file for crash recovery.

## ANTI-PATTERNS (THIS PROJECT)

- **DO NOT** use look-ahead bias in backtests — entry at next bar open after signal, stops checked against bar low/high (not close).
- **DO NOT** hardcode strategy parameters — always use `DEFAULT_PARAMS` + `self.params`.
- **DO NOT** import from `research/` in core code — research scripts are standalone experiments.
- **DO NOT** commit `.env`, API keys, or SQLite DB files — CI enforces this.
- **DO NOT** use `as any` / `@ts-ignore` equivalents — pyright strict mode in CI.
- **DO NOT** bypass `validate_ohlcv()` — all fetched data must pass integrity checks.
- **DO NOT** use close price for stop-loss checks — use bar low (longs) / bar high (shorts) when `use_lows_for_stops=True`.
- **DO NOT** skip `can_enter()` before placing orders — risk manager is the sole gatekeeper.

## UNIQUE STYLES

- **Stop priority**: `stop_loss > take_profit > time_exit > signal_reverse` (both backtest and live).
- **Signal reverse**: Works symmetrically for longs and shorts — exit long on short signal, exit short on long signal.
- **Commission model**: Round-trip commission subtracted from gross trade PnL in `BacktestEngine._create_trade()`.
- **State persistence**: JSON + SHA-256 checksum in `StateManager`. Atomic write via tmp + rename. 5 backup versions.
- **Proxy handling**: ccxt sets `trust_env=False`, so proxies must be set manually on `exchange.session.proxies`.
- **Retry policy**: All Broker exchange methods have `@retry_on_network` with exponential backoff + jitter.
- **Drawdown circuit breaker**: 3-tier graduated: REDUCE_HALF (10% DD) → REDUCE_QUARTER (15%) → HALT (20%). Cooldown per tier.
- **Heartbeat**: Every N ticks, engine logs structured status (balance, positions, trades, PnL, risk tier).

## COMMANDS

```bash
# Install dependencies
uv sync --frozen

# Run tests
uv run pytest --cov=cryptoquant

# Run new tests only
uv run pytest tests/test_risk_manager_advanced.py tests/test_alerts_advanced.py -v

# Lint
uv run ruff check .

# Type check
uv run pyright

# Run backtest demo
uv run python demo_backtest.py

# Run live trading (testnet)
uv run python live_runner.py --dry-run
uv run python live_runner.py --symbol BTC/USDT --timeframe 1h --interval 60

# Run a research experiment (create scripts in research/)
uv run python research/backtest_<experiment>.py

# Docker
docker build -t cryptoquant .
docker run -d --name cryptoquant -v $(pwd)/data:/app/data -v $(pwd)/logs:/app/logs -v $(pwd)/state:/app/state --env-file .env cryptoquant

# Deploy (Linux)
sudo bash deploy/install.sh
```

## NOTES

- **Exchange**: Default OKX testnet. Set `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_PASSPHRASE` in `.env` for live.
- **Data**: SQLite at `data/cryptoquant.db` (gitignored). Tables named `ohlcv_{exchange}_{symbol}_{timeframe}`.
- **Research workflow**: Each `research/backtest_*.py` is a standalone experiment. Results documented in `docs/research/`.
- **CI pipeline**: ruff → pyright → pytest + security checks (no .env, no API keys in source).
- **Branch**: `dev` is main development branch.
- **Pre-live checklist**: See `docs/operations.md` for full startup, monitoring, and emergency procedures.
