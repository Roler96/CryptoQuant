# CryptoQuant — Project Knowledge Base

**Generated:** 2026-06-15
**Commit:** d035fa6
**Branch:** dev

## OVERVIEW

Cryptocurrency quantitative trading system. Python 3.11+, ccxt for exchange connectivity, pandas/numpy for data, SQLite for persistence, loguru for logging. Supports backtesting and live trading with risk management.

## STRUCTURE

```
CryptoQuant/
├── cryptoquant/          # Core library (6 submodules)
│   ├── engine/           # Backtest + live execution engines
│   ├── strategy/         # Strategy ABC + technical indicators
│   ├── execution/        # ccxt broker wrapper + order types
│   ├── data/             # 3-level cache (memory → SQLite → exchange)
│   ├── risk/             # Pre-trade checks + position sizing
│   └── monitor/          # Logging, journaling, PnL reporting, log sanitization
├── strategies/           # Concrete strategy implementations
├── research/             # Standalone backtest scripts (one per experiment)
├── tests/                # pytest suite (mirrors cryptoquant/ structure)
├── docs/                 # Plans + research literature
├── data/                 # SQLite DB (gitignored)
├── config.yaml           # Runtime config (exchange, data, trading, logging)
├── pyproject.toml        # uv-managed, ruff + pytest + pyright
└── demo_backtest.py      # Entry point: end-to-end backtest demo
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Run backtest | `demo_backtest.py`, `backtest_btc.py` | Fetches OKX data → SQLite → BacktestEngine |
| Add new strategy | `strategies/` | Subclass `Strategy`, implement `generate_signal()` |
| Modify backtest logic | `cryptoquant/engine/backtest.py` | Vectorized, 627 lines |
| Modify live trading | `cryptoquant/engine/live.py` | Tick-based loop, 517 lines |
| Change data pipeline | `cryptoquant/data/cache.py` | L1/L2/L3 cascade |
| Adjust risk rules | `cryptoquant/risk/manager.py` | Pre-trade gatekeeper |
| Add technical indicator | `cryptoquant/strategy/signals.py` | Pure numpy/pandas, no external deps |
| Run experiments | `research/` | Each file is standalone, not imported by core |
| Config reference | `config.yaml` + `cryptoquant/config.py` | pydantic-settings, .env overlay |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `Strategy` | ABC | `cryptoquant/strategy/base.py` | Base class: `generate_signal(df) -> Series[1,0,-1]` |
| `BacktestEngine` | class | `cryptoquant/engine/backtest.py` | Vectorized backtest, compound returns |
| `LiveEngine` | class | `cryptoquant/engine/live.py` | Real-time tick loop, broker + risk + state |
| `DataCache` | class | `cryptoquant/data/cache.py` | 3-level cache: LRU → SQLite → ccxt |
| `OHLCVStore` | class | `cryptoquant/data/store.py` | SQLite WAL storage, one table per (exchange, symbol, tf) |
| `OHLCVFetcher` | class | `cryptoquant/data/fetcher.py` | ccxt wrapper, validates OHLCV integrity |
| `Broker` | class | `cryptoquant/execution/broker.py` | ccxt wrapper, retry logic, proxy support |
| `RiskManager` | class | `cryptoquant/risk/manager.py` | Daily limits, drawdown circuit breaker, emergency stop |
| `PositionSizer` | ABC | `cryptoquant/risk/sizer.py` | Fixed / Kelly / ATR sizing methods |
| `AppConfig` | dataclass | `cryptoquant/config.py` | Root config, YAML + .env overlay |
| `Trade` | dataclass | `cryptoquant/engine/types.py` | Trade lifecycle record (entry → exit + metrics) |
| `BacktestResult` | dataclass | `cryptoquant/engine/types.py` | Full backtest output (trades + metrics + curves) |

## CONVENTIONS

- **Signal convention**: `1` = long, `-1` = short, `0` = flat. Series same length as input DataFrame.
- **Timestamps**: Unix milliseconds everywhere. DataFrames use `DatetimeIndex` (UTC, no timezone).
- **Strategy params**: Injected via `params` dict in constructor, never hardcoded. Access via `self.params["key"]`.
- **Error hierarchy**: `CryptoQuantError` → `DataError` / `StrategyError` / `ExecutionError` / `RiskError`. See `cryptoquant/exceptions.py`.
- **Config**: pydantic-settings with YAML base + `.env` overlay. Use `load_config()` (cached singleton).
- **Logging**: loguru only. `setup_logging()` in `cryptoquant/monitor/logger.py`. Sanitize secrets via `SanitizingLogger`.
- **Testing**: pytest, one test file per module (`test_<module>.py`). Integration tests marked with `@pytest.mark.integration`.

## ANTI-PATTERNS (THIS PROJECT)

- **DO NOT** use look-ahead bias in backtests — entry at next bar open after signal, stops checked against bar low/high (not close).
- **DO NOT** hardcode strategy parameters — always use `DEFAULT_PARAMS` + `self.params`.
- **DO NOT** import from `research/` in core code — research scripts are standalone experiments.
- **DO NOT** commit `.env`, API keys, or SQLite DB files — CI enforces this.
- **DO NOT** use `as any` / `@ts-ignore` equivalents — pyright strict mode in CI.
- **DO NOT** bypass `validate_ohlcv()` — all fetched data must pass integrity checks.
- **DO NOT** use close price for stop-loss checks — use bar low (longs) / bar high (shorts) when `use_lows_for_stops=True`.

## UNIQUE STYLES

- **Stop priority**: `stop_loss > take_profit > time_exit > signal_reverse` (both backtest and live).
- **Commission model**: Round-trip commission subtracted from gross trade PnL in `BacktestEngine._create_trade()`.
- **State persistence**: JSON + SHA-256 checksum in `StateManager`. Atomic write via tmp + rename.
- **Cache invalidation**: L1 has TTL (default 300s). L2 checks if DB has enough data for requested lookback. L3 only hit on L1+L2 miss.
- **Proxy handling**: ccxt sets `trust_env=False`, so proxies must be set manually on `exchange.session.proxies`.

## COMMANDS

```bash
# Install dependencies
uv sync --frozen

# Run tests
uv run pytest --cov=cryptoquant

# Lint
uv run ruff check .

# Type check
uv run pyright

# Run backtest demo
uv run python demo_backtest.py

# Run specific backtest
uv run python backtest_btc.py
uv run python backtest_wick_btc.py
```

## NOTES

- **Exchange**: Default OKX testnet. Set `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_PASSPHRASE` in `.env` for live.
- **Data**: SQLite at `data/cryptoquant.db` (gitignored). Tables named `ohlcv_{exchange}_{symbol}_{timeframe}`.
- **Research workflow**: Each `research/backtest_*.py` is a standalone experiment. Results documented in `docs/research/`.
- **CI pipeline**: ruff → pyright → pytest + security checks (no .env, no API keys in source).
- **Branch**: `dev` is main development branch.
