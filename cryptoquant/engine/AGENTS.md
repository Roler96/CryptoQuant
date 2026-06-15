# cryptoquant/engine/ — Execution Engines

## OVERVIEW

Backtest and live trading engines. Both consume `Strategy.generate_signal()` and produce `Trade` records.

## STRUCTURE

```
engine/
├── backtest.py    # BacktestEngine — vectorized, compound returns (627 lines)
├── live.py        # LiveEngine — tick-based real-time loop (517 lines)
├── state.py       # StateManager — JSON + SHA-256 persistence
└── types.py       # Trade, PerformanceMetrics, BacktestResult dataclasses
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Modify backtest logic | `backtest.py` | `_simulate_positions()` is the core loop |
| Change metrics calculation | `backtest.py` | `_calculate_metrics()` — Sharpe, Sortino, drawdown |
| Modify live entry/exit | `live.py` | `tick()` → `_enter_position()` / `_exit_position()` |
| Change state persistence | `state.py` | `StateManager.save()/load()` — atomic write + checksum |
| Add result fields | `types.py` | `Trade`, `PerformanceMetrics`, `BacktestResult` |

## CONVENTIONS

- **Entry timing**: Signal at bar `i` → entry at bar `i+1` open (no look-ahead bias).
- **Stop checks**: Use bar low for long stops, bar high for short stops (when `use_lows_for_stops=True`).
- **Exit priority**: `stop_loss > take_profit > time_exit > signal_reverse`.
- **Commission**: Subtracted from gross PnL in `_create_trade()`, not from equity curve directly.
- **Slippage**: Applied to stop/TP exit prices and signal-reverse exits.

## ANTI-PATTERNS

- **DO NOT** use close price for stop-loss checks — causes look-ahead bias.
- **DO NOT** modify `BacktestEngine` state between runs — create new instance per backtest.
- **DO NOT** call `LiveEngine.tick()` without broker connected — will fail on `get_position()`.
- **DO NOT** skip state checksum validation in `StateManager.load()` — detects corruption.
