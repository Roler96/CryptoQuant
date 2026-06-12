# Spring — Failed Breakdown Reversal

> "Sellers break support. Buyers eat everything. Sellers are trapped.
> Their panic to cover is your profit."

---

## 1. Strategy Insight

### Core Hypothesis

When price makes a new N-bar low but closes back ABOVE its open on elevated
volume, sellers have been trapped. They pushed through support, buyers
absorbed every single sell order, and the bar closes bullish. Trapped sellers
must cover in the following hours — their buying pressure drives price higher.

### Why It Works

1. **New low = sellers succeeded.** The bar made a lower low than any bar in
   the last 30 hours. This is real selling pressure — not just a wick.

2. **Bullish close = buyers instantly reversed it.** Despite breaking support,
   the bar closed above its open. Buyers won the bar.

3. **Elevated volume = conviction.** Above-average volume confirms this was
   a genuine battle, not noise.

4. **Trapped sellers = forced buyers.** Short positions opened at/slightly
   below the breakout level are underwater. Their stop-losses and panic
   covers create upward pressure over the next 4-6 hours.

This is the classic Wyckoff "spring" pattern — a false downside breakout
that traps sellers and resolves in the opposite direction.

### Relationship with Wick Inversion

| Dimension | Wick Inversion | Spring |
|-----------|---------------|--------|
| What it detects | Seller exhaustion (effort without result) | Failed breakdown (sellers trapped) |
| Requires new low? | No | Yes (30-bar) |
| Wick analysis | Upper wick × volume imbalance | Not used |
| Candle pattern | Any | Bullish close required |
| Volume requirement | log compressed | SMA(volume, 20) threshold |
| Market state | Works best in range/mild trend | Works best after pullbacks |
| Signal overlap | Minimal — triggers are mutually exclusive | |

Running both strategies together diversifies across two distinct market
failure patterns.

---

## 2. Signal Calculation

```
For each 1h bar i (after warmup):

1. LOOKBACK = 30 bars (~1 week of trading hours)

2. New low check:
   new_low = low[i] < min(low[i-30 : i])

3. Bullish candle:
   bullish = close[i] > open[i]

4. Volume above average:
   high_vol = volume[i] > mean(volume[i-20 : i])

5. Signal:
   signal = new_low AND bullish AND high_vol

6. Entry: close[i+1] (next bar open ≈ current close)

7. Exit logic (in priority order):
   a. Target: +1.5% (tested optimal across BTC/ETH/multi-pair)
   b. Stop: -3.0% (catastrophic protection)
   c. Time: 6 hour max hold (most rebounds complete within 4-6h)
```

---

## 3. Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| lookback | 30 | Bars for new-low comparison (~1 week) |
| hold_hours | 6 | Maximum position hold time |
| stop_pct | 3.0% | Hard stop loss |
| target_pct | 1.5% | Profit target (same as Wick v4.3) |
| commission | 5 bps | Round-trip cost estimate |

Note: `stop_pct`, `target_pct`, and `hold_hours` are strategy parameters wired to the engine at runtime. Position sizing is handled by the risk manager, not the strategy.

---

## 4. Backtest Results

Script: `research/backtest_new_strategies.py`
Date: 2026-06-09

### BTC/USDT (2018-2026)

```
Trades:        801
Linear sum:    +65.7% (7.8% ann)
Sharpe:        2.72
Max DD:        -12.5%
Win rate:      58%
Avg win:       +0.94%
Avg loss:      -1.13%
Profit factor: 1.18
Exits: stop=65 (8%), target=232 (29%), time=504 (63%)
```

### Walk-Forward (6 splits)

```
⭐ 2019-01→2020-02  sum=+11.8%  sharpe=+4.48
⭐ 2020-02→2021-03  sum= +5.1%  sharpe=+1.86
⭐ 2021-03→2022-03  sum=+24.6%  sharpe=+6.66
   2022-03→2023-04  sum= -2.5%  sharpe=-1.00  ← only negative split
⭐ 2023-04→2024-05  sum= +7.2%  sharpe=+3.48
⭐ 2024-05→2025-05  sum=+10.2%  sharpe=+2.67
→ 5/6 OOS profitable
```

### Multi-Pair OOS (70/30 split, 46 pairs)

```
→ 35/46 OOS profitable (76%), mean Sharpe +2.65

Top pairs:
  PUMP/USDT    Sharpe +25.83
  ENA/USDT     Sharpe +15.32
  RENDER/USDT  Sharpe +13.42
  PEPE/USDT    Sharpe +10.16
  INJ/USDT     Sharpe +9.85
  FIL/USDT     Sharpe +8.70
  JUP/USDT     Sharpe +8.29
  TRX/USDT     Sharpe +7.03
  BTC/USDT     Sharpe +6.78
  ETH/USDT     Sharpe +6.34
```

### Parameter Sensitivity

```
lookback 30, hold 6h, target 1.5%  →  Sharpe 2.72  (best)
lookback 30, hold 8h, target 1.5%  →  Sharpe 2.30
lookback 15, hold 6h, target 1.5%  →  Sharpe 1.79
```

lookback=30 is significantly better than 15/20 — market cares about
"this week's low" being breached. hold=6h > hold=8h — rebounds that
haven't hit target by 6h rarely do. target=1.5% consistently beats
2.0% and 3.0% (same lesson as Wick v4.3).

---

## 5. Known Issues & Risks

### Failure Mode: Sustained Downtrend

In a persistent bear market, every new low is "real" rather than a trap.
The strategy will repeatedly enter on breakdowns that keep breaking down.
This is the same failure mode as Wick — both strategies lose in sustained
downtrends. Running both together amplifies this shared risk.

### Mitigation Ideas (not implemented)

1. **SMA200 filter.** Only take Spring signals when price > SMA(200).
   Cuts ~35% of trades, may improve Sharpe. Needs walk-forward validation.

2. **Consecutive loss cooldown.** After 2 consecutive stop-losses, pause
   for 12 hours. Simple, testable.

3. **Multi-pair diversification.** Running across uncorrelated pairs
   reduces single-pair drawdown risk, same as Wick.

---

## 6. Framework Integration

### Code Location

| Component | Path |
|-----------|------|
| Strategy class | `strategies/spring.py` → `SpringReversal` |
| Signal function | `cryptoquant/strategy/signals.py` → `new_low_bullish()` |
| Backtest engine | `cryptoquant/engine/backtest.py` → `BacktestEngine` |
| Live engine | `cryptoquant/engine/live.py` → `LiveEngine` |

### Backtest Usage

```python
from cryptoquant.engine.backtest import BacktestEngine
from strategies.spring import SpringReversal

strategy = SpringReversal()
engine = BacktestEngine(commission=0.0005, slippage=0.0005)

result = engine.run(
    df,
    strategy,
    symbol="BTC/USDT",
    stop_loss_pct=strategy.params["stop_pct"],
    take_profit_pct=strategy.params["target_pct"],
    max_hold_bars=strategy.params["hold_hours"],  # 1h bars = hours
)
```

### Live Trading

```python
from cryptoquant.engine.live import LiveEngine
from strategies.spring import SpringReversal

strategy = SpringReversal()
engine = LiveEngine(
    broker=broker,
    strategy=strategy,
    cache=cache,
    symbol="BTC/USDT",
    stop_loss_pct=strategy.params["stop_pct"],
    take_profit_pct=strategy.params["target_pct"],
    max_hold_hours=strategy.params["hold_hours"],
)

engine.run(interval=60)
```

### Exit Logic

LiveEngine checks exits in priority order each tick:
1. **Stop loss**: PnL ≤ -stop_pct → exit
2. **Take profit**: PnL ≥ +target_pct → exit
3. **Time exit**: hold_hours exceeded → exit
4. **Signal reverse**: opposite signal → exit

Current price is `df["close"].iloc[-1]` (last bar close), consistent with backtest behavior.

---

*"The market's most predictable moment is when it just lied to everyone."*

— Written 2026-06-09, ~/VibeCoding