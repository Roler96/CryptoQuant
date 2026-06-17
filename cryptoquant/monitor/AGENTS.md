# cryptoquant/monitor/ — Observability

## OVERVIEW

Logging, journaling, health checks, alerts, and reporting. All observability code lives here.

## STRUCTURE

```
monitor/
├── logger.py     # setup_logging() — loguru configuration
├── journal.py    # TradeJournal — JSONL trade records, thread-safe
├── health.py     # Broker connectivity + balance checks
├── alerts.py     # Webhook/email notification dispatch
├── reporter.py   # PnL / equity curve report generation
├── sanitizer.py  # SanitizingLogger — redacts secrets from logs
└── __init__.py
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Change log format | `logger.py` | `setup_logging(level, log_dir)` |
| Record a trade | `journal.py` | `TradeJournal.record()` — JSONL, thread-safe |
| Add health check | `health.py` | `HealthCheck.run()` — broker + balance |
| Send alert | `alerts.py` | Webhook/email dispatch on events |
| Generate report | `reporter.py` | Equity curve, PnL summary |
| Sanitize secrets | `sanitizer.py` | `SanitizingLogger` wraps loguru |

## CONVENTIONS

- **Logging**: Use `from loguru import logger`. Never `print()` in production code.
- **Journal**: JSONL format, one line per trade, thread-safe via file locking.
- **Health**: Checks BTC/USDT ticker by default (configurable via `symbol` param).

## ANTI-PATTERNS

- **DO NOT** log raw API keys or secrets — use `SanitizingLogger` or manual redaction.
- **DO NOT** write to journal from multiple processes without external locking.
- **DO NOT** use `datetime.utcnow()` — deprecated in Python 3.12+; use `datetime.now(UTC)`.
