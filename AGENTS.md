# CryptoQuant Knowledge Base

**Project:** Crypto Quant Trading Platform  
**Stack:** Python 3.10+, asyncio, Pydantic, structlog, ccxt, backtrader  
**Purpose:** Quantitative cryptocurrency trading with backtesting and live execution

## OVERVIEW

A modular Python platform for quantitative crypto trading on OKX exchange. Supports multi-strategy backtesting, paper trading, and live execution with integrated risk management.

## STRUCTURE

```
cryptoquant/
├── cli/              # CLI entry points (argparse-based)
├── config/           # YAML configuration
├── cryptoquant/      # Package entry (__main__.py)
├── data/             # Data management, models, storage
├── backtest/         # Backtesting engine (Backtrader-based)
├── live/             # Live trading execution
├── risk/             # Risk management (position sizing, stop-loss)
├── strategy/         # Trading strategies framework
├── logs/             # Logging and audit trail
└── tests/            # Pytest test suite
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new strategy | `strategy/base.py` + `strategy/cta/`, `strategy/stat_arb/` | Inherit from `StrategyBase` |
| CLI commands | `cli/main.py`, `cli/commands/` | argparse subcommands |
| Data models | `data/models.py` | OHLCV, OrderBook, Balance dataclasses |
| OKX API client | `data/manager.py` | Rate-limited ccxt wrapper |
| Backtest entry | `backtest/engine.py` | Backtrader integration |
| Live trading | `live/trading.py`, `live/paper_trading.py` | Paper vs live modes |
| Risk controls | `risk/stop_loss.py`, `risk/position_sizing.py` | Drawdown limits |
| Configuration | `config/config.yaml` | Trading params, risk limits |
| Logs/Audit | `logs/audit.py`, `logs/logger.py` | structlog + file rotation |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `StrategyBase` | ABC | `strategy/base.py` | All strategies inherit |
| `Signal` | dataclass | `strategy/base.py` | Trading signals |
| `StrategyContext` | dataclass | `strategy/base.py` | Market data + positions |
| `OHLCVCandle` | dataclass | `data/models.py` | Price data model |
| `BacktestEngine` | class | `backtest/engine.py` | Backtesting runner |
| `BacktestResult` | dataclass | `backtest/engine.py` | Results container |
| `OKXDataManager` | class | `data/manager.py` | Exchange API client |
| `RateLimiter` | class | `data/manager.py` | Token bucket rate limiter |
| `main()` | function | `cli/main.py` | CLI entry point |
| `run_backtest()` | function | `cli/commands/backtest.py` | Backtest command |

## CONVENTIONS

**Python Style:**
- Use `Decimal` for all price/quantity calculations (never float)
- `frozen=True` dataclasses for immutable data (candles, signals)
- Type hints required (mypy enforced)
- structlog for structured logging

**Import Pattern:**
```python
from decimal import Decimal  # REQUIRED for money math
from data.models import OHLCVCandle, Ticker
from strategy.base import StrategyBase, Signal, SignalType
```

**Error Handling:**
- Custom exceptions in `data/manager.py`: `OKXAPIError`, `OKXRateLimitError`
- Retry with exponential backoff on API failures

## ANTI-PATTERNS

**FORBIDDEN:**
- Hardcoding API credentials (use `.env` + python-dotenv)
- Using `float` for prices/quantities (precision loss)
- Committing `.env` files (gitignored by default)
- Skipping dry-run before live trading

**WARNINGS:**
- Live trading requires manual confirmation (see `cli/main.py:319`)
- Max 20 requests per 2 seconds to OKX (enforced by `RateLimiter`)

## UNIQUE STYLES

**Strategy Framework:**
```python
class MyStrategy(StrategyBase):
    def generate_signal(self, context: StrategyContext) -> Signal:
        # Access: context.current_price, context.candles, context.positions
        return Signal(SignalType.LONG, pair, timestamp, price)
```

**Signal Types:** `LONG`, `SHORT`, `CLOSE_LONG`, `CLOSE_SHORT`, `HOLD`

**Position Sizing:** Configured in `config.yaml` under `risk.max_position_pct`

## COMMANDS

```bash
# Install dependencies
pip install -r requirements.txt

# Run backtest
python -m cli.main backtest --strategy cta --pair BTC/USDT --timeframe 1h

# Paper trading (simulated funds)
python -m cli.main paper --strategy cta --pair BTC/USDT

# Live trading (DRY-RUN first!)
python -m cli.main live --strategy cta --pair BTC/USDT --dry-run

# Emergency stop
python -m cli.main kill

# Run tests
pytest tests/ -v

# Format + lint
black . && ruff check . --fix && mypy .
```

## NOTES

- **Security:** API keys in `.env` (never committed). See `.env.example` template
- **Data Storage:** Historical OHLCV in `data/historical/` (Parquet format)
- **Exchange:** OKX only (ccxt integration allows others)
- **Mode:** Sandbox default (`exchange.sandbox: true` in config.yaml)
- **Kill Switch:** Emergency stop closes all positions via `cli/main.py run_kill()`

## MODULE GUIDES

- See `cli/AGENTS.md` for CLI patterns
- See `data/AGENTS.md` for data management
- See `live/AGENTS.md` for trading execution
- See `backtest/AGENTS.md` for backtesting
- See `strategy/AGENTS.md` for strategy development
- See `risk/AGENTS.md` for risk controls
