# CryptoQuant Improvement Roadmap

> Based on systematic review of 3,634 core lines + 2,258 test lines + 43 research scripts.
> The framework is engineering-mature but not deployment-ready.

---

## Phase 1: Research Hygiene — Stop Overfitting

The `research/` directory has 43 backtest scripts. This is a massive multiple-comparison problem.

- [ ] **Cull research files to 5 core experiments**
  - Keep: one baseline per strategy (Wick, Spring, BB), one walk-forward validation, one cross-validation
  - Delete or archive: the remaining 38 parameter-sweep files
  - Rationale: 43 research scripts = 38 degrees of freedom spent on historical data. You are not researching, you are p-hacking.

- [ ] **Add out-of-sample lockbox**
  - Reserve 20% of data (e.g., 2024-06 to 2026-06) as a true holdout set
  - Never touch this data until a strategy is frozen for 3+ months
  - Current practice: every research script sees the full 2019-2026 range

- [ ] **Document the "why" for each surviving filter**
  - For WickInversion vol_gate > 1.0: prove it works on BTC 2022-2024 *only* after discovering it
  - For Spring BB [0.12, 0.65): same. The lower bound 0.12 was a post-hoc optimization.

---

## Phase 2: Paper Trading Layer — Close the Demo-to-Deployment Gap

BacktestEngine and LiveEngine share logic but not implementation. The backtest is 627 lines; the live engine is 517 lines. They are two separate systems.

- [ ] **Implement `PaperBroker` class**
  - Inherits from `Broker` interface, but records orders instead of executing
  - Uses real-time market data (same tick as live) with simulated fills
  - Simulates slippage: `fill_price = mid_price * (1 + slippage * random_direction)`
  - Logs latency: `order_submit_ts` vs `order_ack_ts` from exchange

- [ ] **Add paper trading config flag**
  ```yaml
  trading:
    mode: paper  # paper | live
  ```

- [ ] **Run 3-month paper trading minimum**
  - Collect: fill latency, slippage vs size, rejections, partial fills
  - Compare: paper PnL vs backtest PnL for same strategy + same period
  - Target: paper Sharpe within 30% of backtest Sharpe for each strategy

- [ ] **Add `PaperTradingResult` dataclass**
  - Track: `latency_ms`, `fill_deviation_bps`, `rejection_rate`, `partial_fill_rate`
  - Feed this into Phase 4 (adaptive risk)

---

## Phase 3: Fix Backtest vs Live Divergence

Current gap: backtest uses bar high/low for stops; live uses `df["close"].iloc[-1]`.

- [ ] **Unify exit logic**
  - Extract `_check_stop_loss`, `_check_take_profit`, `_check_time_exit` into a shared module
  - `cryptoquant/engine/exit_logic.py` — pure functions, no side effects
  - Both `BacktestEngine` and `LiveEngine` import from this module
  - Input: `position`, `current_bar`, `params` → Output: `(should_exit, reason, exit_price)`

- [ ] **Add slippage model in backtest**
  - Current: fixed `slippage=0.0005` (5bps)
  - Realistic: vol-dependent slippage
    ```python
    slippage = base_slippage * (1 + atr_14 / median_atr_200)
    ```
  - This is the #1 reason paper trading underperforms backtesting

- [ ] **Add fill latency simulation**
  - For market orders in backtest: apply `latency * price_drift` based on bar volatility
  - This closes the gap between "assume instant fill" and reality

- [ ] **Add commission tiers**
  - OKX taker fee is 0.05% for spot, 0.02% for VIP
  - Current hardcoded `0.0005` is wrong for most account sizes

---

## Phase 4: Data Flywheel — Build the Feedback Loop

The system collects trade data but does not use it. This is a dead data problem.

- [ ] **Add `TradeAnalyzer` module**
  - Read `trade_journal_*.jsonl` → compute regime-conditioned stats
  - Output: `spring_above_sma200_sharpe`, `wick_high_vol_sharpe`, etc.
  - Feed this into strategy parameter updates

- [ ] **Make `KellySizer` and `RiskManager` adaptive**
  - `KellySizer.update_from_trades()` exists but is never called in live engine
  - Add post-trade hook: `risk_manager.update_from_journal(journal)` after each exit
  - `RiskManager` should adjust `max_daily_trades` based on recent win rate decay

- [ ] **Add regime detection**
  - Current: SMA200 + BB %B are used as filters
  - Better: compute a rolling `regime_score` from volatility, trend, and volume
  - Use this to dynamically switch strategies or disable trading
  - Store regime in `Trade.regime` dict (already exists in schema, unused)

- [ ] **Add live data quality monitoring**
  - `validate_ohlcv()` runs on fetch but does not log anomalies
  - Add: `data_quality_journal` — timestamp, gap_count, missing_columns, etc.
  - Alert when `gap_count > 3` in a 24h window (data quality degradation)

---

## Phase 5: Risk — Make It Dynamic, Not Static

- [ ] **Add volatility-scaled position sizing**
  - `ATRSizer` exists but is not the default
  - Make it the default: `position_size = balance * (max_risk_pct / (atr_pct * multiplier))`
  - Clamp: `min_order <= size <= max_order`

- [ ] **Add drawdown circuit breaker with graduated response**
  - Current: emergency stop at 20% DD, cooldown 60min, then half position
  - Better: 3 tiers:
    - 10% DD: reduce position size by 50%
    - 15% DD: reduce by 75%
    - 20% DD: emergency stop (current behavior)

- [ ] **Add correlation check for multi-symbol trading**
  - Current `max_positions=3` does not check if symbols are correlated
  - Add: `correlation_matrix` from 24h returns → reject entry if `corr > 0.8` with existing position
  - This prevents "3 BTC positions in different timeframes" risk

- [ ] **Add fat-tail loss scenario**
  - Current `max_per_trade_risk_pct=2.0` assumes normal volatility
  - Add: `tail_risk_limit` based on historical CVaR_95 of the strategy
  - If CVaR_95 > 3% for this strategy, reduce position size by `CVaR_95 / 2.0`

---

## Phase 6: Engineering — Reliability Hardening

- [ ] **Add health check endpoint**
  - `GET /health` or `healthcheck()` in `LiveEngine`
  - Checks: broker connected, data cache warm, risk manager not in emergency, state save < 5min old

- [ ] **Add log rotation + alerting**
  - `loguru` has rotation but no alerting
  - Add: `error_count_24h` threshold → alert if > 10 exchange errors or > 3 signal errors
  - Use `monitor/reporter.py` for this (currently only does daily/weekly summaries)

- [ ] **Add `StateManager` backup**
  - Current: atomic write, one file per strategy-symbol
  - Better: keep last 5 versions, rotate on save
  - `state_{strategy}_{symbol}_v{timestamp}.json`

- [ ] **Add `Broker` mock for CI**
  - Tests currently use `ccxt` in integration tests
  - Add `MockBroker` that implements `Broker` interface with controlled latency/failure
  - Run live engine tests in CI without real API keys

- [ ] **Add `validate_ohlcv` fail-fast mode**
  - Current: warns on gaps but continues
  - Add: `strict=True` mode (for live) that raises `DataValidationError` on any gap
  - Prevents trading on stale data

---

## Phase 7: Strategy — Decompose into Signals

- [ ] **Extract `WickInversion` into a pure signal function**
  - Current: `generate_signal` does filtering + signal generation
  - Better: `wick_signal(df)` returns raw signal, `wick_filter(signal, df)` returns filtered
  - This allows backtesting "raw vs filtered" side-by-side

- [ ] **Add strategy ensemble layer**
  - Current: 3 strategies run independently
  - Better: `EnsembleStrategy` that takes `signal_a * weight_a + signal_b * weight_b`
  - Weights optimized via walk-forward on OOS data
  - This reduces single-strategy tail risk

- [ ] **Add regime-conditioned strategy switching**
  - High vol + uptrend → favor `BBUpperBreakout`
  - Low vol + downtrend → favor `SpringReversal` (if any)
  - Flat → no trade
  - This is a 10x more useful optimization than another parameter sweep

---

## Measurement of Success

| Phase | Metric | Target |
|---|---|---|
| 1 | Research files | 43 → 5 |
| 2 | Paper trading duration | 3 months minimum |
| 2 | Paper vs backtest Sharpe gap | < 30% |
| 3 | Backtest/live logic divergence | 0 (shared module) |
| 4 | Trade journal → strategy feedback | Automatic weekly |
| 5 | Risk params | 100% adaptive (no hardcoded limits) |
| 6 | CI tests | 100% without API keys |
| 7 | Strategy ensemble | 1 ensemble running in paper |

---

## What NOT to Do

- Do NOT add a 44th research script.
- Do NOT add machine learning for price prediction. (Your 3,634 lines are not ready for this.)
- Do NOT add more indicators. (You have 12. You use 4.)
- Do NOT optimize the backtest engine speed. (It's vectorized. It's fast enough.)
- Do NOT add a dashboard. (You have logs. Read them.)

---

> 3,634 lines of core code. 43 research scripts. 1 deployment gap.
> The gap is not in the backtest. The gap is in the march of nines.
> Fix the data flywheel first. Everything else follows.

I'm sorry.
