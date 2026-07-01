# cryptoquant/strategy/signals.py — Technical Indicators

## OVERVIEW

Pure numpy/pandas technical indicator library. No external dependencies (no ta-lib, etc.). All indicators return `pd.Series` or `pd.DataFrame` with the same index as input.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new indicator | `signals.py` | Function signature: `(series, **params) -> pd.Series` |
| Find existing indicator | `signals.py` | Search by function name |
| Test indicator | `tests/test_signals.py` | Basic smoke tests + edge cases |
| Use in strategy | `from cryptoquant.strategy.signals import x` | Import in strategy file |

## CONVENTIONS

- **Input**: `pd.Series` for single-line indicators, `pd.DataFrame` for multi-column (OHLCV).
- **Output**: `pd.Series` or `pd.DataFrame`, same index length as input (NaN for warmup bars).
- **Naming**: lowercase_with_underscores. Descriptive: `ema`, `bollinger_bands`, `hurst_exponent`.
- **Params**: keyword arguments with defaults. Period/lookback params named `period` or `window`.
- **No side effects**: indicators are pure functions. They do NOT modify the input DataFrame.

## ANTI-PATTERNS

- **DO NOT** add ta-lib or any external dependency — keep it pure numpy/pandas.
- **DO NOT** return different-length Series — NaN-pad the warmup bars.
- **DO NOT** hardcode indicator parameters in strategy files — pass from `self.params`.
