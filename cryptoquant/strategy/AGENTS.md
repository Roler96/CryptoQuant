# cryptoquant/strategy/ — Strategy Framework

## OVERVIEW

Strategy base class and technical indicator library. All strategies subclass `Strategy` and implement `generate_signal()`.

## STRUCTURE

```
strategy/
├── base.py      # Strategy ABC — interface + preprocessing (92 lines)
├── signals.py   # Technical indicators — pure numpy/pandas (287 lines)
└── __init__.py
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Create new strategy | `base.py` | Subclass `Strategy`, set `DEFAULT_PARAMS`, implement `generate_signal()` |
| Add indicator | `signals.py` | Return `pd.Series` or `pd.DataFrame`, same index as input |
| Change preprocessing | `base.py` | `preprocess()` checks columns + min_bars |
| Signal utilities | `signals.py` | `crossover()`, `crossunder()`, `rolling_max/min()` |

## CONVENTIONS

- **Signal values**: `1` = long, `-1` = short, `0` = flat. Return `pd.Series` same length as input.
- **Parameters**: Define in `DEFAULT_PARAMS` dict. Access via `self.params["key"]`. Override in constructor.
- **Timeframe**: Set as class variable `timeframe = "1h"`. Used by engines for bar-to-hours conversion.
- **min_bars**: Set as class variable. `preprocess()` raises `StrategyError` if `len(df) < min_bars`.
- **Indicators**: Pure functions, no side effects. Input: `pd.Series` or `pd.DataFrame`. Output: same.

## ANTI-PATTERNS

- **DO NOT** hardcode parameters in `generate_signal()` — always use `self.params`.
- **DO NOT** call `super().__init__()` in subclass — `Strategy.__init__()` handles params merging.
- **DO NOT** return signals with different index than input DataFrame — engines assume alignment.
- **DO NOT** use external indicator libraries (ta-lib, etc.) — `signals.py` is self-contained.
- **DO NOT** modify input DataFrame in indicators — return new Series/DataFrame.
