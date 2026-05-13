# CryptoQuant Backtest Knowledge Base

**Module:** Historical backtesting engine  
**Purpose:** Strategy validation with realistic commission/slippage  
**Status:** ✅ Adapted to SQLite repository (data.storage removed)

## OVERVIEW

Backtrader-based backtesting with custom PandasData feed from SQLite repository. Data is loaded via `data.repository.get_repository().load_as_dataframe()`, which returns a DataFrame with columns: `timestamp, open, high, low, close, volume`.

## STRUCTURE

```
backtest/
├── __init__.py       # Module exports
├── engine.py         # Backtrader integration (~630 lines)
└── metrics.py        # Performance metrics (~500 lines)
```

## WHERE TO LOOK

- `engine.py:BacktestEngine` — Main entry point
- `engine.py:BacktestConfig` — cash, commission, slippage
- `engine.py:BacktestResult` — trades, equity curve, Sharpe, max drawdown
- `engine.py:PandasDataFeed` — Maps DataFrame to Backtrader
- `engine.py:BacktraderStrategyAdapter` — Bridges StrategyBase ↔ Backtrader
- `metrics.py` — Sharpe, drawdown, win rate, profit factor, Calmar

## DATA FLOW

```
SQLite (data/cryptoquant.db)
  → get_repository().load_as_dataframe(pair, timeframe, since=...)
    → DataFrame [timestamp, open, high, low, close, volume]
      → PandasDataFeed._prepare_dataframe()
        → Backtrader Cerebro engine
```

## CONVENTIONS

**Backtest Config:**
- `initial_cash`: Starting capital (default 10,000)
- `commission`: Per-trade fee (default 0.1%)
- `slippage`: Execution penalty (default 0.05%)

**Results:**
- `BacktestResult.to_dict()` for serialization
- Equity curve as `List[float]`
- Trade history with P&L

**Data Loading:**
```python
from data.repository import get_repository

repo = get_repository()
df = repo.load_as_dataframe("BTC/USDT", "1h")
# Returns: DataFrame with columns [timestamp, open, high, low, close, volume]
```

## ANTI-PATTERNS

**FORBIDDEN:**
- Running live without backtesting first
- Ignoring slippage in backtests
- Using insufficient historical data
- Importing from `data.storage` (deleted — use `data.repository`)

**WARNINGS:**
- Backtest != live performance
- Curve-fitting risk on short timeframes
- Survivorship bias in historical data
- Data must exist in SQLite before backtesting (download first)

## UNIQUE STYLES

**Running Backtest:**
```python
from backtest.engine import BacktestEngine, BacktestConfig
from strategy.cta.trend_following import TrendFollowingStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001)
engine = BacktestEngine(config)

strategy = engine.load_strategy("cta")
result = engine.run_backtest(
    strategy=strategy,
    pair="BTC/USDT",
    timeframe="1h",
    days=30,
)
print(f"Return: {result.total_return:.2%}")
```

**Running Backtest (programmatic):**
```python
from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report
from data.repository import get_repository

engine = BacktestEngine()
strategy = engine.load_strategy("cta")
result = engine.run_backtest(strategy, "BTC/USDT", "1h", days=90)

if result.error is None:
    report = generate_performance_report(
        trades=result.trades,
        equity_curve=[Decimal(str(v)) for v in result.equity_curve],
        initial_value=Decimal(str(result.initial_value)),
    )
```

## COMMANDS

```bash
# Download data first (required)
python -m data.downloader --pair BTC/USDT --timeframe 1h --days 365

# Run backtest (when CLI is available)
# python -m cli.main backtest --strategy cta --pair BTC/USDT --timeframe 1h --days 30
```

## NOTES

- **Data Source:** SQLite via `data.repository.get_repository()` (not Parquet files)
- **Plotting:** Uses matplotlib (Agg backend for headless)
- **Metrics:** Sharpe ratio, max drawdown, total return, win rate, profit factor, Calmar
- **Commission:** 0.1% default (OKX spot rate)
- **OHLCVCandle fields:** `open/high/low/close` (not `open_price/close_price`)
