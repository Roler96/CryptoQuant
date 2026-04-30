# CryptoQuant Risk Knowledge Base

**Module:** Risk management controls  
**Purpose:** Position sizing, stop-loss, drawdown limits, circuit breakers

## OVERVIEW

Risk management layer enforcing position limits, stop-loss rules, and drawdown-based circuit breakers. Prevents catastrophic losses through automated position closure.

## STRUCTURE

```
risk/
├── __init__.py           # Module exports
├── position_sizing.py    # Position size calculations (419 lines)
└── stop_loss.py          # Stop-loss logic (534 lines)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Position sizing | `position_sizing.py` | Kelly, fixed fractional, volatility-based |
| Stop loss | `stop_loss.py` | Trailing stops, time stops, loss limits |
| Drawdown check | `stop_loss.py:DrawdownMonitor` | Circuit breaker on max drawdown |
| Risk limits | `config.yaml:risk` | Configurable thresholds |

## CONVENTIONS

**Position Sizing Methods:**
- `fixed_fractional`: Fixed % of portfolio per trade
- `kelly_criterion`: Optimal f based on win rate
- `volatility_based`: Inverse volatility weighting

**Stop Types:**
- `price_stop`: Fixed price level
- `trailing_stop`: Follows favorable moves
- `time_stop`: Exit after time limit

## ANTI-PATTERNS

**FORBIDDEN:**
- Risk limits >10% per position
- Skipping stop-loss on live trades
- Ignoring drawdown circuit breakers

**WARNINGS:**
- Default `max_position_pct: 0.1` (10%)
- Default `max_drawdown: 0.15` (15%)
- Stop-loss triggers immediate market order

## UNIQUE STYLES

**Position Sizing:**
```python
from risk.position_sizing import PositionSizer
from decimal import Decimal

sizer = PositionSizer(method="fixed_fractional", risk_per_trade=Decimal('0.02'))
size = sizer.calculate_size(
    capital=Decimal('10000'),
    entry_price=Decimal('50000'),
    stop_price=Decimal('49000')
)
```

**Stop Loss:**
```python
from risk.stop_loss import StopLossManager

manager = StopLossManager()
manager.set_stop_loss(
    pair="BTC/USDT",
    entry_price=Decimal('50000'),
    stop_price=Decimal('49000'),  # 2% stop
    trailing=True
)
```

## CONFIGURATION

```yaml
risk:
  max_daily_loss: 0.05      # 5% daily loss limit
  max_drawdown: 0.15        # 15% max drawdown
  stop_loss_pct: 0.02       # 2% stop loss
  take_profit_pct: 0.05     # 5% take profit
  max_positions: 5          # Max open positions
```

## NOTES

- **Circuit Breaker:** Automatic kill switch on max drawdown
- **Trailing Stops:** Adjust with favorable price moves
- **Time Stops:** Close positions after holding period
- **P&L:** All calculations use `Decimal` for precision
