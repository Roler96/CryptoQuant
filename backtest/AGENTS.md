# CryptoQuant Backtest Knowledge Base

**Module:** Historical backtesting engine  
**Purpose:** Strategy validation with realistic commission/slippage

## OVERVIEW

Backtrader-based backtesting with custom PandasData feed from Parquet files. Supports configurable cash, commission, slippage, and generates equity curves + performance metrics.

## STRUCTURE

```
backtest/
├── __init__.py       # Module exports
├── engine.py         # Backtrader integration (633 lines)
└── metrics.py        # Performance metrics (503 lines)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Run backtest | `engine.py:BacktestEngine.run()` | Main entry point |
| Config | `engine.py:BacktestConfig` | cash, commission, slippage |
| Results | `engine.py:BacktestResult` | trades, equity curve, Sharpe |
| Data feed | `PandasDataFeed` | Maps DataFrame to Backtrader |
| Metrics | `metrics.py` | Sharpe, drawdown, returns |
| Plot | `engine.py:plot_results()` | Equity curve visualization |

## CONVENTIONS

**Backtest Config:**
- `initial_cash`: Starting capital (default 10,000)
- `commission`: Per-trade fee (default 0.1%)
- `slippage`: Execution penalty (default 0.05%)

**Results:**
- `BacktestResult.to_dict()` for serialization
- Equity curve as List[float]
- Trade history with P&L

## ANTI-PATTERNS

**FORBIDDEN:**
- Running live without backtesting first
- Ignoring slippage in backtests
- Using insufficient historical data

**WARNINGS:**
- Backtest != live performance
- Curve-fitting risk on short timeframes
- Survivorship bias in historical data

## UNIQUE STYLES

**Running Backtest:**
```python
from backtest.engine import BacktestEngine, BacktestConfig
from strategy.cta.trend_following import TrendFollowingStrategy

config = BacktestConfig(initial_cash=10000, commission=0.001)
engine = BacktestEngine(config)
result = engine.run(
    strategy_class=TrendFollowingStrategy,
    pair="BTC/USDT",
    timeframe="1h",
    days=30
)
print(f"Return: {result.total_return:.2%}")
```

**Data Loading:**
```python
from data.storage import load_historical_data
df = load_historical_data("BTC/USDT", "1h")
```

## COMMANDS

```bash
# Run backtest
python -m cli.main backtest \
  --strategy cta \
  --pair BTC/USDT \
  --timeframe 1h \
  --days 30 \
  --initial-cash 10000
```

## NOTES

- **Data:** Requires historical Parquet files in `data/historical/`
- **Plotting:** Uses matplotlib (Agg backend for headless)
- **Metrics:** Sharpe ratio, max drawdown, total return
- **Commission:** 0.1% default (OKX spot rate)
