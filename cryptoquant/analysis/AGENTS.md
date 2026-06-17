# cryptoquant/analysis/ — Post-Trade Analysis

## OVERVIEW

Post-trade analytics: performance metrics, equity curves, and regime analysis. `TradeAnalyzer` consumes `BacktestResult` or `Trade` lists.

## STRUCTURE

```
analysis/
├── trade_analyzer.py  # TradeAnalyzer — metrics, curves, regime report
└── __init__.py
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Calculate metrics | `trade_analyzer.py` | Sharpe, Sortino, max drawdown, win rate |
| Generate equity curve | `trade_analyzer.py` | Cumulative returns plot data |
| Regime analysis | `trade_analyzer.py` | Performance by market regime |

## CONVENTIONS

- **Input**: `BacktestResult` or list of `Trade` objects.
- **Output**: Dict of metrics + equity curve Series.

## ANTI-PATTERNS

- **DO NOT** analyze trades with look-ahead bias — ensure entry/exit timestamps are correct.
