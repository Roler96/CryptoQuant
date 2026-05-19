# CryptoQuant Backtest Knowledge Base

**Module:** Historical backtesting engine  
**Purpose:** Strategy validation with realistic commission/slippage  
**Status:** ✅ Operational — adapted to SQLite repository  
**Lines of Code:** 2,155 total

## OVERVIEW

Backtrader-based backtesting with custom PandasData feed from SQLite repository. 
Data is loaded via `data.repository.get_repository().load_as_dataframe()`, which 
returns a DataFrame with columns: `timestamp, open, high, low, close, volume`.

Supports both single-asset (Backtrader event-driven) and multi-asset (vectorized) 
backtesting modes.

## STRUCTURE

```
backtest/
├── __init__.py               # Module exports (53 lines)
├── engine.py                 # Backtrader integration (671 lines)
│                             #   - BacktestEngine, BacktestConfig, BacktestResult
│                             #   - PandasDataFeed, BacktraderStrategyAdapter
├── metrics.py                # Performance metrics (502 lines)
│                             #   - Sharpe, drawdown, win rate, profit factor
│                             #   - Calmar, volatility, annualized return
│                             #   - generate_performance_report
├── run.py                    # CLI runner (133 lines)
├── run_2024_oos.py           # 2024 out-of-sample test (68 lines)
│
├── multi_asset/              # Vectorized multi-asset backtesting (729 lines)
│   ├── __init__.py           # Exports (15 lines)
│   ├── engine.py             # MultiAssetBacktestEngine (507 lines)
│   │                         #   - CrossSectionalStrategy base class
│   │                         #   - Market-neutral portfolio simulation
│   └── data_loader.py        # MultiAssetDataLoader (207 lines)
│                             #   - Timestamp alignment, data pivoting
│
├── ga_results_2025.md        # GA optimization results (research doc)
└── AGENTS.md                 # This file
```

---

## WHERE TO LOOK

### engine.py (671 lines)

| Class/Function | Lines | Description |
|----------------|-------|-------------|
| `BacktestConfig` | 34-42 | Configuration dataclass (cash, commission, slippage, plot) |
| `BacktestResult` | 45-77 | Result dataclass (trades, equity, sharpe, drawdown) + `to_dict()` |
| `PandasDataFeed` | 80-129 | Custom Backtrader data feed from DataFrame |
| `PandasDataFeed.from_dataframe()` | 98-108 | Factory method to create feed |
| `PandasDataFeed._prepare_dataframe()` | 111-129 | Convert timestamp → datetime index |
| `BacktraderStrategyAdapter` | 132-327 | Bridge StrategyBase → Backtrader bt.Strategy |
| `BacktraderStrategyAdapter.__init__()` | 144-161 | Initialize candles, trades, equity tracking |
| `BacktraderStrategyAdapter.next()` | 167-186 | Per-bar execution: candle → signal → order |
| `BacktraderStrategyAdapter._create_candle()` | 188-199 | Convert Backtrader data → OHLCVCandle |
| `BacktraderStrategyAdapter._create_context()` | 201-209 | Build StrategyContext for strategy |
| `BacktraderStrategyAdapter._process_signal()` | 211-254 | Signal → order execution, position reversal |
| `BacktraderStrategyAdapter._calculate_position_size()` | 255-260 | 95% of cash → position size |
| `BacktraderStrategyAdapter._record_trade()` | 262-293 | Record completed trade with P&L |
| `BacktraderStrategyAdapter.notify_order()` | 295-313 | Order execution callback |
| `BacktraderStrategyAdapter.stop()` | 315-327 | End-of-backtest summary |
| `BacktestEngine` | 329-671 | High-level backtest orchestrator |
| `BacktestEngine.__init__()` | 339-353 | Initialize config, strategy map |
| `BacktestEngine.load_strategy()` | 355-383 | Load strategy by name ('cta', 'trend') |
| `BacktestEngine.create_data_feed()` | 385-438 | Load data from SQLite → PandasDataFeed |
| `BacktestEngine.run_backtest()` | 440-597 | Main entry: setup → run → collect results |
| `BacktestEngine._save_equity_plot()` | 599-653 | Generate equity curve PNG |
| `BacktestEngine.get_available_strategies()` | 655-661 | List registered strategies |
| `BacktestEngine.register_strategy()` | 663-671 | Register custom strategy |

### metrics.py (502 lines)

| Function/Constant | Lines | Description |
|-------------------|-------|-------------|
| `SHARPE_THRESHOLD` | 27 | Default threshold: 1.0 |
| `MAX_DRAWDOWN_THRESHOLD` | 28 | Default threshold: 0.20 (20%) |
| `WIN_RATE_THRESHOLD` | 29 | Default threshold: 0.40 (40%) |
| `calculate_sharpe_ratio()` | 32-95 | Annualized Sharpe (risk-adjusted return) |
| `calculate_max_drawdown()` | 98-133 | Peak-to-trough maximum decline |
| `calculate_win_rate()` | 136-167 | Winning trades / total trades |
| `calculate_profit_factor()` | 170-210 | Gross profit / gross loss |
| `calculate_annualized_return()` | 213-264 | Compound annual growth rate |
| `calculate_volatility()` | 267-311 | Annualized standard deviation |
| `calculate_average_trade()` | 314-341 | Mean P&L per trade |
| `calculate_calmar_ratio()` | 344-381 | Annualized return / max drawdown |
| `generate_performance_report()` | 384-469 | Comprehensive report dict |
| `get_threshold_status()` | 472-502 | Single metric threshold check |

### run.py (133 lines)

| Function | Lines | Description |
|----------|-------|-------------|
| `parse_args()` | 19-54 | argparse setup (--strategy, --pair, --days, etc.) |
| `format_period()` | 57-64 | Format date range for display |
| `run()` | 67-133 | CLI entry point, result printing |

### multi_asset/engine.py (507 lines)

| Class/Function | Lines | Description |
|----------------|-------|-------------|
| `MultiAssetBacktestConfig` | 36-46 | Config for multi-asset (exposure, concentration) |
| `MultiAssetBacktestResult` | 49-93 | Result with equity, positions, turnover |
| `MultiAssetBacktestEngine` | 95-465 | Vectorized backtest engine |
| `MultiAssetBacktestEngine.run_backtest()` | 115-299 | Main loop: load → rebalance → track |
| `_get_rebalance_timestamps()` | 301-330 | Determine rebalance points (daily/weekly) |
| `_allocate_positions()` | 332-377 | Factor score → long/short weights |
| `_execute_rebalance()` | 379-443 | Trade execution simulation |
| `CrossSectionalStrategy` | 467-508 | Abstract base for cross-sectional strategies |
| `CrossSectionalStrategy.compute_scores()` | 485-504 | MUST implement: returns factor scores |

### multi_asset/data_loader.py (207 lines)

| Class/Function | Lines | Description |
|----------------|-------|-------------|
| `MultiAssetDataLoader` | 20-149 | Multi-asset data loader |
| `MultiAssetDataLoader.load_data()` | 35-89 | Load multi-index DataFrame |
| `MultiAssetDataLoader.get_close_prices()` | 91-117 | Pivot → timestamp × pair matrix |
| `MultiAssetDataLoader.get_returns()` | 119-142 | Percentage returns matrix |
| `MultiAssetDataLoader.get_available_pairs()` | 144-149 | List pairs in repository |
| `download_missing_pairs()` | 151-208 | Download data for missing pairs |

---

## DATA FLOW

### Single-Asset Backtest

```
SQLite (data/cryptoquant.db)
  → get_repository().load_as_dataframe(pair, timeframe, since=..., until=...)
    → DataFrame [timestamp, open, high, low, close, volume]
      → PandasDataFeed._prepare_dataframe()
        → DataFrame indexed by datetime
          → Backtrader Cerebro.adddata()
            → BacktraderStrategyAdapter.next()
              → OHLCVCandle → Strategy.on_bar()
                → Signal → order execution
                  → trades[], equity_curve[]
```

### Multi-Asset Backtest

```
SQLite (data/cryptoquant.db)
  → MultiAssetDataLoader.get_close_prices(pairs, timeframe, start, end)
    → DataFrame [timestamp × pair] with close prices
      → returns = prices.pct_change()
        → CrossSectionalStrategy.compute_scores(prices, returns, ts)
          → factor_scores Series [pair → score]
            → MultiAssetBacktestEngine._allocate_positions()
              → long_weights[], short_weights[]
                → _execute_rebalance()
                  → trades[], positions_history[]
                    → equity_curve[]
```

---

## CORE COMPONENTS

### BacktestConfig (engine.py:34-42)

```python
@dataclass
class BacktestConfig:
    initial_cash: float = 10000.0     # Starting capital
    commission: float = 0.001         # Per-trade fee (0.1% = OKX spot)
    slippage: float = 0.0005          # Execution penalty (0.05%)
    plot_results: bool = True         # Generate equity curve PNG
    log_path: str = "logs"            # Directory for plots
```

### BacktestResult (engine.py:45-77)

```python
@dataclass
class BacktestResult:
    strategy_name: str
    pair: str
    timeframe: str
    initial_value: float
    final_value: float
    total_return: float
    trades: List[Dict[str, Any]]       # Trade history
    equity_curve: List[float]          # Portfolio values over time
    equity_timestamps: List[int]       # Corresponding timestamps
    sharpe_ratio: Optional[float]
    max_drawdown: Optional[float]
    config: Optional[BacktestConfig]
    plot_path: Optional[str]
    error: Optional[str]
    
    def to_dict(self) -> Dict[str, Any]: ...
```

### PandasDataFeed (engine.py:80-129)

Custom Backtrader data feed mapping our DataFrame format:

```python
class PandasDataFeed(bt.feeds.PandasData):
    params = (
        ("datetime", 0),    # Column 0: timestamp → datetime index
        ("open", 1),        # Column 1: open
        ("high", 2),        # Column 2: high
        ("low", 3),         # Column 3: low
        ("close", 4),       # Column 4: close
        ("volume", 5),      # Column 5: volume
        ("openinterest", -1),  # Not used
    )
    
    @classmethod
    def from_dataframe(cls, dataframe: pd.DataFrame) -> "PandasDataFeed":
        processed_df = cls._prepare_dataframe(dataframe)
        return bt.feeds.PandasData(dataname=processed_df)
```

**_prepare_dataframe() transformations:**
1. Copy DataFrame (avoid mutation)
2. Convert `timestamp` (ms) → `datetime` index
3. Validate required columns exist
4. Return `[open, high, low, close, volume]` columns

### BacktraderStrategyAdapter (engine.py:132-327)

Bridges our `StrategyBase` to Backtrader's `bt.Strategy`:

```python
class BacktraderStrategyAdapter(bt.Strategy):
    params = (
        ("strategy_instance", None),  # StrategyBase instance
        ("pair", ""),
        ("timeframe", ""),
    )
```

**Key methods:**

| Method | Purpose |
|--------|---------|
| `__init__()` | Initialize candles list, trades list, equity tracking |
| `next()` | Per-bar: create OHLCVCandle → call strategy.on_bar() → process signal |
| `_process_signal()` | Convert Signal → Backtrader order (handle position reversal) |
| `_record_trade()` | Calculate P&L, record to trades list |
| `notify_order()` | Log order execution |
| `stop()` | Print final summary |

**Position reversal logic:**
- LONG signal while in short → close short first, then open long
- SHORT signal while in long → close long first, then open short

---

## PERFORMANCE METRICS

### Thresholds (metrics.py:27-29)

| Metric | Threshold | Direction |
|--------|-----------|-----------|
| Sharpe Ratio | >= 1.0 | Higher is better |
| Max Drawdown | <= 20% | Lower is better |
| Win Rate | >= 40% | Higher is better |

### Metric Functions

| Function | Formula | Returns |
|----------|---------|---------|
| `calculate_sharpe_ratio()` | `(ann_return - rf_rate) / ann_volatility` | Decimal or None |
| `calculate_max_drawdown()` | `max((peak - value) / peak)` | Decimal (0.0-1.0) |
| `calculate_win_rate()` | `winning_trades / total_trades` | Decimal (0.0-1.0) |
| `calculate_profit_factor()` | `gross_profit / gross_loss` | Decimal or None (infinite) |
| `calculate_annualized_return()` | `(final/initial)^(1/years) - 1` | Decimal or None |
| `calculate_volatility()` | `std_dev * sqrt(365)` | Decimal or None |
| `calculate_calmar_ratio()` | `ann_return / max_drawdown` | Decimal or None |
| `calculate_average_trade()` | `sum(pnl) / count` | Decimal |

### generate_performance_report() Output

```python
{
    "summary": {
        "initial_value": float,
        "final_value": float,
        "total_return": float,
        "total_trades": int,
        "winning_trades": int,
        "losing_trades": int,
    },
    "returns": {
        "total_return_pct": float,
        "annualized_return_pct": float or None,
        "volatility_pct": float or None,
    },
    "risk_metrics": {
        "sharpe_ratio": float or None,
        "max_drawdown_pct": float or None,
        "calmar_ratio": float or None,
    },
    "trade_metrics": {
        "win_rate_pct": float or None,
        "profit_factor": float or None,
        "average_trade_pnl": float,
    },
    "thresholds": {
        "sharpe_ratio": {"value": float, "threshold": 1.0, "pass": bool},
        "max_drawdown": {"value": float, "threshold": 0.20, "pass": bool},
        "win_rate": {"value": float, "threshold": 0.40, "pass": bool},
        "overall_pass": bool,
    },
    "metadata": {
        "data_points": int,
        "calculation_timestamp": str,
    },
}
```

---

## MULTI-ASSET BACKTESTING

### MultiAssetBacktestConfig (multi_asset/engine.py:36-46)

```python
@dataclass
class MultiAssetBacktestConfig:
    initial_cash: float = 100000.0
    commission: float = 0.0005        # 0.05% (OKX futures rate)
    slippage: float = 0.0002          # 0.02%
    gross_exposure: float = 2.0       # 100% long + 100% short
    rebalance_frequency: str = "1d"   # Daily rebalance
    position_concentration_limit: float = 0.15  # Max 15% per position
    min_position_size: float = 0.01   # Min 1% position
```

### CrossSectionalStrategy (multi_asset/engine.py:467-508)

Abstract base class for cross-sectional (market-neutral) strategies:

```python
class CrossSectionalStrategy:
    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None):
        self.name = name
        self.params = params or {}
    
    def compute_scores(
        self,
        prices: pd.DataFrame,    # Historical close prices
        returns: pd.DataFrame,   # Historical returns
        timestamp: int,
    ) -> pd.Series:
        """Return factor scores indexed by pair.
        Higher = better (longed), Lower = worse (shorted).
        """
        raise NotImplementedError()
    
    def get_param(self, key: str, default: Any = None) -> Any: ...
```

**Implementation example:**

```python
class MomentumStrategy(CrossSectionalStrategy):
    def compute_scores(self, prices, returns, timestamp):
        # 20-day momentum
        lookback = self.get_param("lookback", 20)
        momentum = prices.iloc[-lookback:].pct_change().sum()
        return momentum  # Higher momentum → longed
```

### MultiAssetDataLoader (multi_asset/data_loader.py:20-149)

```python
loader = MultiAssetDataLoader()

# Load as multi-index DataFrame
df = loader.load_data(
    pairs=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    timeframe="1h",
    start_date="2024-01-01",
    end_date="2024-12-31",
)
# Index: (timestamp, pair), Columns: open, high, low, close, volume

# Get close prices as matrix
close_prices = loader.get_close_prices(pairs, timeframe, start, end)
# Index: timestamp, Columns: pair names, Values: close prices

# Get returns matrix
returns = loader.get_returns(pairs, timeframe, start, end)
# Index: timestamp, Columns: pair names, Values: pct_change()

# Get available pairs
pairs = loader.get_available_pairs()
```

---

## CLI USAGE

### run.py — Single-Asset Backtest CLI

```bash
# By days (last N days from now)
python backtest/run.py -s cta -p BTC/USDT -t 1h --days 90

# By date range
python backtest/run.py -s cta -p BTC/USDT -t 1h --start 2024-01-01 --end 2024-06-30

# Open-ended (from a date to now)
python backtest/run.py -s cta -p BTC/USDT -t 4h --start 2024-06-01

# Custom parameters
python backtest/run.py -s cta -p ETH/USDT -t 4h --days 180 \
    --cash 50000 --commission 0.001 --slippage 0.001 --no-plot

# List available strategies
python backtest/run.py --list-strategies
```

**Arguments:**

| Argument | Default | Description |
|----------|---------|-------------|
| `--strategy`, `-s` | required | Strategy name (cta, trend_following, trend) |
| `--pair`, `-p` | BTC/USDT | Trading pair |
| `--timeframe`, `-t` | 1h | Candle interval |
| `--days`, `-d` | 90 | Backtest period (if no --start) |
| `--start` | None | Start date (YYYY-MM-DD) |
| `--end` | None | End date (YYYY-MM-DD) |
| `--cash` | 10000 | Initial capital |
| `--commission` | 0.001 | Fee rate |
| `--slippage` | 0.0005 | Slippage rate |
| `--no-plot` | False | Skip equity plot |
| `--list-strategies`, `-l` | False | Show available strategies |

---

## PROGRAMMATIC USAGE

### Single-Asset Backtest

```python
from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import generate_performance_report

# Initialize engine
config = BacktestConfig(
    initial_cash=10000,
    commission=0.001,   # 0.1%
    slippage=0.0005,    # 0.05%
    plot_results=True,
)
engine = BacktestEngine(config)

# Load strategy
strategy = engine.load_strategy("cta")
# Available: "cta", "trend_following", "trend"

# Run backtest
result = engine.run_backtest(
    strategy=strategy,
    pair="BTC/USDT",
    timeframe="1h",
    days=90,            # Last 90 days
    # OR:
    start_date="2024-01-01",
    end_date="2024-12-31",
)

# Check result
if result.error:
    print(f"Error: {result.error}")
else:
    print(f"Return: {result.total_return:.2%}")
    print(f"Trades: {len(result.trades)}")
    print(f"Sharpe: {result.sharpe_ratio:.4f}")
    print(f"Max DD: {result.max_drawdown:.2%}")
    
    # Generate detailed report
    from decimal import Decimal
    report = generate_performance_report(
        trades=result.trades,
        equity_curve=[Decimal(str(v)) for v in result.equity_curve],
        initial_value=Decimal(str(result.initial_value)),
    )
```

### Multi-Asset Backtest

```python
from backtest.multi_asset import MultiAssetBacktestEngine, MultiAssetBacktestConfig
from backtest.multi_asset.engine import CrossSectionalStrategy

# Define strategy
class MomentumStrategy(CrossSectionalStrategy):
    def compute_scores(self, prices, returns, timestamp):
        lookback = self.get_param("lookback", 20)
        return prices.iloc[-lookback:].pct_change().sum()

# Initialize engine
config = MultiAssetBacktestConfig(
    initial_cash=100000,
    gross_exposure=2.0,  # Market-neutral
    rebalance_frequency="1d",
)
engine = MultiAssetBacktestEngine(config)

# Run backtest
strategy = MomentumStrategy("momentum", {"lookback": 20})
result = engine.run_backtest(
    strategy=strategy,
    pairs=["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"],
    timeframe="1h",
    start_date="2024-01-01",
    end_date="2024-12-31",
)

print(f"Return: {result.total_return:.2%}")
print(f"Sharpe: {result.sharpe_ratio:.4f}")
print(f"Turnover: {result.turnover:.2f}")
print(f"Long Exposure Avg: {result.long_exposure_avg:.2%}")
print(f"Short Exposure Avg: {result.short_exposure_avg:.2%}")
```

### Register Custom Strategy

```python
from backtest.engine import BacktestEngine
from strategy.base import StrategyBase

class MyCustomStrategy(StrategyBase):
    def on_bar(self, candle, context):
        # Custom logic
        return Signal(...)

# Register for backtest
engine = BacktestEngine()
engine.register_strategy("my_strategy", MyCustomStrategy)

# Now available
strategy = engine.load_strategy("my_strategy")
```

---

## ANTI-PATTERNS

**FORBIDDEN:**
- Running live without backtesting first
- Ignoring slippage/commission in backtests (unrealistic expectations)
- Using insufficient historical data (< 30 days)
- Importing from `data.storage` (deleted — use `data.repository`)
- Using `xxx_price` field names (e.g., `close_price`) — use `open/high/low/close`

**WARNINGS:**
- Backtest != live performance (execution differences, slippage variance)
- Curve-fitting risk on short timeframes
- Survivorship bias in historical data
- Data must exist in SQLite before backtesting (download first)
- `PandasDataFeed` requires `timestamp` column in milliseconds
- Multi-asset backtest assumes market-neutral (no net directional exposure)

---

## NOTES

- **Data Source:** SQLite via `data.repository.get_repository()` (not Parquet files)
- **Backtrader:** Uses `bt.Cerebro` with built-in Sharpe/DrawDown analyzers
- **Plotting:** Uses matplotlib (Agg backend for headless servers)
- **Metrics:** Sharpe, max drawdown, total return, win rate, profit factor, Calmar
- **Commission:** 0.1% default (OKX spot rate), 0.05% for futures (multi-asset)
- **Timeframes:** Supports 1m, 5m, 15m, 1h, 4h, 1d, 1w
- **Position Size:** Single-asset uses 95% of available cash
- **Reversal:** Handles position reversal (long→short, short→long) cleanly
- **Crypto Year:** 365 trading days (not 252 like traditional markets)

---

## PUBLIC API (__init__.py)

```python
from backtest import (
    BacktestEngine,
    BacktestConfig,
    BacktestResult,
    BacktraderStrategyAdapter,
    PandasDataFeed,
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_annualized_return,
    calculate_volatility,
    calculate_average_trade,
    calculate_calmar_ratio,
    generate_performance_report,
    get_threshold_status,
    SHARPE_THRESHOLD,
    MAX_DRAWDOWN_THRESHOLD,
    WIN_RATE_THRESHOLD,
)

from backtest.multi_asset import (
    MultiAssetBacktestEngine,
    MultiAssetBacktestConfig,
    MultiAssetBacktestResult,
    MultiAssetDataLoader,
)
```