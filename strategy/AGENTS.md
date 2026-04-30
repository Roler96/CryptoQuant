# CryptoQuant Strategy Knowledge Base

**Module:** Trading strategy framework  
**Purpose:** Pluggable strategy system with backtesting/live support

## OVERVIEW

Abstract base class `StrategyBase` defines the strategy interface. Two built-in implementations: trend-following CTA and statistical arbitrage pair trading.

## STRUCTURE

```
strategy/
├── __init__.py              # Module exports
├── base.py                  # StrategyBase ABC (323 lines)
├── cta/
│   ├── __init__.py
│   └── trend_following.py   # Moving average crossover (394 lines)
└── stat_arb/
    ├── __init__.py
    └── pair_trading.py      # Pair trading strategy (393 lines)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Base class | `base.py:StrategyBase` | Abstract base for all strategies |
| Signal types | `base.py:SignalType` | LONG, SHORT, CLOSE_LONG, CLOSE_SHORT, HOLD |
| Context | `base.py:StrategyContext` | Market data + positions |
| Example CTA | `cta/trend_following.py` | SMA crossover strategy |
| Example stat arb | `stat_arb/pair_trading.py` | Correlation-based pairs |

## CONVENTIONS

**Strategy Class:**
```python
class MyStrategy(StrategyBase):
    def initialize(self):
        # Set up indicators
        pass
    
    def generate_signal(self, context: StrategyContext) -> Signal:
        # Analyze context.current_price, context.candles
        # Return Signal(SignalType.LONG, ...)
        pass
```

**Signal Return:**
- Always return a `Signal` object
- Use `SignalType.HOLD` for no action
- Include metadata for debugging

## ANTI-PATTERNS

**FORBIDDEN:**
- Modifying `context.positions` directly
- Using float instead of Decimal
- Storing state in global variables

**WARNINGS:**
- `generate_signal()` called every bar
- Keep calculations lightweight
- Validate params in `initialize()`

## UNIQUE STYLES

**Strategy Template:**
```python
from decimal import Decimal
from strategy.base import StrategyBase, Signal, SignalType, StrategyContext

class MyStrategy(StrategyBase):
    def initialize(self):
        self.lookback = self.get_param("lookback", 20)
        self.threshold = Decimal(str(self.get_param("threshold", 0.02)))
    
    def generate_signal(self, context: StrategyContext) -> Signal:
        candles = context.get_recent_candles(self.lookback)
        if len(candles) < self.lookback:
            return Signal(SignalType.HOLD, context.pair, context.current_time, context.current_price)
        
        # Your logic here
        return Signal(
            signal_type=SignalType.LONG,
            pair=context.pair,
            timestamp=context.current_time,
            price=context.current_price,
            confidence=Decimal('0.8'),
            metadata={"reason": "custom_indicator"}
        )
```

**Loading Strategy:**
```python
from strategy.cta.trend_following import TrendFollowingStrategy
strategy = TrendFollowingStrategy("trend", {"fast_period": 10, "slow_period": 30})
```

## COMMANDS

```bash
# Test strategy
python -m cli.main backtest --strategy cta --pair BTC/USDT
```

## NOTES

- **Lifecycle:** `initialize()` → `on_bar()` per candle → `generate_signal()`
- **Tick Mode:** Override `on_tick()` for tick-based strategies
- **Params:** Access via `get_param(key, default)`
- **Reset:** Call `reset()` to clear state between runs
