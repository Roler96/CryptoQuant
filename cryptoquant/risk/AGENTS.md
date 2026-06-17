# cryptoquant/risk/ — Risk Management

## OVERVIEW

Pre-trade risk gatekeeper, position sizing, and portfolio-level checks.

## STRUCTURE

```
risk/
├── manager.py      # RiskManager — daily limits, drawdown, emergency stop
├── sizer.py        # PositionSizer ABC — Fixed / Kelly / ATR
├── correlation.py  # Cross-position correlation limits (standalone)
├── cvar.py         # Conditional Value-at-Risk position sizing
└── __init__.py
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Change risk rules | `manager.py` | `can_enter()` — daily limits, drawdown circuit breaker |
| Change position size | `sizer.py` | `FixedSizer`, `KellySizer`, `ATRSizer` |
| Add correlation check | `correlation.py` | Standalone — not wired into `RiskManager` yet |
| Add CVaR sizing | `cvar.py` | Standalone — not wired into `RiskManager` yet |

## CONVENTIONS

- **Sizing**: Always return `int` number of contracts. Clamp to `balance` and `min_order`.
- **Risk check order**: Correlation → Daily limits → Drawdown → Emergency stop.
- **Drawdown**: 3-tier graduated circuit breaker (soft / medium / hard).

## ANTI-PATTERNS

- **DO NOT** bypass `RiskManager.can_enter()` before placing orders.
- **DO NOT** use close price for stop-loss checks — use bar low (longs) / bar high (shorts).
- **DO NOT** instantiate `Broker` or `OHLCVFetcher` directly in risk tests — use mocks.
