# CryptoQuant Live Trading Knowledge Base

**Module:** Live trading execution  
**Purpose:** Execute strategies with real or simulated funds on OKX

## OVERVIEW

Three execution modes: paper trading (simulated), dry-run live (real validation), and live trading (real funds). Largest module (~2,200 lines) with order management and kill switch.

## STRUCTURE

```
live/
├── __init__.py          # Module exports
├── trading.py           # Live trading engine (856 lines)
├── paper_trading.py     # Paper trading simulation (667 lines)
├── order_manager.py     # Order lifecycle management (686 lines)
└── kill_switch.py       # Emergency stop functionality
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Live execution | `trading.py` | Real order placement |
| Paper trading | `paper_trading.py` | Simulated balance tracking |
| Order management | `order_manager.py` | Create, cancel, track orders |
| Emergency stop | `kill_switch.py` | Close all positions |
| Position tracking | `paper_trading.py:PaperTrader` | Simulated P&L |

## CONVENTIONS

**Position State:**
- `Position` dataclass tracks size, entry_price, unrealized_pnl
- `is_long`, `is_short`, `is_flat` properties
- P&L calculated with Decimal precision

**Order Flow:**
1. Strategy generates `Signal`
2. OrderManager validates + creates order
3. Execution engine places order
4. Position tracker updates state

## ANTI-PATTERNS

**FORBIDDEN:**
- Running live without `--dry-run` first
- Disabling kill switch in production
- Using float for P&L calculations

**WARNINGS:**
- Requires manual confirmation for live mode
- Sandbox default - set `sandbox: false` for real trading
- Max drawdown triggers automatic kill switch

## UNIQUE STYLES

**Signal Processing:**
```python
def on_signal(self, signal: Signal):
    if signal.is_entry():
        self.order_manager.create_order(
            side="buy" if signal.signal_type == SignalType.LONG else "sell",
            # ...
        )
    elif signal.is_exit():
        self.close_position(signal.pair)
```

**Paper Trading:**
- Simulates fills at mid-price
- Tracks virtual balance
- Logs trades to audit log

## COMMANDS

```bash
# Dry run (recommended first step)
python -m cli.main live --strategy cta --pair BTC/USDT --dry-run

# Paper trading
python -m cli.main paper --strategy cta --pair BTC/USDT --duration 24

# Emergency stop
python -m cli.main kill [--force]
```

## NOTES

- **Safety:** Dry-run mode validates without placing orders
- **Confirmation:** Live mode requires typing 'LIVE'
- **Kill Switch:** Immediate position closure on activation
- **Audit:** All trades logged via `logs/audit.py`
