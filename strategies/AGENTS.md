# strategies/ — Concrete Strategy Implementations

## OVERVIEW

User-defined trading strategies. Each subclasses `Strategy` from `cryptoquant.strategy.base` and implements `generate_signal()`.

## STRUCTURE

```
strategies/
├── spring.py              # SpringReversal — mean-reversion on spring candles
├── wick.py                # WickInversion — fade wick extremes
├── bb_upper_breakout.py   # BBUpperBreakout — volatility breakout
├── example/
│   └── ma_cross.py        # Example: SMA20/50 crossover (template)
└── __init__.py
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Create new strategy | `example/ma_cross.py` | Copy as template; set `DEFAULT_PARAMS` |
| Modify spring logic | `spring.py` | SMA200 + BB %B filter inline |
| Modify wick logic | `wick.py` | SMA200 + BB %B filter inline |
| Add breakout strategy | `bb_upper_breakout.py` | Volatility breakout on BB upper band |

## CONVENTIONS

- **Signal values**: `1` = long, `-1` = short, `0` = flat. Return `pd.Series` same length as input.
- **Parameters**: Define in `DEFAULT_PARAMS` dict. Access via `self.params["key"]`. Override in constructor.
- **Timeframe**: Set as class variable `timeframe = "1h"`. Used by engines for bar-to-hours conversion.
- **Filters**: Currently inline in each strategy (SMA200 + BB %B). `todo.md` plans extraction to composable filter functions.

## ANTI-PATTERNS

- **DO NOT** hardcode parameters in `generate_signal()` — always use `self.params`.
- **DO NOT** duplicate filter logic across strategies — extract shared filters to `cryptoquant.strategy.signals.py`.
- **DO NOT** set file permissions to `600` for strategy files — use standard `644`.
