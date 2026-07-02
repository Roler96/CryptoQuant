# CryptoQuant Improvement Roadmap

> Updated: 2026-07-02
> Branch: dev
> Based on review of ~7,700 core lines + ~4,500 test lines + 3 research scripts.

---

## Completed

### Phase 1: Research Hygiene
- [x] Cull research files (43 → 3 remaining: `_runner.py`, `backtest_pivot_breakout_atr.py`, `backtest_hurst_trend_filter.py`)
- [x] Out-of-sample testing module (`data/oos.py`, 60 lines)

### Phase 2: Paper Trading Layer
- [x] `PaperBroker` class (`execution/paper_broker.py`, 184 lines — simulated fills, slippage, latency)
- [x] Paper trading config flag (`PaperTradingConfig` in `config.py`, `paper_trading.enabled` in `config.yaml`)
- [x] `PaperTradingResult` dataclass (`engine/types.py:73`)

### Phase 3: Backtest vs Live Divergence
- [x] Unified exit logic (`engine/exit_logic.py`, 80 lines — pure functions, shared by backtest + live)
- [x] Slippage model (`engine/slippage.py`, 44 lines)
- [x] Fill latency simulation (`engine/latency.py`, 31 lines)
- [x] Commission model (`engine/commission.py`, 53 lines)

### Phase 4: Data Flywheel
- [x] `TradeAnalyzer` module (`analysis/trade_analyzer.py`, 100 lines)
- [x] `KellySizer.update_from_trades()` (`risk/sizer.py:87`, called when `adaptive=True`)
- [x] Regime detection (`strategy/regime_switch.py`, `detect_regime()` in `signals.py`)
- [x] Data quality monitoring (`data/quality.py`, 157 lines)

### Phase 5: Dynamic Risk
- [x] ATRSizer is default (`TradingConfig.sizer_method = "atr"`)
- [x] 3-tier drawdown circuit breaker (REDUCE_HALF 10% → REDUCE_QUARTER 15% → HALT 20%)
- [x] Correlation check (`risk/correlation.py`, 55 lines)
- [x] CVaR tail risk (`risk/cvar.py`, 28 lines)

### Phase 6: Reliability Hardening
- [x] `HealthChecker` class (`monitor/health.py`, 91 lines)
- [x] Docker healthcheck (`deploy/healthcheck.py` — state file freshness check)
- [x] `AlertHandler` with rate limiting + dedup (`monitor/alerts.py`, 95 lines)
- [x] `StateManager` backup rotation (5 versions, SHA-256 checksum)
- [x] `MockBroker` for CI (`execution/mock_broker.py`, 122 lines)

### Phase 7: Strategy Decomposition
- [x] Strategy ensemble layer (`strategy/ensemble.py`, 59 lines)
- [x] Regime-conditioned strategy switching (`strategy/regime_switch.py`, 69 lines)

---

## Open Items

### From Original Roadmap

- [ ] **Run 3-month paper trading minimum** — operational task, not code. Collect fill latency, slippage vs size, rejections. Compare paper Sharpe vs backtest Sharpe (target: within 30%).
- [ ] **`validate_ohlcv` strict/fail-fast mode** — `data/quality.py` has `check()`, `detect_gaps()`, `detect_stale()`, `detect_outliers()`, `detect_volume_anomalies()` but no `strict=True` parameter that raises `DataValidationError` on gaps. Add for live trading to prevent trading on stale data.
- [ ] **HTTP `/health` endpoint** — `HealthChecker` exists but no HTTP server exposes it. Docker healthcheck (file-based) is done, but external monitoring (Prometheus, load balancer) needs an HTTP endpoint. Lightweight: stdlib `http.server` + `HealthChecker`.
- [ ] **WickInversion signal decomposition** — `generate_signal()` still does filtering + signal generation in one method. Split into `wick_signal(df)` (raw) + `wick_filter(signal, df)` (filtered) for raw-vs-filtered backtesting.
- [ ] **Verify `update_from_trades()` is called in live engine** — `KellySizer.update_from_trades()` exists (`sizer.py:87`), called when `adaptive=True` (`sizer.py:120`), but `LiveEngine` may not wire the post-exit hook. `live.py:673` calls `risk_manager.record_exit()` — check if this triggers sizer update.
- [ ] **Document the "why" for each strategy filter** — rationale for parameter choices (e.g., WickInversion `vol_gate > 1.0`, Spring BB `[0.12, 0.65)`) should be in docstrings or `docs/research/`.

### Phase 8: Engineering Hardening (New — 2026-07-02)

- [ ] **Split `signals.py`** (3000+ lines, 80 functions) into `strategy/indicators/` package by category (trend, momentum, volatility, volume, price_action, cycle, fractal, utilities). `__init__.py` re-exports for backward compat.
- [ ] **Upgrade pyright `basic` → `strict`** and fix type errors (`pyproject.toml:59`). AGENTS.md claims "strict mode in CI" but config is `basic`.
- [ ] **Pin dependencies with upper bounds** — `ccxt>=4.0.0,<5.0.0` etc. (`pyproject.toml:6-14`). Trading system sensitive to major version breaks.
- [ ] **Fix CI redundant double test run** — merge two pytest steps into one (`ci.yml:38-41`).
- [ ] **Replace CI grep security check with gitleaks** (`ci.yml:49-52`) — current grep misses real secrets, produces false positives.
- [ ] **Include `tests/` in pyright** — currently excluded (`pyproject.toml:58`). Test code type errors hide interface misunderstandings.
- [ ] **Dockerfile non-root user** — add `USER app` directive, currently runs as root.
- [ ] **Fix coverage `exclude_lines`** — remove `pass` from exclusion list (`pyproject.toml:53`), could hide empty function bodies.
- [ ] **Remove unused `hypothesis` dep or add property-based tests** — `hypothesis>=6.0` in dev deps but no `@given` in any test file. Good candidates: `StateManager` serialize/deserialize, `RiskManager` drawdown transitions, `validate_ohlcv`.

---

## What NOT to Do

- Do NOT add a 4th research script.
- Do NOT add machine learning for price prediction.
- Do NOT add more indicators. **You have 80. You use ~4.** The indicator library (`signals.py`) is already overbuilt — it should be split and pruned, not expanded.
- Do NOT optimize the backtest engine speed. (It's vectorized. It's fast enough.)
- Do NOT add a dashboard. (You have logs. Read them.)
- Do NOT split into microservices. (Single-process tick loop is correct for low-latency trading.)

---

> The framework is engineering-mature. The remaining gap is in operational validation (paper trading) and engineering hygiene (type safety, dependency pinning, code organization). Fix the engineering debt before adding features.
