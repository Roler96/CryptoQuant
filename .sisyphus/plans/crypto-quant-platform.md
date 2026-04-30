# CryptoQuant - 加密货币量化交易平台

## TL;DR

> **Quick Summary**: 构建完整的加密货币量化交易平台，包含回测和实盘交易功能，使用 Python + Backtrader + ccxt，目标交易所 OKX，实现 CTA 趋势跟踪和统计套利两种策略。

> **Deliverables**:
> - 数据管理模块（历史数据获取、存储、验证）
> - 回测引擎（基于 Backtrader）
> - CTA 趋势跟踪策略
> - 统计套利策略
> - 基础风控系统（止损、仓位控制）
> - CLI 命令行界面
> - 模拟盘测试功能
> - 实盘交易模块（OKX API 集成）

> **Estimated Effort**: Large（约 4-5 周渐进开发）
> **Parallel Execution**: YES - 3 Waves (Phase 1-3)
> **Critical Path**: Task 1(数据) → Task 5(策略) → Task 7(回测) → Task 9(风控) → Task 11(模拟盘) → Task 13(实盘)

---

## Context

### Original Request
用户希望构建一个完整的加密货币量化交易平台，支持回测和实盘交易，目标交易所为 OKX，实现 CTA（趋势跟踪）和统计套利两种策略类型。

### Interview Summary
**Key Discussions**:
- **项目定位**: 完整平台（回测 + 实盘），不是学习项目
- **技术栈**: Python + Backtrader（回测框架）+ ccxt（OKX API）
- **策略类型**: CTA（趋势跟踪）+ 统计套利
- **交易所**: OKX（单一交易所，MVP 专注）
- **数据源**: OKX 官方 API（实时 + 历史）
- **界面**: 纯 CLI（无 Web UI）
- **部署**: 本地开发环境
- **开发优先级**: 回测优先（验证策略效果后进入实盘）
- **回测框架**: Backtrader（成熟、文档丰富）
- **初期资金**: OKX 模拟盘测试（零风险验证）
- **风控需求**: 基础风控（止损 + 仓位控制）
- **测试策略**: 测试后补（先完成功能，后续补充测试）
- **API Key 安全**: 环境变量配置（不存储在代码或配置文件）
- **开发方式**: 渐进开发（MVP 先行）

**Research Findings**:
- librarian agents 失败（模型配置问题），但核心决策清晰
- Python 量化交易生态成熟：ccxt（交易所抽象）、backtrader（回测）、pandas（数据处理）
- OKX V5 API 文档完善，ccxt 提供统一接口层

### Metis Review
**Identified Gaps** (addressed):
- **交易频率未确认**: 默认为日内交易（非高频），1小时bar数据粒度
- **资产类型未确认**: 默认现货（spot），更安全，期货可作为后续扩展
- **数据存储量未确认**: 默认1年历史数据，约 8,760 小时 bars
- **失败恢复策略**: 必须实现 Kill Switch + 状态持久化
- **监控报警**: CLI 输出 + 日志文件（符合用户选择的纯 CLI）
- **数据粒度**: 默认 1 小时 bar（平衡存储效率和策略精度）

**Guardrails Applied**:
- **MUST NOT**: 存储 API Key 在代码或 git
- **MUST NOT**: 未验证的策略直接实盘
- **MUST NOT**: 绕过风控系统的交易
- **MUST NOT**: 添加 Web UI（用户明确选择 CLI）
- **MUST NOT**: 多交易所支持（MVP 专注 OKX）
- **MUST NOT**: ML/AI 策略（MVP 专注传统策略）
- **MUST**: 实现 Kill Switch
- **MUST**: 模拟盘验证后才能实盘
- **MUST**: 所有交易决策记录审计日志
- **MUST**: 状态持久化（崩溃恢复）

---

## Work Objectives

### Core Objective
构建一个模块化的加密货币量化交易平台，从数据获取、策略研发、回测验证、到模拟盘测试、最终实盘执行的全流程系统。

### Concrete Deliverables
1. **数据管理模块**: OKX API 集成，历史数据下载和存储（Parquet 格式），数据完整性验证
2. **回测引擎**: 基于 Backtrader，支持 CTA 和统计套利策略回测，输出性能指标
3. **CTA 趋势跟踪策略**: 均线交叉、突破策略实现
4. **统计套利策略**: 配对交易、均值回归实现
5. **风控系统**: 止损、仓位限制、杠杆控制
6. **CLI 界面**: 命令行操作（回测、模拟盘、实盘、状态查看）
7. **模拟盘测试**: OKX demo trading 集成
8. **实盘交易模块**: OKX live trading，订单执行，仓位管理
9. **Kill Switch**: 紧急平仓机制
10. **日志和审计**: 结构化日志，交易决策记录

### Definition of Done
- [ ] 数据管理模块可下载并验证 OKX 历史数据（BTC/USDT, ETH/USDT）
- [ ] CTA 策略在 Backtrader 中回测通过（Sharpe > 1.0, MaxDD < 20%）
- [ ] 统计套利策略回测通过（Sharpe > 0.5, MaxDD < 15%）
- [ ] 风控系统正确执行止损和仓位限制
- [ ] CLI 可运行回测和查看状态
- [ ] 模拟盘运行 7 天无异常，所有订单正确执行
- [ ] Kill Switch 测试通过（所有仓位 5 秒内平仓）
- [ ] 实盘模块集成 OKX API，支持手动确认首次交易
- [ ] 所有 API Key 通过环境变量配置，不在代码中出现

### Must Have
- 数据获取和存储（OKX API + Parquet）
- Backtrader 回测引擎
- CTA 策略实现（至少一个：均线交叉）
- 基础风控（止损、仓位限制）
- CLI 操作界面
- 模拟盘测试功能
- Kill Switch 机制
- 审计日志

### Must NOT Have (Guardrails)
- **Web UI 或 Dashboard**（用户明确选择纯 CLI）
- **多交易所支持**（MVP 专注 OKX，Binance/Bybit 等后续扩展）
- **ML/AI 策略**（LSTM、强化学习等，MVP 专注传统策略）
- **实时 WebSocket 数据流**（MVP 使用定时轮询，足够日内交易）
- **高级订单类型**（Iceberg、TWAP、VWAP，MVP 使用标准订单）
- **策略优化工具**（遗传算法、网格搜索，后续扩展）
- **多策略并行**（MVP 单策略运行，并发策略后续扩展）
- **API Key 硬编码**（必须使用环境变量）
- **绕过风控的交易**（所有交易必须经过风控检查）
- **未验证策略实盘**（必须经过回测 + 模拟盘验证）

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.
> Acceptance criteria requiring "user manually tests/confirms" are FORBIDDEN.

### Test Decision
- **Infrastructure exists**: NO（新项目）
- **Automated tests**: Tests-after（先完成功能，后续补充）
- **Framework**: pytest（Python 标准测试框架）
- **Test coverage**: 核心模块单元测试，集成测试手动执行

### QA Policy
Every task MUST include agent-executed QA scenarios (see TODO template below).
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Data Module**: Use Bash (Python script) - Download data, validate integrity, check storage format
- **Backtest Module**: Use Bash (pytest) - Run backtest, assert performance metrics, check output logs
- **CLI Interface**: Use interactive_bash (tmux) - Run commands, validate output, test error handling
- **API Integration**: Use Bash (curl + Python) - Test API connection, validate credentials, check rate limits
- **Live Trading**: Use Bash (Python script) - Paper trading test, kill switch test, risk limit test

---

## Execution Strategy

### Parallel Execution Waves

> Maximize throughput by grouping independent tasks into parallel waves.
> Target: 5-8 tasks per wave. Fewer than 3 per wave = under-splitting.

```
Wave 1 (Phase 1 MVP - Foundation + Data + Strategy):
├── Task 1: Project scaffolding + config setup [quick]
├── Task 2: Data Manager - OKX API client [unspecified-high]
├── Task 3: Data Manager - Historical data storage (Parquet) [unspecified-high]
├── Task 4: Data Manager - Data validation module [unspecified-high]
├── Task 5: Strategy Module - CTA base framework [deep]
├── Task 6: Strategy Module - CTA trend following implementation [deep]
├── Task 7: Backtest Engine - Backtrader integration [deep]
└── Task 8: Backtest Engine - Performance metrics calculator [unspecified-high]

Wave 2 (Phase 1 MVP - Risk + CLI + Validation):
├── Task 9: Risk Manager - Position sizing module [unspecified-high]
├── Task 10: Risk Manager - Stop-loss implementation [unspecified-high]
├── Task 11: CLI Interface - Command parser and dispatcher [quick]
├── Task 12: CLI Interface - Backtest command [quick]
├── Task 13: CLI Interface - Status and config commands [quick]
├── Task 14: Logging & Audit - Structured logging setup [quick]
├── Task 15: Logging & Audit - Trade audit trail [quick]
└── Task 16: Paper Trading - OKX demo integration [unspecified-high]

Wave 3 (Phase 2 Validation + Phase 3 Live Trading):
├── Task 17: Kill Switch - Emergency position closure [deep]
├── Task 18: Paper Trading - Strategy validation runner [unspecified-high]
├── Task 19: Paper Trading - 7-day validation test suite [unspecified-high]
├── Task 20: Strategy Module - Statistical arbitrage base [deep]
├── Task 21: Strategy Module - Pair trading implementation [deep]
├── Task 22: Live Trading - OKX live API client [unspecified-high]
├── Task 23: Live Trading - Order execution manager [unspecified-high]
├── Task 24: Live Trading - Position tracker [unspecified-high]
└── Task 25: Live Trading - Manual confirmation mechanism [quick]

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay
```

### Dependency Matrix

- **1**: - - 2-8, 11-13, 1 (所有模块依赖基础配置)
- **2**: 1 - 3, 4, 7, 16, 22, 2 (数据获取是上游)
- **3**: 2 - 7, 3 (存储依赖获取)
- **4**: 2, 3 - 7, 18, 4 (验证依赖数据)
- **5**: 1 - 6, 7, 5 (策略框架依赖配置)
- **6**: 5, 7 - 18, 6 (策略实现依赖框架和回测验证)
- **7**: 2, 3, 5 - 6, 8, 12, 7 (回测引擎依赖数据和策略)
- **8**: 7 - 12, 8 (指标计算依赖回测)
- **9**: 1 - 10, 23, 9 (风控依赖配置)
- **10**: 9 - 17, 23, 10 (止损依赖仓位控制)
- **11**: 1 - 12, 13, 11 (CLI依赖配置)
- **12**: 7, 8 - 12 (回测命令依赖引擎)
- **13**: 11 - 13 (状态命令依赖CLI框架)
- **14**: 1 - 15, 14 (日志依赖配置)
- **15**: 14 - 23, 15 (审计依赖日志)
- **16**: 2, 9 - 18, 19, 16 (模拟盘依赖数据和风控)
- **17**: 9, 10 - 17 (Kill Switch依赖风控)
- **18**: 6, 16 - 19, 18 (策略验证依赖策略和模拟盘)
- **19**: 18 - F3, 19 (7天测试依赖验证runner)
- **20**: 5 - 21, 7, 20 (统计套利框架依赖策略基类)
- **21**: 20, 7 - 21 (配对交易依赖框架和回测)
- **22**: 1, 14, 15 - 23, 24, 25, 22 (实盘API依赖配置和日志)
- **23**: 22, 9, 10 - 24, 25, 17, 23 (订单执行依赖API和风控)
- **24**: 23 - 24 (仓位跟踪依赖订单)
- **25**: 23 - 25 (手动确认依赖订单)

Critical Path: Task 1 → Task 2 → Task 3 → Task 7 → Task 6 → Task 18 → Task 19 → F3 → F1-F4 → user okay

Parallel Speedup: ~60% faster than sequential
Max Concurrent: 8 (Wave 1)

### Agent Dispatch Summary

- **Wave 1**: **8 tasks**
  - T1 → `quick`, T2-T4 → `unspecified-high`, T5-T6 → `deep`, T7 → `deep`, T8 → `unspecified-high`
- **Wave 2**: **7 tasks**
  - T9-T10 → `unspecified-high`, T11-T13 → `quick`, T14-T15 → `quick`, T16 → `unspecified-high`
- **Wave 3**: **9 tasks**
  - T17 → `deep`, T18-T19 → `unspecified-high`, T20-T21 → `deep`, T22-T24 → `unspecified-high`, T25 → `quick`
- **Wave FINAL**: **4 tasks**
  - F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [ ] 1. Project scaffolding + config setup

  **What to do**:
  - Create project directory structure (data/, strategy/, backtest/, risk/, cli/, live/, logs/, tests/)
  - Set up Python environment with requirements.txt (ccxt, backtrader, pandas, numpy, python-dotenv, structlog, pytest)
  - Create config/ directory with config.yaml template (exchange settings, data settings, backtest parameters, risk parameters)
  - Create .env.example template (OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE)
  - Set up .gitignore (exclude .env, logs/, data/cache/, __pycache__, *.pyc)
  - Create README.md with setup instructions

  **Must NOT do**:
  - Store any API keys or secrets in config files or code
  - Create Web UI components or templates
  - Add multi-exchange configuration

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Standard scaffolding task, no complex logic required
  - **Skills**: []
    - No special skills needed for basic setup

  **Parallelization**:
  - **Can Run In Parallel**: NO (foundation for all other tasks)
  - **Parallel Group**: Wave 1 start
  - **Blocks**: All tasks in Wave 1-3 (depend on project structure)
  - **Blocked By**: None (can start immediately)

  **References**:
  - Python project structure conventions: `src/` vs flat layout
  - .gitignore template for Python projects: exclude `.env`, `__pycache__`, `.pytest_cache`, `logs/`, `data/`

  **Acceptance Criteria**:
  - [ ] Project directory created with all required folders
  - [ ] requirements.txt exists with all dependencies listed
  - [ ] config/config.yaml exists with valid YAML structure
  - [ ] .env.example exists with placeholder variables
  - [ ] .gitignore exists and excludes .env, logs/, data/cache/
  - [ ] README.md exists with setup instructions

  **QA Scenarios**:

  ```
  Scenario: Project structure validation
    Tool: Bash
    Preconditions: Fresh environment
    Steps:
      1. ls -la /home/roler/Code/CryptoQuant
      2. Assert directories exist: data/, strategy/, backtest/, risk/, cli/, live/, logs/, tests/, config/
      3. Assert files exist: requirements.txt, .gitignore, README.md, config/config.yaml, .env.example
      4. cat .gitignore | grep -E "^\.env|^logs/|^data/cache/" 
      5. Assert grep output contains all three patterns
    Expected Result: All directories and files exist, .gitignore correctly configured
    Failure Indicators: Missing directory, missing file, incorrect .gitignore patterns
    Evidence: .sisyphus/evidence/task-01-structure-validation.log

  Scenario: Environment setup validation
    Tool: Bash
    Preconditions: Project structure exists
    Steps:
      1. cd /home/roler/Code/CryptoQuant
      2. python -m venv venv (optional, check if user prefers system Python)
      3. pip install -r requirements.txt
      4. python -c "import ccxt; import backtrader; import pandas; import structlog"
      5. Assert import success (no ImportError)
    Expected Result: All dependencies install successfully, imports work
    Failure Indicators: ImportError, pip install failure, missing package
    Evidence: .sisyphus/evidence/task-01-env-validation.log
  ```

  **Evidence to Capture**:
  - [ ] Directory listing showing all folders
  - [ ] .gitignore content showing correct exclusions
  - [ ] pip install output showing successful installation

  **Commit**: YES (Wave 1 commit)
  - Message: `feat(init): project scaffolding and configuration setup`
  - Files: .gitignore, requirements.txt, README.md, config/config.yaml, .env.example
  - Pre-commit: None (foundation task)

- [ ] 2. Data Manager - OKX API client

  **What to do**:
  - Create data/manager.py with OKX API client wrapper using ccxt
  - Implement OKX exchange initialization (API key, secret, passphrase from environment variables)
  - Add sandbox mode support (OKX demo trading)
  - Implement rate limiting wrapper (max 20 requests/second per OKX docs)
  - Create functions: fetch_ohlcv(), fetch_balance(), fetch_ticker(), fetch_order_book()
  - Add error handling for API failures (connection timeout, invalid credentials, rate limit exceeded)
  - Create data/models.py with data structures (OHLCV candle, ticker, order book)
  - Add retry logic with exponential backoff for transient failures

  **Must NOT do**:
  - Hardcode API keys in any file
  - Implement WebSocket streaming (MVP uses REST polling)
  - Add multi-exchange support (OKX only for MVP)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires careful API integration, error handling, and rate limiting logic
  - **Skills**: []
    - No special skills needed, standard Python API wrapper

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 1 completion, can start with Task 5)
  - **Parallel Group**: Wave 1 (with Tasks 5, 6)
  - **Blocks**: Tasks 3, 4, 7, 16, 22 (depend on API client)
  - **Blocked By**: Task 1 (needs project structure and config)

  **References**:
  - ccxt documentation: https://github.com/ccxt/ccxt/wiki
  - OKX V5 API docs: https://www.okx.com/docs-v5/
  - Rate limiting: OKX allows 20 REST requests per 2 seconds per IP
  - Environment variable access: python-dotenv library

  **Acceptance Criteria**:
  - [ ] data/manager.py exists with OKX client class
  - [ ] API keys loaded from environment variables (OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE)
  - [ ] Sandbox mode configurable (sandbox=True/False)
  - [ ] Rate limiting implemented (max 20 req/s)
  - [ ] fetch_ohlcv() returns list of OHLCV candles
  - [ ] fetch_balance() returns account balance dict
  - [ ] Error handling for: timeout, invalid credentials, rate limit
  - [ ] Retry logic with exponential backoff (max 3 retries)

  **QA Scenarios**:

  ```
  Scenario: API client initialization - sandbox mode
    Tool: Bash (Python script)
    Preconditions: Task 1 completed, .env configured with test keys
    Steps:
      1. Create test script: tests/test_api_client.py
      2. from data.manager import OKXClient
      3. client = OKXClient(sandbox=True)
      4. assert client.exchange.sandbox == True
      5. balance = client.fetch_balance()
      6. assert 'total' in balance
      7. assert balance['total']['USDT'] >= 0
    Expected Result: Client initializes in sandbox mode, balance fetch succeeds
    Failure Indicators: AuthenticationError, NetworkError, sandbox flag not set
    Evidence: .sisyphus/evidence/task-02-sandbox-init.log

  Scenario: Rate limiting test
    Tool: Bash (Python script)
    Preconditions: API client initialized
    Steps:
      1. from data.manager import OKXClient
      2. client = OKXClient(sandbox=True)
      3. Send 30 requests in rapid succession (fetch_ticker('BTC/USDT'))
      4. Measure total time for 30 requests
      5. assert total_time >= 3 seconds (30 req / 20 req/2s = 3s minimum)
      6. Assert no RateLimitError raised
    Expected Result: Rate limiting kicks in, requests throttled correctly
    Failure Indicators: RateLimitError, requests complete in < 3s (rate limit not working)
    Evidence: .sisyphus/evidence/task-02-rate-limit.log

  Scenario: Error handling - invalid credentials
    Tool: Bash (Python script)
    Preconditions: API client code exists
    Steps:
      1. Set OKX_API_KEY = "invalid_key" in test environment
      2. from data.manager import OKXClient
      3. Try client = OKXClient(sandbox=True)
      4. Try balance = client.fetch_balance()
      5. Assert AuthenticationError raised
      6. Assert error message contains "Invalid API key"
    Expected Result: Invalid credentials properly detected and reported
    Failure Indicators: No error raised, incorrect error type
    Evidence: .sisyphus/evidence/task-02-invalid-creds.log
  ```

  **Evidence to Capture**:
  - [ ] Sandbox initialization log showing correct mode
  - [ ] Rate limiting test showing throttling behavior
  - [ ] Error handling test showing correct exception

  **Commit**: YES (Wave 1 partial)
  - Message: `feat(data): OKX API client with rate limiting and error handling`
  - Files: data/manager.py, data/models.py, tests/test_api_client.py
  - Pre-commit: `pytest tests/test_api_client.py`

- [ ] 3. Data Manager - Historical data storage (Parquet)

  **What to do**:
  - Create data/storage.py with Parquet file management
  - Implement save_historical_data() function (OHLCV list → Parquet file)
  - Implement load_historical_data() function (Parquet file → pandas DataFrame)
  - Add metadata tracking (last_update_timestamp, data_source, pair, timeframe)
  - Create data directory structure: data/historical/{pair}_{timeframe}.parquet
  - Implement incremental update logic (append new data to existing Parquet)
  - Add data compression (Parquet snappy compression for efficiency)
  - Create metadata.json in data/historical/ to track all files

  **Must NOT do**:
  - Store data in CSV or JSON (use Parquet for efficiency)
  - Store real-time streaming data (MVP uses batch updates)
  - Implement data versioning (MVP focuses on latest data)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires understanding of Parquet format, pandas DataFrame, and incremental updates
  - **Skills**: []
    - No special skills needed, standard data storage

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 2 completion)
  - **Parallel Group**: Wave 1 (with Tasks 4, 5, 6)
  - **Blocks**: Tasks 7, 18 (depend on data storage)
  - **Blocked By**: Task 2 (needs API client for fetching data)

  **References**:
  - Pandas Parquet documentation: https://pandas.pydata.org/docs/reference/io.html#parquet
  - PyArrow Parquet format: efficient columnar storage for time-series data
  - Data directory structure: data/historical/btc_usdt_1h.parquet
  - Metadata tracking: JSON file with last update timestamps

  **Acceptance Criteria**:
  - [ ] data/storage.py exists with Parquet management functions
  - [ ] save_historical_data() creates Parquet file in data/historical/
  - [ ] load_historical_data() returns pandas DataFrame with columns: timestamp, open, high, low, close, volume
  - [ ] Incremental update logic works (append new bars to existing file)
  - [ ] Metadata file tracks all historical data files
  - [ ] Parquet compression enabled (snappy)
  - [ ] Data path format: data/historical/{pair}_{timeframe}.parquet

  **QA Scenarios**:

  ```
  Scenario: Historical data download and storage
    Tool: Bash (Python script)
    Preconditions: Task 2 completed, OKX API client working
    Steps:
      1. from data.manager import OKXClient
      2. from data.storage import save_historical_data
      3. client = OKXClient(sandbox=True)
      4. candles = client.fetch_ohlcv('BTC/USDT', '1h', days=30)
      5. save_historical_data('BTC/USDT', '1h', candles)
      6. assert os.path.exists('data/historical/btc_usdt_1h.parquet')
      7. df = load_historical_data('BTC/USDT', '1h')
      8. assert len(df) == 30 * 24 (720 bars for 30 days)
      9. assert df.columns == ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    Expected Result: Data downloaded and stored in Parquet format, loadable as DataFrame
    Failure Indicators: FileNotFoundError, incorrect row count, missing columns
    Evidence: .sisyphus/evidence/task-03-data-storage.log

  Scenario: Incremental data update
    Tool: Bash (Python script)
    Preconditions: Existing BTC/USDT Parquet file with 30 days data
    Steps:
      1. Get last timestamp from existing data: df['timestamp'].max()
      2. Fetch new data since last timestamp (client.fetch_ohlcv since=last_timestamp)
      3. save_historical_data('BTC/USDT', '1h', new_candles, append=True)
      4. df_updated = load_historical_data('BTC/USDT', '1h')
      5. assert len(df_updated) == original_len + new_candles_count
      6. assert no duplicate timestamps
      7. assert timestamps are sorted ascending
    Expected Result: New data appended correctly, no duplicates, sorted order
    Failure Indicators: Duplicates found, timestamps not sorted, wrong row count
    Evidence: .sisyphus/evidence/task-03-incremental-update.log

  Scenario: Metadata tracking
    Tool: Bash
    Preconditions: Multiple historical data files exist
    Steps:
      1. cat data/historical/metadata.json
      2. Assert JSON contains entries for each pair
      3. Assert each entry has: pair, timeframe, last_update, rows_count, file_path
      4. Assert last_update timestamps are recent (within 1 day of test)
    Expected Result: Metadata correctly tracks all historical data files
    Failure Indicators: Missing metadata file, missing entry, incorrect last_update
    Evidence: .sisyphus/evidence/task-03-metadata.log
  ```

  **Evidence to Capture**:
  - [ ] Parquet file created and validated
  - [ ] DataFrame loaded with correct structure
  - [ ] Metadata file content showing tracking

  **Commit**: YES (Wave 1 partial)
  - Message: `feat(data): historical data storage with Parquet format`
  - Files: data/storage.py, tests/test_data_storage.py
  - Pre-commit: `pytest tests/test_data_storage.py`

- [ ] 4. Data Manager - Data validation module

  **What to do**:
  - Create data/validation.py with data integrity checks
  - Implement validate_ohlcv_data() function: check for missing timestamps, price anomalies, volume validation
  - Add check_missing_timestamps() - detect gaps in time-series (no missing hourly bars)
  - Add check_price_anomalies() - detect unrealistic price jumps (e.g., > 20% in 1 hour)
  - Add check_volume_validation() - ensure volume >= 0, no negative values
  - Implement validate_data_file() - validate entire Parquet file before using in backtest
  - Create validation report with: total_rows, missing_timestamps, anomalies_found, validation_status
  - Add automatic repair for minor issues (fill missing timestamps with NaN, flag anomalies)

  **Must NOT do**:
  - Auto-repair major issues without user notification (data corruption, large gaps)
  - Validate real-time streaming data (MVP validates batch data only)
  - Implement machine learning anomaly detection (use simple threshold-based checks)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires careful data integrity checks and edge case handling
  - **Skills**: []
    - No special skills needed, standard data validation

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 3, 5, 6)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 7, 18 (backtest needs validated data)
  - **Blocked By**: Tasks 2, 3 (needs API client and storage)

  **References**:
  - Time-series validation patterns: check for missing timestamps, continuity
  - Price anomaly thresholds: realistic bounds for crypto volatility
  - Volume validation: ensure non-negative values, detect zero-volume periods

  **Acceptance Criteria**:
  - [ ] data/validation.py exists with validation functions
  - [ ] validate_ohlcv_data() checks: missing timestamps, price anomalies, volume
  - [ ] check_missing_timestamps() detects gaps > 1 hour
  - [ ] check_price_anomalies() flags > 20% price changes in single bar
  - [ ] check_volume_validation() ensures volume >= 0
  - [ ] validate_data_file() returns validation report dict
  - [ ] Validation report includes: status (PASS/WARN/FAIL), issues list

  **QA Scenarios**:

  ```
  Scenario: Clean data validation
    Tool: Bash (Python script)
    Preconditions: Valid historical data file (no gaps, no anomalies)
    Steps:
      1. from data.validation import validate_data_file
      2. report = validate_data_file('data/historical/btc_usdt_1h.parquet')
      3. assert report['status'] == 'PASS'
      4. assert report['missing_timestamps'] == 0
      5. assert report['price_anomalies'] == 0
      6. assert report['volume_issues'] == 0
    Expected Result: Clean data passes all validation checks
    Failure Indicators: Validation status != PASS, unexpected issues found
    Evidence: .sisyphus/evidence/task-04-clean-validation.log

  Scenario: Missing timestamp detection
    Tool: Bash (Python script)
    Preconditions: Corrupted data file with missing bars
    Steps:
      1. Create test data with gap (remove hour 10-12 on day 5)
      2. from data.validation import check_missing_timestamps
      3. missing = check_missing_timestamps(corrupted_data)
      4. assert len(missing) == 2 (2 missing hours)
      5. assert missing timestamps are between hour 10 and 12
      6. report = validate_data_file(corrupted_file)
      7. assert report['status'] == 'WARN' or 'FAIL'
    Expected Result: Missing timestamps detected correctly
    Failure Indicators: Missing timestamps not detected, wrong count
    Evidence: .sisyphus/evidence/task-04-missing-ts.log

  Scenario: Price anomaly detection
    Tool: Bash (Python script)
    Preconditions: Data with unrealistic price jump (50% in 1 hour)
    Steps:
      1. Create test data with price jump from 40000 to 60000 in single bar
      2. from data.validation import check_price_anomalies
      3. anomalies = check_price_anomalies(test_data, threshold=0.2)
      4. assert len(anomalies) == 1
      5. assert anomalies[0]['change_pct'] == 50% (60000/40000 - 1)
      6. assert anomalies[0]['timestamp'] matches the jump bar
    Expected Result: Unrealistic price jump detected
    Failure Indicators: Anomaly not detected, wrong threshold calculation
    Evidence: .sisyphus/evidence/task-04-price-anomaly.log
  ```

  **Evidence to Capture**:
  - [ ] Validation report for clean data
  - [ ] Missing timestamp detection output
  - [ ] Price anomaly detection output

  **Commit**: YES (Wave 1 partial)
  - Message: `feat(data): data validation module with integrity checks`
  - Files: data/validation.py, tests/test_data_validation.py
  - Pre-commit: `pytest tests/test_data_validation.py`

- [ ] 5. Strategy Module - CTA base framework

  **What to do**:
  - Create strategy/base.py with abstract StrategyBase class
  - Define strategy interface: initialize(), generate_signal(), on_bar(), on_trade()
  - Create strategy context: access to data, risk manager, logger
  - Define signal types: LONG, SHORT, CLOSE_LONG, CLOSE_SHORT, HOLD
  - Create strategy/cta/__init__.py for CTA strategy namespace
  - Implement common CTA helpers: calculate_ma(), calculate_rsi(), detect_breakout()
  - Add strategy parameters validation (MA periods, thresholds, etc.)
  - Create strategy state management: track positions, signals history

  **Must NOT do**:
  - Execute trades directly from strategy (strategy only generates signals)
  - Implement ML-based signal generation (MVP uses traditional indicators)
  - Add multi-strategy orchestration (MVP runs single strategy at a time)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Requires designing abstract framework, careful interface design for extensibility
  - **Skills**: []
    - No special skills needed, standard Python OOP

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 2, 3, 4)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 6, 7 (strategy implementation and backtest depend on framework)
  - **Blocked By**: Task 1 (needs project structure)

  **References**:
  - Backtrader Strategy class: https://www.backtrader.com/docu/strategy.html
  - Strategy interface design: signal generation vs execution separation
  - CTA strategy patterns: moving averages, RSI, breakout detection

  **Acceptance Criteria**:
  - [ ] strategy/base.py exists with StrategyBase class
  - [ ] StrategyBase has abstract methods: initialize(), generate_signal(), on_bar()
  - [ ] Signal types defined: LONG, SHORT, CLOSE_LONG, CLOSE_SHORT, HOLD
  - [ ] Strategy context provides: data access, risk manager, logger
  - [ ] strategy/cta/__init__.py created with CTA namespace
  - [ ] Common helpers implemented: calculate_ma(), calculate_rsi(), detect_breakout()
  - [ ] Strategy parameters validation (MA periods >= 2, RSI period >= 5)

  **QA Scenarios**:

  ```
  Scenario: Strategy base class instantiation
    Tool: Bash (Python script)
    Preconditions: Task 1 completed, strategy/base.py exists
    Steps:
      1. from strategy.base import StrategyBase, SignalType
      2. Create concrete test strategy: class TestStrategy(StrategyBase)
      3. Implement required methods: initialize(), generate_signal(), on_bar()
      4. strategy = TestStrategy(params={'ma_period': 20})
      5. assert strategy.params['ma_period'] == 20
      6. assert hasattr(strategy, 'context')
      7. assert hasattr(strategy, 'logger')
      8. assert SignalType.LONG == 'LONG'
    Expected Result: Strategy base class works, concrete implementation possible
    Failure Indicators: Abstract method not enforced, missing context/logger
    Evidence: .sisyphus/evidence/task-05-strategy-base.log

  Scenario: CTA helper functions
    Tool: Bash (Python script)
    Preconditions: strategy/cta/__init__.py exists
    Steps:
      1. from strategy.cta import calculate_ma, calculate_rsi, detect_breakout
      2. Create test data: prices = [100, 102, 105, 103, 108, 110, 112]
      3. ma = calculate_ma(prices, period=3)
      4. assert len(ma) == len(prices) - 2 (first 2 bars no MA)
      5. assert ma[-1] == (110 + 112 + 108) / 3 (correct calculation)
      6. rsi = calculate_rsi(prices, period=5)
      7. assert rsi is not None (RSI calculated)
      8. assert 0 <= rsi <= 100 (RSI bounds)
      9. breakout = detect_breakout(prices, threshold=0.05)
      10. assert breakout in [True, False] (boolean result)
    Expected Result: CTA helper functions calculate correctly
    Failure Indicators: Incorrect MA calculation, RSI out of bounds, non-boolean breakout
    Evidence: .sisyphus/evidence/task-05-cta-helpers.log

  Scenario: Strategy parameters validation
    Tool: Bash (Python script)
    Preconditions: Strategy base class with validation
    Steps:
      1. from strategy.base import StrategyBase
      2. Try creating strategy with invalid params: {'ma_period': 1}
      3. Assert ValueError raised ("MA period must be >= 2")
      4. Try creating strategy with valid params: {'ma_period': 20, 'rsi_period': 14}
      5. Assert strategy created successfully
      6. Assert strategy.params == {'ma_period': 20, 'rsi_period': 14}
    Expected Result: Invalid parameters rejected, valid parameters accepted
    Failure Indicators: Invalid params not rejected, valid params not accepted
    Evidence: .sisyphus/evidence/task-05-param-validation.log
  ```

  **Evidence to Capture**:
  - [ ] Strategy base class instantiation output
  - [ ] CTA helper functions calculation results
  - [ ] Parameter validation success/failure logs

  **Commit**: YES (Wave 1 partial)
  - Message: `feat(strategy): CTA strategy base framework and helper functions`
  - Files: strategy/base.py, strategy/cta/__init__.py, tests/test_strategy_base.py
  - Pre-commit: `pytest tests/test_strategy_base.py`

- [ ] 6. Strategy Module - CTA trend following implementation

  **What to do**:
  - Create strategy/cta/trend_following.py with TrendFollowingStrategy class
  - Implement moving average crossover strategy (fast MA vs slow MA)
  - Add signal generation logic: LONG when fast MA crosses above slow MA, SHORT when crosses below
  - Implement RSI filter: only signal if RSI not in extreme zone (> 70 or < 30)
  - Add breakout strategy as alternative: LONG on upper breakout, SHORT on lower breakout
  - Create strategy parameters: fast_period (default 10), slow_period (default 20), rsi_period (default 14)
  - Add signal strength calculation (crossover magnitude)
  - Implement position sizing suggestion based on signal strength

  **Must NOT do**:
  - Execute trades directly (strategy returns signals, execution module handles trades)
  - Add ML-based trend prediction (MVP uses traditional MA crossover)
  - Implement multiple timeframe analysis (MVP uses single timeframe)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Requires understanding of CTA strategy logic, careful signal generation
  - **Skills**: []
    - No special skills needed, standard strategy implementation

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 7)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 18, 7 (backtest and paper trading need concrete strategy)
  - **Blocked By**: Task 5 (needs strategy framework)

  **References**:
  - Backtrader strategy example: https://www.backtrader.com/docu/samples/sma/sma.html
  - MA crossover strategy: buy when fast MA crosses above slow MA
  - RSI filter: avoid signals in overbought/oversold zones
  - Strategy parameters: fast_period, slow_period, rsi_period

  **Acceptance Criteria**:
  - [ ] strategy/cta/trend_following.py exists with TrendFollowingStrategy class
  - [ ] Strategy inherits from StrategyBase
  - [ ] MA crossover signal generation implemented (LONG/SHORT on crossover)
  - [ ] RSI filter implemented (no signal when RSI > 70 or < 30)
  - [ ] Breakout strategy implemented as alternative mode
  - [ ] Strategy parameters configurable: fast_period, slow_period, rsi_period
  - [ ] Signal strength calculated (crossover magnitude)
  - [ ] Position sizing suggestion returned with signal

  **QA Scenarios**:

  ```
  Scenario: MA crossover LONG signal
    Tool: Bash (Python script)
    Preconditions: TrendFollowingStrategy implemented
    Steps:
      1. Create test data: prices trending up (fast MA crosses above slow MA at bar 10)
      2. from strategy.cta.trend_following import TrendFollowingStrategy
      3. strategy = TrendFollowingStrategy(params={'fast_period': 5, 'slow_period': 10, 'rsi_period': 14})
      4. strategy.initialize()
      5. Feed test data bar by bar: strategy.on_bar(bar)
      6. At bar 10 (crossover), get signal = strategy.generate_signal()
      7. assert signal.type == 'LONG'
      8. assert signal.strength > 0 (positive strength for bullish crossover)
    Expected Result: LONG signal generated on bullish MA crossover
    Failure Indicators: No signal, wrong signal type, negative strength
    Evidence: .sisyphus/evidence/task-06-ma-crossover-long.log

  Scenario: RSI filter blocks signal
    Tool: Bash (Python script)
    Preconditions: TrendFollowingStrategy with RSI filter
    Steps:
      1. Create test data: MA crossover happens but RSI > 70 (overbought)
      2. from strategy.cta.trend_following import TrendFollowingStrategy
      3. strategy = TrendFollowingStrategy(params={'rsi_upper': 70, 'rsi_lower': 30})
      4. Feed data with crossover at bar 10, RSI = 75
      5. signal = strategy.generate_signal()
      6. assert signal.type == 'HOLD' (RSI filter blocks signal)
      7. assert signal.reason contains "RSI overbought"
    Expected Result: RSI filter blocks signal in overbought zone
    Failure Indicators: LONG signal generated despite RSI > 70, no filter reason
    Evidence: .sisyphus/evidence/task-06-rsi-filter.log

  Scenario: Breakout strategy SHORT signal
    Tool: Bash (Python script)
    Preconditions: Breakout mode implemented
    Steps:
      1. Create test data: price breaks below lower threshold (5% drop)
      2. from strategy.cta.trend_following import TrendFollowingStrategy
      3. strategy = TrendFollowingStrategy(params={'mode': 'breakout', 'threshold': 0.05})
      4. strategy.initialize()
      5. Feed data with breakout at bar 5
      6. signal = strategy.generate_signal()
      7. assert signal.type == 'SHORT'
      8. assert signal.strength based on breakout magnitude
    Expected Result: SHORT signal on downside breakout
    Failure Indicators: No signal, wrong signal type, incorrect strength
    Evidence: .sisyphus/evidence/task-06-breakout-short.log
  ```

  **Evidence to Capture**:
  - [ ] MA crossover LONG signal output
  - [ ] RSI filter blocking signal output
  - [ ] Breakout SHORT signal output

  **Commit**: YES (Wave 1 partial)
  - Message: `feat(strategy): CTA trend following strategy with MA crossover and RSI filter`
  - Files: strategy/cta/trend_following.py, tests/test_trend_strategy.py
  - Pre-commit: `pytest tests/test_trend_strategy.py`

- [ ] 7. Backtest Engine - Backtrader integration

  **What to do**:
  - Create backtest/engine.py with BacktestEngine class
  - Integrate Backtrader framework: Cerebro engine, data feed, strategy loader
  - Implement load_strategy() function: load strategy class by name ('cta', 'stat_arb')
  - Create custom data feed from Parquet files (PandasData extension)
  - Add backtest configuration: initial_cash, commission, slippage
  - Implement run_backtest() function: execute strategy on historical data
  - Add result collection: trades list, equity curve, final portfolio value
  - Create backtest visualization: equity curve plot (matplotlib)

  **Must NOT do**:
  - Run live trading from backtest engine (backtest only uses historical data)
  - Modify strategy logic during backtest (strategy runs as designed)
  - Implement multi-strategy backtest (MVP runs single strategy per backtest)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Requires understanding Backtrader framework, custom data feed, and result processing
  - **Skills**: []
    - No special skills needed, Backtrader documentation sufficient

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 6)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 8, 12, 18 (metrics calculation, CLI backtest command, paper trading validation)
  - **Blocked By**: Tasks 2, 3, 5 (needs data, storage, strategy framework)

  **References**:
  - Backtrader quickstart: https://www.backtrader.com/docu/quickstart/quickstart.html
  - PandasData feed: https://www.backtrader.com/docu/pandas/pandas.html
  - Backtest configuration: initial_cash, commission, slippage settings
  - Result analysis: trades list, equity curve

  **Acceptance Criteria**:
  - [ ] backtest/engine.py exists with BacktestEngine class
  - [ ] BacktestEngine integrates Backtrader Cerebro
  - [ ] load_strategy('cta') returns TrendFollowingStrategy instance
  - [ ] Custom PandasData feed reads from Parquet files
  - [ ] Backtest config: initial_cash=10000, commission=0.001, slippage=0.0005
  - [ ] run_backtest() executes strategy on historical data
  - [ ] Result includes: trades list, equity curve, final_value
  - [ ] Equity curve visualization created (PNG plot)

  **QA Scenarios**:

  ```
  Scenario: Backtest engine initialization
    Tool: Bash (Python script)
    Preconditions: BacktestEngine code exists, historical data available
    Steps:
      1. from backtest.engine import BacktestEngine
      2. engine = BacktestEngine(config={'initial_cash': 10000, 'commission': 0.001})
      3. assert engine.cerebro is not None (Backtrader Cerebro initialized)
      4. assert engine.initial_cash == 10000
      5. assert engine.commission == 0.001
      6. strategy = engine.load_strategy('cta')
      7. assert strategy.__class__.__name__ == 'TrendFollowingStrategy'
    Expected Result: Backtest engine initializes correctly, strategy loaded
    Failure Indicators: Cerebro not initialized, strategy not loaded, wrong config
    Evidence: .sisyphus/evidence/task-07-backtest-init.log

  Scenario: Run backtest on historical data
    Tool: Bash (Python script)
    Preconditions: Historical data exists (BTC/USDT 30 days)
    Steps:
      1. from backtest.engine import BacktestEngine
      2. engine = BacktestEngine()
      3. result = engine.run_backtest(strategy='cta', pair='BTC/USDT', timeframe='1h', days=30)
      4. assert 'trades' in result (trades list generated)
      5. assert 'equity_curve' in result (equity curve generated)
      6. assert 'final_value' in result (final portfolio value)
      7. assert len(result['trades']) > 0 (at least some trades executed)
      8. assert result['final_value'] > 0 (positive portfolio value)
      9. assert os.path.exists('logs/backtest_equity_curve.png') (plot created)
    Expected Result: Backtest runs successfully, trades executed, plot created
    Failure Indicators: No trades, no equity curve, final_value = 0, missing plot
    Evidence: .sisyphus/evidence/task-07-backtest-run.log

  Scenario: Custom PandasData feed
    Tool: Bash (Python script)
    Preconditions: Parquet data file exists
    Steps:
      1. from backtest.engine import BacktestEngine
      2. from data.storage import load_historical_data
      3. df = load_historical_data('BTC/USDT', '1h')
      4. engine = BacktestEngine()
      5. data_feed = engine.create_data_feed(df)
      6. assert data_feed.__class__.__name__ contains 'PandasData'
      7. cerebro = engine.cerebro
      8. cerebro.adddata(data_feed)
      9. assert cerebro.datas[0] is data_feed (data added to Cerebro)
    Expected Result: Custom data feed created from Parquet DataFrame
    Failure Indicators: PandasData not created, data not added to Cerebro
    Evidence: .sisyphus/evidence/task-07-data-feed.log
  ```

  **Evidence to Capture**:
  - [ ] Backtest engine initialization log
  - [ ] Backtest run output with trades and equity curve
  - [ ] Equity curve plot PNG file

  **Commit**: YES (Wave 1 partial)
  - Message: `feat(backtest): Backtrader integration with custom PandasData feed`
  - Files: backtest/engine.py, tests/test_backtest_engine.py
  - Pre-commit: `pytest tests/test_backtest_engine.py`

- [ ] 8. Backtest Engine - Performance metrics calculator

  **What to do**:
  - Create backtest/metrics.py with performance calculation functions
  - Implement calculate_sharpe_ratio(): (annualized return - risk_free_rate) / std_dev
  - Implement calculate_max_drawdown(): largest peak-to-trough decline in equity curve
  - Implement calculate_win_rate(): winning trades / total trades
  - Implement calculate_profit_factor(): gross profit / gross loss
  - Implement calculate_average_trade(): average profit per trade
  - Implement calculate_volatility(): annualized standard deviation of returns
  - Create generate_performance_report(): combine all metrics into single report dict
  - Add performance thresholds: Sharpe > 1.0, MaxDD < 20%, WinRate > 40%

  **Must NOT do**:
  - Calculate metrics for live trading (backtest metrics only for MVP)
  - Implement custom risk metrics beyond standard financial metrics
  - Add machine learning performance prediction

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires understanding of financial metrics, careful calculation
  - **Skills**: []
    - No special skills needed, standard financial calculations

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 6)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 12, 18 (CLI backtest command, paper trading validation)
  - **Blocked By**: Task 7 (needs backtest results to calculate metrics)

  **References**:
  - Sharpe ratio formula: (return - risk_free) / std_dev, annualized
  - Maximum drawdown: peak-to-trough decline
  - Win rate: winning_trades / total_trades
  - Profit factor: gross_profit / gross_loss
  - Industry benchmarks: Sharpe > 1.0 considered good for crypto strategies

  **Acceptance Criteria**:
  - [ ] backtest/metrics.py exists with performance calculation functions
  - [ ] calculate_sharpe_ratio() returns annualized Sharpe ratio
  - [ ] calculate_max_drawdown() returns max drawdown percentage
  - [ ] calculate_win_rate() returns win rate percentage
  - [ ] calculate_profit_factor() returns profit factor ratio
  - [ ] generate_performance_report() combines all metrics
  - [ ] Performance thresholds: Sharpe > 1.0, MaxDD < 20%, WinRate > 40%

  **QA Scenarios**:

  ```
  Scenario: Sharpe ratio calculation
    Tool: Bash (Python script)
    Preconditions: Backtest results with equity curve
    Steps:
      1. Create test equity curve: steady growth with some volatility
      2. from backtest.metrics import calculate_sharpe_ratio
      3. sharpe = calculate_sharpe_ratio(equity_curve, risk_free_rate=0.02)
      4. assert sharpe is not None (calculation succeeded)
      5. assert sharpe > 0 (positive return)
      6. Validate with manual calculation: (annual_return - 0.02) / std_dev
      7. assert sharpe approximately equals manual calculation
    Expected Result: Sharpe ratio calculated correctly, positive for good strategy
    Failure Indicators: Sharpe = None, negative Sharpe, incorrect calculation
    Evidence: .sisyphus/evidence/task-08-sharpe.log

  Scenario: Maximum drawdown calculation
    Tool: Bash (Python script)
    Preconditions: Equity curve with peak and trough
    Steps:
      1. Create test equity curve: peak 10000, trough 8000 (20% drawdown)
      2. from backtest.metrics import calculate_max_drawdown
      3. max_dd = calculate_max_drawdown(equity_curve)
      4. assert max_dd >= 0 (drawdown percentage)
      5. assert max_dd <= 1.0 (max 100% drawdown)
      6. Validate: peak=10000, trough=8000, max_dd should be 0.20 (20%)
      7. assert max_dd == 0.20 (correct calculation)
    Expected Result: Max drawdown calculated correctly, 20% for test data
    Failure Indicators: Wrong drawdown value, negative drawdown, > 100%
    Evidence: .sisyphus/evidence/task-08-max-dd.log

  Scenario: Performance report generation
    Tool: Bash (Python script)
    Preconditions: Backtest results with trades and equity curve
    Steps:
      1. from backtest.metrics import generate_performance_report
      2. report = generate_performance_report(backtest_results)
      3. assert 'sharpe_ratio' in report
      4. assert 'max_drawdown' in report
      5. assert 'win_rate' in report
      6. assert 'profit_factor' in report
      7. assert 'total_trades' in report
      8. assert 'final_value' in report
      9. Validate: report['sharpe_ratio'] > 1.0 for good strategy
    Expected Result: Complete performance report with all metrics
    Failure Indicators: Missing metrics, wrong values, incomplete report
    Evidence: .sisyphus/evidence/task-08-performance-report.log
  ```

  **Evidence to Capture**:
  - [ ] Sharpe ratio calculation output
  - [ ] Maximum drawdown calculation output
  - [ ] Complete performance report JSON

  **Commit**: YES (Wave 1 partial)
  - Message: `feat(backtest): performance metrics calculator with Sharpe and drawdown`
  - Files: backtest/metrics.py, tests/test_backtest_metrics.py
  - Pre-commit: `pytest tests/test_backtest_metrics.py`

- [ ] 9. Risk Manager - Position sizing module

  **What to do**:
  - Create risk/position_sizing.py with PositionSizer class
  - Implement fixed percentage sizing: position_size = portfolio_value * risk_pct
  - Implement volatility-based sizing: adjust position based on recent volatility
  - Add position limits: max_position_pct (e.g., 30% of portfolio), max_leverage (e.g., 2x)
  - Implement Kelly criterion as advanced option (optimal position size for maximizing growth)
  - Create risk calculator: assess risk for proposed position
  - Add position validation: check if proposed position exceeds limits
  - Integrate with strategy: provide position sizing recommendation with each signal

  **Must NOT do**:
  - Allow positions to exceed max_position_pct or max_leverage (hard limits enforced)
  - Implement dynamic position sizing based on ML predictions
  - Allow unlimited position sizing (must always have limits)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires understanding of risk management, position sizing theory
  - **Skills**: []
    - No special skills needed, standard risk calculation

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 10, 11, 12, 13, 14, 15)
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 10, 23 (stop-loss and live trading depend on position sizing)
  - **Blocked By**: Task 1 (needs config)

  **References**:
  - Position sizing methods: fixed percentage, volatility-based, Kelly criterion
  - Risk limits: max_position_pct prevents over-concentration
  - Kelly criterion: f = (p * b - q) / b where p = win probability, b = win/loss ratio

  **Acceptance Criteria**:
  - [ ] risk/position_sizing.py exists with PositionSizer class
  - [ ] Fixed percentage sizing implemented: portfolio_value * risk_pct
  - [ ] Volatility-based sizing implemented: adjust by recent std_dev
  - [ ] Position limits: max_position_pct = 30%, max_leverage = 2x
  - [ ] Kelly criterion available as advanced option
  - [ ] Position validation returns True/False for limit check
  - [ ] PositionSizer integrated with strategy signals

  **QA Scenarios**:

  ```
  Scenario: Fixed percentage position sizing
    Tool: Bash (Python script)
    Preconditions: PositionSizer implemented
    Steps:
      1. from risk.position_sizing import PositionSizer
      2. sizer = PositionSizer(method='fixed', risk_pct=0.1)
      3. portfolio_value = 10000
      4. position_size = sizer.calculate(portfolio_value)
      5. assert position_size == 1000 (10% of portfolio)
      6. Validate position: valid = sizer.validate_position(1000, portfolio_value)
      7. assert valid == True (within limits)
    Expected Result: Position size calculated as 10% of portfolio, validated
    Failure Indicators: Wrong position size, validation fails
    Evidence: .sisyphus/evidence/task-09-fixed-sizing.log

  Scenario: Position limit enforcement
    Tool: Bash (Python script)
    Preconditions: PositionSizer with max_position_pct = 30%
    Steps:
      1. from risk.position_sizing import PositionSizer
      2. sizer = PositionSizer(max_position_pct=0.3)
      3. portfolio_value = 10000
      4. Try to create position of 5000 (50% of portfolio)
      5. valid = sizer.validate_position(5000, portfolio_value)
      6. assert valid == False (exceeds 30% limit)
      7. Adjusted position = sizer.calculate(portfolio_value) with limit
      8. assert adjusted_position <= 3000 (capped at 30%)
    Expected Result: Large position rejected, capped at max_position_pct
    Failure Indicators: Large position accepted, not capped
    Evidence: .sisyphus/evidence/task-09-limit-enforce.log

  Scenario: Volatility-based sizing
    Tool: Bash (Python script)
    Preconditions: Historical data with volatility calculation
    Steps:
      1. from risk.position_sizing import PositionSizer
      2. sizer = PositionSizer(method='volatility')
      3. Calculate recent volatility: std_dev of last 20 bars
      4. position_size = sizer.calculate_volatility_based(portfolio_value, volatility)
      5. High volatility should result in smaller position
      6. Low volatility should result in larger position
      7. assert position_size inversely proportional to volatility
    Expected Result: Position size adjusted by volatility (smaller for high vol)
    Failure Indicators: Position not adjusted, wrong direction
    Evidence: .sisyphus/evidence/task-09-volatility-sizing.log
  ```

  **Evidence to Capture**:
  - [ ] Fixed percentage sizing calculation
  - [ ] Position limit enforcement rejection
  - [ ] Volatility-based sizing calculation

  **Commit**: YES (Wave 2 partial)
  - Message: `feat(risk): position sizing module with limits enforcement`
  - Files: risk/position_sizing.py, tests/test_position_sizing.py
  - Pre-commit: `pytest tests/test_position_sizing.py`

- [ ] 10. Risk Manager - Stop-loss implementation

  **What to do**:
  - Create risk/stop_loss.py with StopLossManager class
  - Implement percentage stop-loss: close position when price drops X% from entry
  - Implement trailing stop-loss: stop moves with price, locks in profits
  - Implement volatility-based stop-loss: stop at 2x recent volatility
  - Add stop-loss calculation for each position: stop_price = entry_price - stop_pct
  - Create stop-loss monitoring: check if current price triggers stop-loss
  - Implement stop-loss execution: generate CLOSE signal when triggered
  - Add stop-loss adjustment: update trailing stop when price moves favorably

  **Must NOT do**:
  - Allow positions without stop-loss (mandatory risk management)
  - Execute stop-loss without logging (must record all stop-loss events)
  - Implement ML-based stop-loss prediction

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires understanding of stop-loss types, careful trigger logic
  - **Skills**: []
    - No special skills needed, standard risk management

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 9, 11, 12, 13, 14, 15)
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 17, 23 (kill switch and live trading depend on stop-loss)
  - **Blocked By**: Task 9 (needs position sizing for context)

  **References**:
  - Stop-loss types: percentage, trailing, volatility-based
  - Trailing stop: moves with price to lock in profits
  - Volatility-based stop: 2x standard deviation of recent bars

  **Acceptance Criteria**:
  - [ ] risk/stop_loss.py exists with StopLossManager class
  - [ ] Percentage stop-loss implemented: close at entry - X%
  - [ ] Trailing stop-loss implemented: stop moves with price
  - [ ] Volatility-based stop-loss implemented: 2x std_dev
  - [ ] Stop-loss monitoring: check price vs stop_price each bar
  - [ ] Stop-loss execution: generate CLOSE signal when triggered
  - [ ] Stop-loss adjustment: update trailing stop on favorable price move
  - [ ] Mandatory stop-loss: no position without stop

  **QA Scenarios**:

  ```
  Scenario: Percentage stop-loss trigger
    Tool: Bash (Python script)
    Preconditions: StopLossManager implemented
    Steps:
      1. from risk.stop_loss import StopLossManager
      2. manager = StopLossManager(method='percentage', stop_pct=0.05)
      3. entry_price = 40000
      4. stop_price = manager.calculate_stop(entry_price)
      5. assert stop_price == 38000 (40000 - 5%)
      6. Check trigger: current_price = 37500
      7. triggered = manager.check_trigger(current_price, stop_price)
      8. assert triggered == True (price below stop)
      9. action = manager.execute_stop(position_id)
      10. assert action == 'CLOSE' (close signal generated)
    Expected Result: Stop-loss triggers at 5% drop, generates CLOSE signal
    Failure Indicators: Stop not triggered, wrong stop price, no CLOSE signal
    Evidence: .sisyphus/evidence/task-10-stop-trigger.log

  Scenario: Trailing stop-loss adjustment
    Tool: Bash (Python script)
    Preconditions: Trailing stop implemented
    Steps:
      1. from risk.stop_loss import StopLossManager
      2. manager = StopLossManager(method='trailing', trail_pct=0.03)
      3. entry_price = 40000, initial_stop = 38800 (3% trail)
      4. Price moves to 42000 (favorable)
      5. updated_stop = manager.update_trailing_stop(42000)
      6. assert updated_stop == 40740 (42000 - 3%)
      7. assert updated_stop > initial_stop (stop moved up)
      8. Price drops to 40600
      9. triggered = manager.check_trigger(40600, updated_stop)
      10. assert triggered == False (still above stop)
      11. Price drops to 40500
      12. triggered = manager.check_trigger(40500, updated_stop)
      13. assert triggered == True (below trailing stop)
    Expected Result: Trailing stop moves with price, triggers on reversal
    Failure Indicators: Stop not updated, wrong trigger
    Evidence: .sisyphus/evidence/task-10-trailing-stop.log

  Scenario: Mandatory stop-loss check
    Tool: Bash (Python script)
    Preconditions: Position created without stop-loss
    Steps:
      1. from risk.stop_loss import StopLossManager
      2. manager = StopLossManager()
      3. Create position with no stop-loss configured
      4. valid = manager.validate_position(position)
      5. assert valid == False (mandatory stop-loss)
      6. Add stop-loss to position
      7. valid = manager.validate_position(position_with_stop)
      8. assert valid == True (stop-loss present)
    Expected Result: Positions without stop-loss rejected
    Failure Indicators: Position accepted without stop-loss
    Evidence: .sisyphus/evidence/task-10-mandatory-stop.log
  ```

  **Evidence to Capture**:
  - [ ] Percentage stop-loss trigger log
  - [ ] Trailing stop-loss adjustment log
  - [ ] Mandatory stop-loss validation log

  **Commit**: YES (Wave 2 partial)
  - Message: `feat(risk): stop-loss implementation with trailing and volatility-based options`
  - Files: risk/stop_loss.py, tests/test_stop_loss.py
  - Pre-commit: `pytest tests/test_stop_loss.py`

- [ ] 11. CLI Interface - Command parser and dispatcher

  **What to do**:
  - Create cli/main.py with command-line interface
  - Implement argument parser with argparse: mode (--backtest, --paper, --live, --status)
  - Add strategy argument: --strategy (cta, stat_arb)
  - Add data arguments: --pair, --timeframe, --days
  - Add validation arguments: --validate, --duration
  - Create command dispatcher: route to appropriate module (backtest engine, live trading, etc.)
  - Implement help messages for each command
  - Add version argument: --version
  - Create error handling for invalid arguments

  **Must NOT do**:
  - Execute trades directly from CLI (CLI dispatches to execution modules)
  - Implement interactive mode (MVP uses simple command-line args)
  - Add Web API endpoints (CLI only, no HTTP server)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Standard argparse implementation, straightforward CLI
  - **Skills**: []
    - No special skills needed, basic Python CLI

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 9, 10, 12, 13, 14, 15)
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 12, 13 (CLI commands depend on parser)
  - **Blocked By**: Task 1 (needs project structure)

  **References**:
  - argparse documentation: https://docs.python.org/3/library/argparse.html
  - CLI commands: backtest, paper, live, status, config
  - Command dispatcher pattern: route commands to handlers

  **Acceptance Criteria**:
  - [ ] cli/main.py exists with argument parser
  - [ ] Mode arguments: --backtest, --paper, --live, --status
  - [ ] Strategy argument: --strategy (cta, stat_arb)
  - [ ] Data arguments: --pair, --timeframe, --days
  - [ ] Validation arguments: --validate, --duration
  - [ ] Command dispatcher routes to correct module
  - [ ] Help messages for each command
  - [ ] Error handling for invalid arguments

  **QA Scenarios**:

  ```
  Scenario: CLI argument parsing - backtest mode
    Tool: interactive_bash (tmux)
    Preconditions: cli/main.py exists
    Steps:
      1. python cli/main.py --help
      2. Assert help output contains: --backtest, --paper, --live, --status
      3. python cli/main.py --mode backtest --strategy cta --pair BTC/USDT --days 30
      4. Assert command parsed successfully (no argparse error)
      5. Assert dispatcher calls backtest engine
    Expected Result: Backtest command parsed and dispatched correctly
    Failure Indicators: Argparse error, wrong dispatcher call
    Evidence: .sisyphus/evidence/task-11-cli-parse.log

  Scenario: Invalid argument handling
    Tool: interactive_bash (tmux)
    Preconditions: CLI parser implemented
    Steps:
      1. python cli/main.py --mode invalid_mode
      2. Assert error message: "Invalid mode: must be backtest|paper|live|status"
      3. python cli/main.py --strategy invalid_strategy
      4. Assert error message: "Invalid strategy: must be cta|stat_arb"
      5. python cli/main.py --days -10
      6. Assert error message: "Days must be positive"
    Expected Result: Invalid arguments rejected with clear error messages
    Failure Indicators: Invalid arguments accepted, unclear error
    Evidence: .sisyphus/evidence/task-11-invalid-args.log

  Scenario: Help message display
    Tool: interactive_bash (tmux)
    Preconditions: CLI help configured
    Steps:
      1. python cli/main.py --help
      2. Assert output contains: "CryptoQuant - Crypto Quantitative Trading Platform"
      3. Assert output contains: "--mode MODE" description
      4. Assert output contains: "--strategy STRATEGY" description
      5. Assert output contains: "--pair PAIR" description
      6. python cli/main.py --mode backtest --help
      7. Assert backtest-specific help displayed
    Expected Result: Help messages displayed for main and mode-specific
    Failure Indicators: Missing help, incomplete descriptions
    Evidence: .sisyphus/evidence/task-11-help-msg.log
  ```

  **Evidence to Capture**:
  - [ ] Backtest command parsing output
  - [ ] Invalid argument error messages
  - [ ] Help message display output

  **Commit**: YES (Wave 2 partial)
  - Message: `feat(cli): command parser and dispatcher implementation`
  - Files: cli/main.py, tests/test_cli_parser.py
  - Pre-commit: `pytest tests/test_cli_parser.py`

- [ ] 12. CLI Interface - Backtest command

  **What to do**:
  - Create cli/commands/backtest.py with backtest command handler
  - Implement run_backtest_command(): parse args, load data, run backtest, display results
  - Display performance metrics: Sharpe ratio, max drawdown, win rate, profit factor
  - Show equity curve plot (matplotlib popup or save to file)
  - Display trades summary: entry/exit prices, profit/loss per trade
  - Add backtest validation: check if metrics meet thresholds (Sharpe > 1.0, MaxDD < 20%)
  - Create output formatting: table for metrics, list for trades
  - Add verbose mode: --verbose for detailed output

  **Must NOT do**:
  - Execute live trades from backtest command (simulation only)
  - Modify strategy parameters during backtest (use config parameters)
  - Implement multi-strategy comparison (single strategy per backtest)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Command handler that calls backtest engine, straightforward output formatting
  - **Skills**: []
    - No special skills needed, standard CLI command

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 9, 10, 11, 13, 14, 15)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 18 (paper trading validation uses backtest command)
  - **Blocked By**: Tasks 7, 8, 11 (needs backtest engine, metrics, and CLI parser)

  **References**:
  - Backtest command flow: parse args → load data → run backtest → display results
  - Output formatting: table for metrics, list for trades
  - Validation thresholds: Sharpe > 1.0, MaxDD < 20%, WinRate > 40%

  **Acceptance Criteria**:
  - [ ] cli/commands/backtest.py exists with run_backtest_command()
  - [ ] Command loads data, runs backtest, displays results
  - [ ] Performance metrics displayed: Sharpe, MaxDD, WinRate, ProfitFactor
  - [ ] Equity curve plot displayed or saved
  - [ ] Trades summary displayed: entry/exit, profit/loss
  - [ ] Backtest validation: check metrics vs thresholds
  - [ ] Output formatted as table (metrics) and list (trades)
  - [ ] Verbose mode: --verbose for detailed output

  **QA Scenarios**:

  ```
  Scenario: Backtest command execution
    Tool: interactive_bash (tmux)
    Preconditions: Backtest engine and CLI implemented
    Steps:
      1. python cli/main.py --mode backtest --strategy cta --pair BTC/USDT --days 30
      2. Assert output contains: "Running backtest for BTC/USDT..."
      3. Assert output contains: "Sharpe Ratio: 1.2"
      4. Assert output contains: "Max Drawdown: 15%"
      5. Assert output contains: "Win Rate: 45%"
      6. Assert output contains: "Total Trades: 12"
      7. Assert equity curve plot displayed or saved
      8. Assert trades list displayed with profit/loss
    Expected Result: Backtest runs and displays complete results
    Failure Indicators: Missing metrics, no plot, incomplete trades list
    Evidence: .sisyphus/evidence/task-12-backtest-cmd.log

  Scenario: Backtest validation - passing metrics
    Tool: Bash (Python script)
    Preconditions: Backtest with good strategy (Sharpe > 1.0)
    Steps:
      1. Run backtest: python cli/main.py --mode backtest --strategy cta --pair BTC/USDT
      2. Check validation output: "✓ Sharpe Ratio: 1.2 (> 1.0)"
      3. Check validation output: "✓ Max Drawdown: 15% (< 20%)"
      4. Check validation output: "✓ Win Rate: 45% (> 40%)"
      5. Assert "PASS" status displayed
      6. Assert recommendation: "Strategy validated for paper trading"
    Expected Result: Good strategy passes validation with PASS status
    Failure Indicators: Validation shows WARN/FAIL, wrong thresholds
    Evidence: .sisyphus/evidence/task-12-validation-pass.log

  Scenario: Backtest validation - failing metrics
    Tool: Bash (Python script)
    Preconditions: Backtest with poor strategy (Sharpe < 1.0)
    Steps:
      1. Run backtest with poor strategy data
      2. Check validation output: "✗ Sharpe Ratio: 0.8 (< 1.0)"
      3. Check validation output: "✗ Max Drawdown: 25% (> 20%)"
      4. Assert "FAIL" status displayed
      5. Assert recommendation: "Strategy needs improvement before paper trading"
    Expected Result: Poor strategy fails validation with FAIL status
    Failure Indicators: Poor strategy passes validation, wrong thresholds
    Evidence: .sisyphus/evidence/task-12-validation-fail.log
  ```

  **Evidence to Capture**:
  - [ ] Backtest command output with metrics
  - [ ] Validation PASS status for good strategy
  - [ ] Validation FAIL status for poor strategy

  **Commit**: YES (Wave 2 partial)
  - Message: `feat(cli): backtest command with validation and result display`
  - Files: cli/commands/backtest.py, tests/test_cli_backtest.py
  - Pre-commit: `pytest tests/test_cli_backtest.py`

- [ ] 13. CLI Interface - Status and config commands

  **What to do**:
  - Create cli/commands/status.py with status command handler
  - Implement run_status_command(): display current system state
  - Display: active strategy, current positions, balance, recent trades, risk status
  - Create cli/commands/config.py with config command handler
  - Implement run_config_command(): display or modify configuration
  - Show config: python main.py --config --show
  - Modify config: python main.py --config --set risk.max_position_pct=0.2
  - Add config validation: check if new config values are valid
  - Create status refresh: --refresh to update status from live data

  **Must NOT do**:
  - Modify API keys from CLI (API keys only in .env)
  - Execute trades from status/config commands (display only)
  - Implement config persistence (config changes temporary for MVP)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Display and simple config modification commands
  - **Skills**: []
    - No special skills needed, standard CLI commands

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 9, 10, 11, 12, 14, 15)
  - **Parallel Group**: Wave 2
  - **Blocks**: None (status/config are optional)
  - **Blocked By**: Task 11 (needs CLI parser)

  **References**:
  - Status display: active strategy, positions, balance, trades, risk status
  - Config modification: --set parameter=value
  - Config validation: check values against defined constraints

  **Acceptance Criteria**:
  - [ ] cli/commands/status.py exists with run_status_command()
  - [ ] Status displays: strategy, positions, balance, trades, risk status
  - [ ] cli/commands/config.py exists with run_config_command()
  - [ ] Config show: python main.py --config --show
  - [ ] Config modify: python main.py --config --set key=value
  - [ ] Config validation implemented
  - [ ] Status refresh: --refresh updates from live data

  **QA Scenarios**:

  ```
  Scenario: Status command display
    Tool: interactive_bash (tmux)
    Preconditions: System running with active strategy
    Steps:
      1. python cli/main.py --mode status
      2. Assert output contains: "Active Strategy: cta"
      3. Assert output contains: "Current Positions: BTC/USDT LONG"
      4. Assert output contains: "Balance: 10000 USDT"
      5. Assert output contains: "Recent Trades: 3 trades in last 24h"
      6. Assert output contains: "Risk Status: Max position 30%, Stop-loss active"
    Expected Result: Status displays complete system state
    Failure Indicators: Missing fields, incorrect values
    Evidence: .sisyphus/evidence/task-13-status-display.log

  Scenario: Config show command
    Tool: interactive_bash (tmux)
    Preconditions: Config file exists
    Steps:
      1. python cli/main.py --config --show
      2. Assert output contains: "exchange.name: okx"
      3. Assert output contains: "exchange.sandbox: true"
      4. Assert output contains: "data.history_days: 365"
      5. Assert output contains: "risk.max_position_pct: 0.3"
      6. Assert output contains: "risk.stop_loss_pct: 0.05"
    Expected Result: Config values displayed correctly
    Failure Indicators: Missing config keys, wrong values
    Evidence: .sisyphus/evidence/task-13-config-show.log

  Scenario: Config modify and validate
    Tool: interactive_bash (tmux)
    Preconditions: Config command implemented
    Steps:
      1. python cli/main.py --config --set risk.max_position_pct=0.4
      2. Assert output: "Updated: risk.max_position_pct = 0.4"
      3. python cli/main.py --config --show
      4. Assert max_position_pct now shows 0.4
      5. Try invalid value: python cli/main.py --config --set risk.max_position_pct=2.0
      6. Assert error: "Invalid value: max_position_pct must be <= 1.0"
    Expected Result: Config modified and validated successfully
    Failure Indicators: Invalid value accepted, config not updated
    Evidence: .sisyphus/evidence/task-13-config-modify.log
  ```

  **Evidence to Capture**:
  - [ ] Status command display output
  - [ ] Config show command output
  - [ ] Config modify and validation output

  **Commit**: YES (Wave 2 partial)
  - Message: `feat(cli): status and config commands for system monitoring`
  - Files: cli/commands/status.py, cli/commands/config.py, tests/test_cli_status.py
  - Pre-commit: `pytest tests/test_cli_status.py`

- [ ] 14. Logging & Audit - Structured logging setup

  **What to do**:
  - Create logs/logger.py with structured logging configuration
  - Use structlog for structured JSON logging: timestamp, level, module, event, data
  - Implement log rotation: RotatingFileHandler with max size 10MB, 5 backups
  - Create log levels: DEBUG (strategy calculations), INFO (key events), WARNING (risk alerts), ERROR (failures), CRITICAL (kill switch)
  - Add logging to each module: data, strategy, backtest, risk, execution
  - Implement context-aware logging: include strategy name, pair, position_id in logs
  - Create log directory: logs/trading.log, logs/backtest.log, logs/risk.log
  - Add log filtering: filter sensitive data (API keys never logged)

  **Must NOT do**:
  - Log API keys or secrets (security violation)
  - Log sensitive account information (balance details filtered)
  - Implement log streaming to external services (MVP logs locally)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Standard logging setup with structlog, straightforward configuration
  - **Skills**: []
    - No special skills needed, standard logging

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 9, 10, 11, 12, 13, 15)
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 15, 23 (audit trail and live trading need logging)
  - **Blocked By**: Task 1 (needs project structure and config)

  **References**:
  - structlog documentation: https://www.structlog.org/
  - Log rotation: RotatingFileHandler, maxBytes=10MB, backupCount=5
  - Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
  - Sensitive data filtering: never log API keys

  **Acceptance Criteria**:
  - [ ] logs/logger.py exists with structured logging
  - [ ] structlog configured: JSON format, timestamp, level, module, event
  - [ ] Log rotation: 10MB max, 5 backups
  - [ ] Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
  - [ ] Logging added to all modules: data, strategy, backtest, risk, execution
  - [ ] Context-aware logging: strategy, pair, position_id in logs
  - [ ] Log files: logs/trading.log, logs/backtest.log, logs/risk.log
  - [ ] Sensitive data filtered: no API keys in logs

  **QA Scenarios**:

  ```
  Scenario: Structured logging format
    Tool: Bash (Python script)
    Preconditions: Logging configured
    Steps:
      1. from logs.logger import get_logger
      2. logger = get_logger('strategy')
      3. logger.info('signal_generated', strategy='cta', pair='BTC/USDT', signal='LONG')
      4. cat logs/trading.log
      5. Assert JSON format: {"timestamp": "...", "level": "INFO", "module": "strategy", "event": "signal_generated", "strategy": "cta", "pair": "BTC/USDT", "signal": "LONG"}
      6. Assert timestamp is ISO 8601 format
      7. Assert level is INFO
    Expected Result: Logs in structured JSON format with all fields
    Failure Indicators: Non-JSON format, missing fields, wrong format
    Evidence: .sisyphus/evidence/task-14-logging-format.log

  Scenario: Log rotation
    Tool: Bash (Python script)
    Preconditions: Log rotation configured
    Steps:
      1. Generate large log: write > 10MB to logs/trading.log
      2. ls -la logs/
      3. Assert logs/trading.log size <= 10MB (rotation triggered)
      4. Assert logs/trading.log.1 exists (backup created)
      5. Assert logs/trading.log.2 exists if multiple rotations
      6. Assert no more than 5 backup files
    Expected Result: Log rotation triggered at 10MB, backups created
    Failure Indicators: Log exceeds 10MB, no backups, too many backups
    Evidence: .sisyphus/evidence/task-14-log-rotation.log

  Scenario: Sensitive data filtering
    Tool: Bash
    Preconditions: Logging active
    Steps:
      1. grep -r "API_KEY" logs/
      2. grep -r "API_SECRET" logs/
      3. grep -r "PASSPHRASE" logs/
      4. Assert grep returns no results (API keys not logged)
      5. grep -r "okx_api_key" logs/
      6. Assert grep returns no results (variable name not logged)
    Expected Result: No API keys or secrets in any log file
    Failure Indicators: API keys found in logs (security violation)
    Evidence: .sisyphus/evidence/task-14-sensitive-filter.log
  ```

  **Evidence to Capture**:
  - [ ] Structured JSON log sample
  - [ ] Log rotation backup files listing
  - [ ] Sensitive data grep results (should be empty)

  **Commit**: YES (Wave 2 partial)
  - Message: `feat(logs): structured logging with rotation and sensitive data filtering`
  - Files: logs/logger.py, tests/test_logging.py
  - Pre-commit: `pytest tests/test_logging.py`

- [ ] 15. Logging & Audit - Trade audit trail

  **What to do**:
  - Create logs/audit.py with trade audit trail module
  - Implement audit_trade(): record trade decision with full context (strategy, signal, risk checks, execution)
  - Record: timestamp, strategy, pair, action (BUY/SELL), price, quantity, signal reason, risk validation, order_id
  - Create audit_risk_event(): record risk events (stop-loss trigger, position limit breach)
  - Implement audit_query(): query audit trail by date, strategy, pair
  - Add audit export: export to CSV for external analysis
  - Create audit validation: check if all trades have complete audit records
  - Implement audit replay: replay audit trail to recreate trade history

  **Must NOT do**:
  - Delete audit records (permanent record required)
  - Modify audit records after creation (immutable audit trail)
  - Implement real-time audit streaming (batch audit for MVP)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Standard audit trail implementation, data recording and querying
  - **Skills**: []
    - No special skills needed, standard data logging

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 9, 10, 11, 12, 13, 14)
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 23, F3 (live trading and final QA need audit trail)
  - **Blocked By**: Task 14 (needs structured logging)

  **References**:
  - Audit trail fields: timestamp, strategy, pair, action, price, quantity, signal reason, risk validation, order_id
  - Risk event audit: stop-loss trigger, position limit breach
  - Audit query: filter by date, strategy, pair
  - Audit export: CSV format for external analysis

  **Acceptance Criteria**:
  - [ ] logs/audit.py exists with audit functions
  - [ ] audit_trade() records complete trade context
  - [ ] Audit fields: timestamp, strategy, pair, action, price, quantity, reason, risk, order_id
  - [ ] audit_risk_event() records risk events
  - [ ] audit_query() filters audit trail by criteria
  - [ ] Audit export to CSV implemented
  - [ ] Audit validation: check all trades have records
  - [ ] Audit replay recreates trade history

  **QA Scenarios**:

  ```
  Scenario: Trade audit recording
    Tool: Bash (Python script)
    Preconditions: Audit module implemented
    Steps:
      1. from logs.audit import audit_trade
      2. audit_trade(timestamp='2024-01-15T10:30:00', strategy='cta', pair='BTC/USDT', action='BUY', price=40000, quantity=0.01, reason='MA crossover', risk='passed', order_id='12345')
      3. from logs.audit import audit_query
      4. records = audit_query(strategy='cta', date='2024-01-15')
      5. assert len(records) >= 1
      6. assert records[0]['action'] == 'BUY'
      7. assert records[0]['price'] == 40000
      8. assert records[0]['reason'] == 'MA crossover'
    Expected Result: Trade audit recorded and queryable
    Failure Indicators: Missing record, query returns empty, wrong fields
    Evidence: .sisyphus/evidence/task-15-trade-audit.log

  Scenario: Risk event audit
    Tool: Bash (Python script)
    Preconditions: Risk event occurred
    Steps:
      1. from logs.audit import audit_risk_event
      2. audit_risk_event(timestamp='2024-01-15T11:00:00', event='stop_loss_trigger', position_id='pos_001', trigger_price=38000, stop_price=38500)
      3. records = audit_query(event_type='risk')
      4. assert len(records) >= 1
      5. assert records[0]['event'] == 'stop_loss_trigger'
      6. assert records[0]['trigger_price'] == 38000
    Expected Result: Risk events recorded in audit trail
    Failure Indicators: Missing risk event, wrong fields
    Evidence: .sisyphus/evidence/task-15-risk-audit.log

  Scenario: Audit export to CSV
    Tool: Bash (Python script)
    Preconditions: Multiple audit records exist
    Steps:
      1. from logs.audit import export_audit_to_csv
      2. export_audit_to_csv(output_path='logs/audit_export.csv', start_date='2024-01-01', end_date='2024-01-31')
      3. cat logs/audit_export.csv
      4. Assert CSV header: timestamp,strategy,pair,action,price,quantity,reason,order_id
      5. Assert CSV rows contain audit data
      6. wc -l logs/audit_export.csv
      7. Assert line count matches number of records
    Expected Result: Audit trail exported to CSV correctly
    Failure Indicators: Missing CSV file, wrong format, incomplete data
    Evidence: .sisyphus/evidence/task-15-audit-export.log
  ```

  **Evidence to Capture**:
  - [ ] Trade audit query results
  - [ ] Risk event audit query results
  - [ ] Audit CSV export file content

  **Commit**: YES (Wave 2 partial)
  - Message: `feat(logs): trade audit trail with query and export capabilities`
  - Files: logs/audit.py, tests/test_audit.py
  - Pre-commit: `pytest tests/test_audit.py`

- [ ] 16. Paper Trading - OKX demo integration

  **What to do**:
  - Create live/paper_trading.py with paper trading runner
  - Integrate OKX sandbox mode (demo trading): sandbox=True in OKX API client
  - Implement paper trading loop: fetch live data, generate signals, simulate execution
  - Create simulated order execution: track orders without real API calls
  - Add simulated position tracking: maintain position state locally
  - Implement simulated balance tracking: deduct/add balance for simulated trades
  - Create paper trading validation: check if simulated execution matches real execution logic
  - Add paper trading log: all simulated trades logged for audit

  **Must NOT do**:
  - Execute real orders in paper trading mode (simulation only)
  - Use real API keys for paper trading (sandbox API keys only)
  - Implement paper trading without logging (all simulated trades must be logged)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires integrating live data feed, strategy execution, and simulation logic
  - **Skills**: []
    - No special skills needed, standard simulation implementation

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 9-15)
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 17, 18, 19 (kill switch, validation runner, and 7-day test depend on paper trading)
  - **Blocked By**: Tasks 2, 9 (needs OKX API client and risk manager)

  **References**:
  - OKX sandbox mode: sandbox=True in ccxt configuration
  - Paper trading loop: fetch data → generate signal → simulate execution
  - Simulated execution: track orders locally without real API calls
  - Sandbox API keys: separate demo trading credentials

  **Acceptance Criteria**:
  - [ ] live/paper_trading.py exists with paper trading runner
  - [ ] OKX sandbox mode integrated: sandbox=True
  - [ ] Paper trading loop: fetch data, generate signals, simulate execution
  - [ ] Simulated order execution: track orders locally
  - [ ] Simulated position tracking: maintain position state
  - [ ] Simulated balance tracking: update balance for trades
  - [ ] Paper trading validation: check execution logic
  - [ ] All simulated trades logged

  **QA Scenarios**:

  ```
  Scenario: Paper trading initialization
    Tool: Bash (Python script)
    Preconditions: Paper trading module implemented
    Steps:
      1. from live.paper_trading import PaperTradingRunner
      2. runner = PaperTradingRunner(strategy='cta', pair='BTC/USDT', sandbox=True)
      3. assert runner.client.exchange.sandbox == True
      4. assert runner.strategy.__class__.__name__ == 'TrendFollowingStrategy'
      5. assert runner.pair == 'BTC/USDT'
      6. balance = runner.get_balance()
      7. assert balance['USDT'] == 10000 (sandbox demo balance)
    Expected Result: Paper trading initializes in sandbox mode
    Failure Indicators: Sandbox not enabled, wrong strategy, no demo balance
    Evidence: .sisyphus/evidence/task-16-paper-init.log

  Scenario: Simulated trade execution
    Tool: Bash (Python script)
    Preconditions: Paper trading runner active
    Steps:
      1. runner = PaperTradingRunner(strategy='cta', pair='BTC/USDT')
      2. runner.start() (start paper trading loop)
      3. Wait for signal generation
      4. signal = runner.get_last_signal()
      5. assert signal.type in ['LONG', 'SHORT', 'HOLD']
      6. If signal.type == 'LONG':
        7. runner.simulate_order(action='BUY', price=40000, quantity=0.01)
        8. position = runner.get_position()
        9. assert position['quantity'] == 0.01
        10. assert position['entry_price'] == 40000
        11. balance = runner.get_balance()
        12. assert balance['USDT'] == 10000 - 400 (40000 * 0.01)
    Expected Result: Simulated trade executed, position and balance updated
    Failure Indicators: Order not simulated, wrong position/balance
    Evidence: .sisyphus/evidence/task-16-sim-trade.log

  Scenario: Paper trading validation
    Tool: Bash (Python script)
    Preconditions: Multiple simulated trades executed
    Steps:
      1. runner = PaperTradingRunner(strategy='cta')
      2. runner.run_for_duration(duration=1h) (run for 1 hour)
      3. trades = runner.get_simulated_trades()
      4. assert len(trades) > 0 (trades simulated)
      5. Validate each trade: assert trade['risk_passed'] == True
      6. Validate balance consistency: assert runner.validate_balance()
      7. Validate position tracking: assert runner.validate_positions()
    Expected Result: Paper trading validation passes for all simulated trades
    Failure Indicators: No trades simulated, risk not passed, balance inconsistency
    Evidence: .sisyphus/evidence/task-16-paper-validate.log
  ```

  **Evidence to Capture**:
  - [ ] Paper trading initialization in sandbox mode
  - [ ] Simulated trade execution with position/balance update
  - [ ] Paper trading validation results

  **Commit**: YES (Wave 2 partial)
  - Message: `feat(live): paper trading with OKX sandbox integration`
  - Files: live/paper_trading.py, tests/test_paper_trading.py
  - Pre-commit: `pytest tests/test_paper_trading.py`

- [ ] 17. Kill Switch - Emergency position closure

  **What to do**:
  - Create live/kill_switch.py with KillSwitch class
  - Implement emergency_close_all(): immediately close all open positions
  - Add kill switch trigger conditions: manual trigger, max loss threshold, API disconnection
  - Implement position closure logic: send CLOSE orders for all positions
  - Add kill switch confirmation: require manual confirmation for first use
  - Create kill switch testing: test_kill_switch() function for validation
  - Add kill switch logging: log all kill switch events to audit trail
  - Implement kill switch recovery: after kill switch, system enters safe mode (no new positions)

  **Must NOT do**:
  - Trigger kill switch automatically without manual confirmation (user must trigger)
  - Allow kill switch to fail silently (must log all failures)
  - Allow new positions immediately after kill switch (safe mode enforced)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Critical safety mechanism, requires careful implementation and testing
  - **Skills**: []
    - No special skills needed, standard safety logic

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 18-25)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 23 (live trading depends on kill switch)
  - **Blocked By**: Tasks 9, 10 (needs position sizing and stop-loss)

  **References**:
  - Kill switch trigger: manual (CLI command), max loss (drawdown threshold), API disconnection
  - Emergency closure: CLOSE orders for all positions
  - Safe mode: after kill switch, no new positions allowed until manual reset
  - Kill switch testing: validate closure speed (< 5 seconds)

  **Acceptance Criteria**:
  - [ ] live/kill_switch.py exists with KillSwitch class
  - [ ] emergency_close_all() implemented
  - [ ] Trigger conditions: manual, max loss, API disconnection
  - [ ] Position closure logic: CLOSE orders for all
  - [ ] Manual confirmation required for first use
  - [ ] test_kill_switch() validation function
  - [ ] All kill switch events logged
  - [ ] Safe mode enforced after kill switch

  **QA Scenarios**:

  ```
  Scenario: Manual kill switch trigger
    Tool: Bash (Python script)
    Preconditions: Active positions exist, kill switch implemented
    Steps:
      1. from live.kill_switch import KillSwitch
      2. kill_switch = KillSwitch()
      3. Create 3 active positions (BTC, ETH, SOL)
      4. kill_switch.trigger_manual()
      5. Confirm: "Are you sure you want to close all positions? (yes/no)"
      6. Input: 'yes'
      7. positions = kill_switch.emergency_close_all()
      8. assert len(positions_closed) == 3
      9. assert all positions have status='CLOSED'
      10. assert closure_time < 5 seconds for all positions
      11. balance = get_balance()
      12. assert balance reflects closure (funds returned)
    Expected Result: All positions closed within 5 seconds on manual trigger
    Failure Indicators: Positions not closed, slow closure (> 5s), confirmation skipped
    Evidence: .sisyphus/evidence/task-17-kill-manual.log

  Scenario: Kill switch test mode
    Tool: Bash (Python script)
    Preconditions: Kill switch test function implemented
    Steps:
      1. python cli/main.py --mode paper --strategy cta --test-kill-switch
      2. Assert output: "Testing kill switch..."
      3. Assert positions created for test
      4. Assert kill switch triggered automatically in test mode
      5. Assert all test positions closed < 5 seconds
      6. Assert output: "Kill switch test PASSED"
      7. Assert safe mode activated: "System in safe mode, no new positions"
    Expected Result: Kill switch test passes, all positions closed quickly
    Failure Indicators: Test fails, positions not closed, safe mode not activated
    Evidence: .sisyphus/evidence/task-17-kill-test.log

  Scenario: Safe mode enforcement
    Tool: Bash (Python script)
    Preconditions: Kill switch triggered, safe mode active
    Steps:
      1. from live.kill_switch import KillSwitch
      2. kill_switch.trigger_manual()
      3. assert kill_switch.safe_mode == True
      4. Try to create new position: runner.simulate_order(action='BUY', ...)
      5. Assert error: "System in safe mode, no new positions allowed"
      6. Manual reset: kill_switch.reset_safe_mode()
      7. assert kill_switch.safe_mode == False
      8. New position now allowed
    Expected Result: Safe mode prevents new positions until manual reset
    Failure Indicators: New position allowed in safe mode, reset fails
    Evidence: .sisyphus/evidence/task-17-safe-mode.log
  ```

  **Evidence to Capture**:
  - [ ] Manual kill switch trigger and closure log
  - [ ] Kill switch test results
  - [ ] Safe mode enforcement log

  **Commit**: YES (Wave 3 partial)
  - Message: `feat(live): kill switch for emergency position closure`
  - Files: live/kill_switch.py, tests/test_kill_switch.py
  - Pre-commit: `pytest tests/test_kill_switch.py`

- [ ] 18. Paper Trading - Strategy validation runner

  **What to do**:
  - Create live/validation_runner.py with validation runner
  - Implement run_validation(): execute strategy on paper trading for specified duration
  - Add validation metrics: trades count, win rate, max drawdown, Sharpe ratio
  - Create validation thresholds: win rate > 40%, max drawdown < 20%, Sharpe > 1.0
  - Implement validation reporting: generate validation report after duration
  - Add validation logging: log all validation events
  - Create validation comparison: compare paper trading results to backtest results
  - Implement validation approval: approve strategy for live trading if validation passes

  **Must NOT do**:
  - Approve strategy without validation (must run paper trading first)
  - Skip validation thresholds (all thresholds must be checked)
  - Run live trading before validation passes

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires running paper trading, collecting metrics, comparing results
  - **Skills**: []
    - No special skills needed, standard validation logic

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 17, 19-25)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 19 (7-day test depends on validation runner)
  - **Blocked By**: Tasks 6, 16 (needs strategy and paper trading)

  **References**:
  - Validation duration: minimum 7 days for paper trading
  - Validation metrics: trades count, win rate, max drawdown, Sharpe ratio
  - Validation thresholds: win rate > 40%, max drawdown < 20%, Sharpe > 1.0
  - Validation approval: strategy approved for live trading if all thresholds pass

  **Acceptance Criteria**:
  - [ ] live/validation_runner.py exists with validation runner
  - [ ] run_validation() executes paper trading for duration
  - [ ] Validation metrics collected: trades, win rate, drawdown, Sharpe
  - [ ] Validation thresholds: win_rate > 40%, max_dd < 20%, sharpe > 1.0
  - [ ] Validation report generated
  - [ ] Validation logging implemented
  - [ ] Paper vs backtest comparison
  - [ ] Validation approval for live trading

  **QA Scenarios**:

  ```
  Scenario: Validation runner execution
    Tool: Bash (Python script)
    Preconditions: Strategy implemented, paper trading active
    Steps:
      1. from live.validation_runner import run_validation
      2. report = run_validation(strategy='cta', duration=1h) (run for 1 hour test)
      3. assert 'trades_count' in report
      4. assert 'win_rate' in report
      5. assert 'max_drawdown' in report
      6. assert 'sharpe_ratio' in report
      7. assert report['duration'] == '1h'
      8. assert report['trades_count'] >= 0
      9. assert 0 <= report['win_rate'] <= 100
    Expected Result: Validation runs and collects metrics
    Failure Indicators: Missing metrics, wrong duration, invalid values
    Evidence: .sisyphus/evidence/task-18-validation-run.log

  Scenario: Validation threshold check
    Tool: Bash (Python script)
    Preconditions: Validation report generated
    Steps:
      1. from live.validation_runner import check_validation_thresholds
      2. report = {'win_rate': 45, 'max_drawdown': 15, 'sharpe_ratio': 1.2, 'trades_count': 10}
      3. passed = check_validation_thresholds(report)
      4. assert passed == True (all thresholds pass)
      5. Check individual thresholds:
        6. assert win_rate >= 40
        7. assert max_drawdown <= 20
        8. assert sharpe_ratio >= 1.0
        9. assert trades_count >= 5 (minimum trades for validation)
    Expected Result: Validation thresholds checked correctly
    Failure Indicators: Thresholds not checked, wrong logic
    Evidence: .sisyphus/evidence/task-18-thresholds.log

  Scenario: Validation approval
    Tool: Bash (Python script)
    Preconditions: Validation passed all thresholds
    Steps:
      1. from live.validation_runner import approve_for_live_trading
      2. approval = approve_for_live_trading(validation_report)
      3. assert approval['approved'] == True
      4. assert approval['strategy'] == 'cta'
      5. assert approval['reason'] == 'All validation thresholds passed'
      6. assert approval['paper_trading_duration'] == '7d'
      7. assert approval['approved_timestamp'] is not None
      8. Log approval: audit_risk_event(event='strategy_approved', ...)
    Expected Result: Strategy approved for live trading after validation
    Failure Indicators: Not approved despite passing thresholds, missing approval record
    Evidence: .sisyphus/evidence/task-18-approval.log
  ```

  **Evidence to Capture**:
  - [ ] Validation runner output with metrics
  - [ ] Validation threshold check results
  - [ ] Validation approval record

  **Commit**: YES (Wave 3 partial)
  - Message: `feat(live): validation runner with threshold checking and approval`
  - Files: live/validation_runner.py, tests/test_validation_runner.py
  - Pre-commit: `pytest tests/test_validation_runner.py`

- [ ] 19. Paper Trading - 7-day validation test suite

  **What to do**:
  - Create tests/validation/test_7day_validation.py with 7-day test suite
  - Implement continuous paper trading for 7 days: run strategy, collect metrics daily
  - Add daily metric logging: log win rate, drawdown, Sharpe for each day
  - Create daily validation check: check if metrics improving or stable
  - Implement anomaly detection: flag unusual trading behavior (no trades for 24h, extreme losses)
  - Add test interruption handling: pause/resume validation, save state
  - Create final validation report: aggregate 7-day results, compare to initial backtest
  - Implement test suite automation: run automatically after backtest validation passes

  **Must NOT do**:
  - Allow live trading before 7-day validation completes
  - Skip daily metric checks (must validate each day)
  - Ignore anomalies during validation (must flag unusual behavior)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires long-running test, continuous monitoring, anomaly detection
  - **Skills**: []
    - No special skills needed, standard test suite

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 17, 18, 20-25)
  - **Parallel Group**: Wave 3
  - **Blocks**: F3 (final QA needs 7-day validation results)
  - **Blocked By**: Task 18 (needs validation runner)

  **References**:
  - 7-day validation: minimum duration for paper trading
  - Daily metrics: log win rate, drawdown, Sharpe daily
  - Anomaly detection: no trades for 24h, extreme losses (> 10% in single day)
  - Final report: aggregate 7-day results, compare to backtest

  **Acceptance Criteria**:
  - [ ] tests/validation/test_7day_validation.py exists
  - [ ] Continuous paper trading for 7 days
  - [ ] Daily metric logging: win rate, drawdown, Sharpe
  - [ ] Daily validation check: metrics improving/stable
  - [ ] Anomaly detection: no trades 24h, extreme losses
  - [ ] Test interruption handling: pause/resume
  - [ ] Final validation report: aggregate 7-day
  - [ ] Test suite automation: run after backtest validation

  **QA Scenarios**:

  ```
  Scenario: 7-day validation execution
    Tool: Bash (Python script) - long-running test
    Preconditions: Validation runner implemented
    Steps:
      1. python tests/validation/test_7day_validation.py --strategy cta --duration 7d
      2. Assert output: "Starting 7-day validation..."
      3. Assert daily log created: logs/validation_day_1.log, day_2.log, ..., day_7.log
      4. Each day log contains: win_rate, drawdown, sharpe, trades_count
      5. After 7 days, assert final report generated
      6. Assert final report contains: avg_win_rate, avg_drawdown, avg_sharpe
      7. Assert comparison to backtest: backtest_sharpe vs paper_sharpe
    Expected Result: 7-day validation runs continuously, daily logs created, final report generated
    Failure Indicators: Missing daily logs, incomplete final report, validation interrupted
    Evidence: .sisyphus/evidence/task-19-7day-run.log

  Scenario: Anomaly detection during validation
    Tool: Bash (Python script)
    Preconditions: Validation running, anomaly introduced
    Steps:
      1. Simulate anomaly: no trades for 24 hours
      2. Check anomaly detection: from live.validation_runner import detect_anomaly
      3. anomaly = detect_anomaly(daily_metrics)
      4. assert anomaly['type'] == 'no_trades'
      5. assert anomaly['severity'] == 'HIGH'
      6. assert anomaly['message'] == 'No trades generated in 24 hours'
      7. Assert anomaly logged: grep "no_trades anomaly" logs/validation.log
      8. Simulate extreme loss: > 10% drawdown in single day
      9. anomaly = detect_anomaly(daily_metrics_with_loss)
      10. assert anomaly['type'] == 'extreme_loss'
    Expected Result: Anomalies detected and logged during validation
    Failure Indicators: Anomaly not detected, not logged
    Evidence: .sisyphus/evidence/task-19-anomaly.log

  Scenario: Validation interruption and resume
    Tool: Bash (Python script)
    Preconditions: 7-day validation running
    Steps:
      1. Start validation: python test_7day_validation.py
      2. After day 3, interrupt: Ctrl+C
      3. Assert state saved: validation_state.json
      4. Resume validation: python test_7day_validation.py --resume
      5. Assert output: "Resuming validation from day 3..."
      6. Assert validation continues from saved state
      7. After completion, assert full 7 days validated
    Expected Result: Validation interrupted, state saved, resumed correctly
    Failure Indicators: State not saved, resume fails, incomplete validation
    Evidence: .sisyphus/evidence/task-19-interrupt.log
  ```

  **Evidence to Capture**:
  - [ ] 7-day validation final report
  - [ ] Anomaly detection logs
  - [ ] Validation interruption/resume state

  **Commit**: YES (Wave 3 partial)
  - Message: `feat(tests): 7-day validation test suite with anomaly detection`
  - Files: tests/validation/test_7day_validation.py, live/validation_state.py
  - Pre-commit: None (long-running test, manual execution)

- [ ] 20. Strategy Module - Statistical arbitrage base

  **What to do**:
  - Create strategy/stat_arb/__init__.py with stat arb namespace
  - Create strategy/stat_arb/base.py with StatArbStrategyBase class
  - Define stat arb strategy interface: find_pairs(), calculate_spread(), generate_signal()
  - Implement pair selection logic: correlation analysis, cointegration test
  - Create spread calculation: normalized price difference between pair
  - Define signal types: OPEN_PAIR (long A, short B), CLOSE_PAIR, HOLD
  - Add stat arb parameters: correlation_threshold, spread_threshold, lookback_period
  - Implement strategy state: track pair positions, spread history

  **Must NOT do**:
  - Execute trades directly from stat arb strategy (signals only)
  - Implement ML-based pair selection (MVP uses correlation + cointegration)
  - Add multi-pair arbitrage (MVP focuses on single pair at a time)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Requires understanding statistical arbitrage theory, pair trading, cointegration
  - **Skills**: []
    - No special skills needed, standard stat arb implementation

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 17, 18, 19, 21-25)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 21 (pair trading implementation depends on base)
  - **Blocked By**: Task 5 (needs strategy base framework)

  **References**:
  - Statistical arbitrage theory: pairs trading, mean reversion
  - Pair selection: correlation > 0.8, cointegration test (Engle-Granger)
  - Spread calculation: price_A / price_A_mean - price_B / price_B_mean
  - Signal generation: open pair when spread exceeds threshold, close when spread normalizes

  **Acceptance Criteria**:
  - [ ] strategy/stat_arb/__init__.py created
  - [ ] strategy/stat_arb/base.py exists with StatArbStrategyBase
  - [ ] Strategy interface: find_pairs(), calculate_spread(), generate_signal()
  - [ ] Pair selection: correlation analysis, cointegration test
  - [ ] Spread calculation: normalized price difference
  - [ ] Signal types: OPEN_PAIR, CLOSE_PAIR, HOLD
  - [ ] Parameters: correlation_threshold, spread_threshold, lookback_period
  - [ ] Strategy state: pair positions, spread history

  **QA Scenarios**:

  ```
  Scenario: Stat arb strategy base instantiation
    Tool: Bash (Python script)
    Preconditions: Stat arb base implemented
    Steps:
      1. from strategy.stat_arb.base import StatArbStrategyBase, SignalType
      2. Create test strategy: class TestStatArb(StatArbStrategyBase)
      3. Implement required methods: find_pairs(), calculate_spread(), generate_signal()
      4. strategy = TestStatArb(params={'correlation_threshold': 0.8, 'spread_threshold': 0.05})
      5. assert strategy.params['correlation_threshold'] == 0.8
      6. assert hasattr(strategy, 'pair_positions')
      7. assert hasattr(strategy, 'spread_history')
      8. assert SignalType.OPEN_PAIR == 'OPEN_PAIR'
    Expected Result: Stat arb base class works, concrete implementation possible
    Failure Indicators: Abstract method not enforced, missing state tracking
    Evidence: .sisyphus/evidence/task-20-statarb-base.log

  Scenario: Pair selection - correlation analysis
    Tool: Bash (Python script)
    Preconditions: Historical data for BTC, ETH
    Steps:
      1. from strategy.stat_arb.base import StatArbStrategyBase
      2. strategy = StatArbStrategyBase()
      3. pairs = strategy.find_pairs(['BTC/USDT', 'ETH/USDT'], correlation_threshold=0.8)
      4. Calculate correlation: df_btc.close vs df_eth.close
      5. correlation = df_btc.corrwith(df_eth)
      6. assert correlation > 0.8 for BTC/ETH pair
      7. assert 'BTC/USDT-ETH/USDT' in pairs (selected pair)
      8. If correlation < 0.8, assert pair not selected
    Expected Result: High correlation pairs selected correctly
    Failure Indicators: Pair not selected despite high correlation, wrong threshold
    Evidence: .sisyphus/evidence/task-20-pair-select.log

  Scenario: Spread calculation
    Tool: Bash (Python script)
    Preconditions: Pair data available
    Steps:
      1. from strategy.stat_arb.base import StatArbStrategyBase
      2. strategy = StatArbStrategyBase()
      3. btc_price = 40000, eth_price = 2000
      4. btc_mean = 38000, eth_mean = 1900
      5. spread = strategy.calculate_spread(btc_price, btc_mean, eth_price, eth_mean)
      6. Normalized BTC: 40000/38000 = 1.05
      7. Normalized ETH: 2000/1900 = 1.05
      8. spread = 1.05 - 1.05 = 0.0 (prices in sync)
      9. assert spread == 0.0 (correct calculation)
      10. Alternative: btc_price=40000, eth_price=1800
      11. spread = 1.05 - 0.95 = 0.10 (spread divergence)
      12. assert spread == 0.10
    Expected Result: Spread calculated correctly as normalized difference
    Failure Indicators: Wrong spread value, incorrect normalization
    Evidence: .sisyphus/evidence/task-20-spread-calc.log
  ```

  **Evidence to Capture**:
  - [ ] Stat arb base class instantiation
  - [ ] Pair selection with correlation analysis
  - [ ] Spread calculation results

  **Commit**: YES (Wave 3 partial)
  - Message: `feat(strategy): statistical arbitrage base framework with pair selection`
  - Files: strategy/stat_arb/__init__.py, strategy/stat_arb/base.py, tests/test_stat_arb_base.py
  - Pre-commit: `pytest tests/test_stat_arb_base.py`

- [ ] 21. Strategy Module - Pair trading implementation

  **What to do**:
  - Create strategy/stat_arb/pair_trading.py with PairTradingStrategy class
  - Implement pair trading logic: open position when spread exceeds threshold
  - Add spread threshold: open pair when spread > 0.05, close when spread < 0.01
  - Implement position opening: long asset A, short asset B (or vice versa)
  - Create spread monitoring: check spread each bar, update spread history
  - Add mean reversion signal: signal to close pair when spread normalizes
  - Implement pair position sizing: equal dollar amount for both legs
  - Add pair risk management: stop-loss on spread, position limits for pair

  **Must NOT do**:
  - Open pair without spread threshold check (must wait for divergence)
  - Allow asymmetric pair positions (must be equal dollar amount)
  - Implement multi-pair arbitrage (single pair per strategy instance)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Requires understanding pair trading logic, mean reversion, position management
  - **Skills**: []
    - No special skills needed, standard pair trading

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 17-20, 22-25)
  - **Parallel Group**: Wave 3
  - **Blocks**: None (stat arb is optional, extends strategy options)
  - **Blocked By**: Tasks 20, 7 (needs stat arb base and backtest)

  **References**:
  - Pair trading logic: open on spread divergence, close on normalization
  - Spread thresholds: open at 0.05 divergence, close at 0.01
  - Position opening: long A + short B (or short A + long B)
  - Mean reversion: spread returns to mean over time

  **Acceptance Criteria**:
  - [ ] strategy/stat_arb/pair_trading.py exists with PairTradingStrategy
  - [ ] Pair trading logic: open on spread > threshold
  - [ ] Spread threshold: open > 0.05, close < 0.01
  - [ ] Position opening: long A, short B (or vice versa)
  - [ ] Spread monitoring each bar
  - [ ] Mean reversion signal: close on normalization
  - [ ] Pair position sizing: equal dollar amount
  - [ ] Pair risk management: stop-loss on spread

  **QA Scenarios**:

  ```
  Scenario: Pair trading - open pair on divergence
    Tool: Bash (Python script)
    Preconditions: PairTradingStrategy implemented, BTC/ETH data
    Steps:
      1. from strategy.stat_arb.pair_trading import PairTradingStrategy
      2. strategy = PairTradingStrategy(pair='BTC/USDT-ETH/USDT', spread_threshold=0.05)
      3. strategy.initialize()
      4. Feed data: BTC price rises, ETH stays stable → spread = 0.06
      5. signal = strategy.generate_signal()
      6. assert signal.type == 'OPEN_PAIR'
      7. assert signal.action_A == 'LONG' (long BTC)
      8. assert signal.action_B == 'SHORT' (short ETH)
      9. assert signal.spread == 0.06 (recorded spread)
      10. assert signal.reason == 'Spread divergence > threshold'
    Expected Result: Pair opened on spread divergence, long BTC + short ETH
    Failure Indicators: No signal, wrong action, spread not recorded
    Evidence: .sisyphus/evidence/task-21-pair-open.log

  Scenario: Pair trading - close pair on normalization
    Tool: Bash (Python script)
    Preconditions: Open pair position, spread normalizing
    Steps:
      1. strategy has open pair position (long BTC, short ETH)
      2. Feed data: BTC price drops, ETH rises → spread = 0.01
      3. signal = strategy.generate_signal()
      4. assert signal.type == 'CLOSE_PAIR'
      5. assert signal.reason == 'Spread normalized'
      6. assert signal.profit == calculated profit (BTC gain + ETH gain)
      7. Check pair position closed: assert strategy.pair_positions empty
    Expected Result: Pair closed on spread normalization, profit calculated
    Failure Indicators: Pair not closed, wrong signal, position not cleared
    Evidence: .sisyphus/evidence/task-21-pair-close.log

  Scenario: Pair position sizing - equal dollar amount
    Tool: Bash (Python script)
    Preconditions: Pair opening signal generated
    Steps:
      1. strategy = PairTradingStrategy(position_size=1000)
      2. signal = strategy.generate_signal() (OPEN_PAIR)
      3. position_A = signal.quantity_A * signal.price_A
      4. position_B = signal.quantity_B * signal.price_B
      5. assert position_A == position_B (equal dollar amount)
      6. assert position_A == 1000 (specified position size)
      7. assert position_B == 1000
    Expected Result: Pair positions equal dollar amount
    Failure Indicators: Asymmetric positions, wrong size
    Evidence: .sisyphus/evidence/task-21-pair-sizing.log
  ```

  **Evidence to Capture**:
  - [ ] Pair opening on divergence signal
  - [ ] Pair closing on normalization signal
  - [ ] Pair position sizing output

  **Commit**: YES (Wave 3 partial)
  - Message: `feat(strategy): pair trading implementation with mean reversion`
  - Files: strategy/stat_arb/pair_trading.py, tests/test_pair_trading.py
  - Pre-commit: `pytest tests/test_pair_trading.py`

- [ ] 22. Live Trading - OKX live API client

  **What to do**:
  - Create live/client.py with LiveTradingClient class
  - Extend OKX API client for live trading: sandbox=False, real API keys
  - Implement live order placement: create_order(), cancel_order()
  - Add live balance tracking: fetch real balance from OKX account
  - Create live position tracking: fetch open positions from OKX
  - Implement live ticker subscription: fetch real-time price updates
  - Add API key validation: check if live API keys have trading permissions
  - Create live trading safeguards: check balance > minimum, check API permissions

  **Must NOT do**:
  - Use sandbox API keys for live trading (must use real API keys with trading permissions)
  - Execute live orders without balance check (must verify sufficient balance)
  - Allow live trading without API key validation (must check permissions)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Critical for live trading, requires careful API integration and safety checks
  - **Skills**: []
    - No special skills needed, standard live API

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 17-21, 23-25)
  - **Parallel Group**: Wave 3
  - **Blocks**: Tasks 23, 24, 25 (order execution, position tracker, manual confirmation)
  - **Blocked By**: Tasks 1, 14, 15 (needs config, logging, audit)

  **References**:
  - OKX live API: sandbox=False, real API keys required
  - Live order placement: create_order(symbol, type, side, amount, price)
  - Live balance tracking: fetch_balance() returns real account balance
  - API key validation: check 'trade' permission enabled

  **Acceptance Criteria**:
  - [ ] live/client.py exists with LiveTradingClient
  - [ ] Live API client: sandbox=False
  - [ ] Live order placement: create_order(), cancel_order()
  - [ ] Live balance tracking: fetch real balance
  - [ ] Live position tracking: fetch open positions
  - [ ] Live ticker subscription: real-time prices
  - [ ] API key validation: check trading permissions
  - [ ] Live trading safeguards: balance check, permission check

  **QA Scenarios**:

  ```
  Scenario: Live API client initialization
    Tool: Bash (Python script)
    Preconditions: Live API keys configured in .env
    Steps:
      1. from live.client import LiveTradingClient
      2. client = LiveTradingClient()
      3. assert client.exchange.sandbox == False (live mode)
      4. permissions = client.validate_api_permissions()
      5. assert permissions['trade'] == True (trading enabled)
      6. assert permissions['read'] == True (read enabled)
      7. balance = client.fetch_balance()
      8. assert balance['total']['USDT'] >= minimum_balance (e.g., 100 USDT)
    Expected Result: Live client initializes, API keys validated, balance sufficient
    Failure Indicators: Sandbox mode on, missing permissions, insufficient balance
    Evidence: .sisyphus/evidence/task-22-live-client.log

  Scenario: Live order placement
    Tool: Bash (Python script) - CAREFUL: This creates real order
    Preconditions: Live client initialized, balance sufficient
    Steps:
      1. client = LiveTradingClient()
      2. balance_before = client.fetch_balance()['total']['USDT']
      3. order = client.create_order(symbol='BTC/USDT', type='limit', side='buy', amount=0.001, price=40000)
      4. assert order['id'] is not None (order created)
      5. assert order['status'] == 'open' or 'filled'
      6. balance_after = client.fetch_balance()['total']['USDT']
      7. assert balance_after < balance_before (balance deducted for buy order)
      8. Cancel order if still open: client.cancel_order(order['id'])
      9. assert order cancelled successfully
    Expected Result: Live order created, balance updated, order cancelable
    Failure Indicators: Order creation fails, balance not updated, cancel fails
    Evidence: .sisyphus/evidence/task-22-live-order.log

  Scenario: API key validation - missing permissions
    Tool: Bash (Python script)
    Preconditions: API keys without trade permission
    Steps:
      1. Set API keys with read-only permission in test environment
      2. client = LiveTradingClient()
      3. permissions = client.validate_api_permissions()
      4. assert permissions['trade'] == False (trading not enabled)
      5. Try to create order
      6. assert error raised: "API key does not have trading permission"
      7. assert order not created
    Expected Result: API keys without trading permission rejected
    Failure Indicators: Order created despite missing permission
    Evidence: .sisyphus/evidence/task-22-api-validation.log
  ```

  **Evidence to Capture**:
  - [ ] Live client initialization with permission validation
  - [ ] Live order placement and balance update
  - [ ] API key validation rejection for missing permissions

  **Commit**: YES (Wave 3 partial)
  - Message: `feat(live): live trading client with OKX API and safety checks`
  - Files: live/client.py, tests/test_live_client.py
  - Pre-commit: `pytest tests/test_live_client.py` (careful with real API)

- [ ] 23. Live Trading - Order execution manager

  **What to do**:
  - Create live/execution.py with OrderExecutionManager class
  - Implement execute_signal(): convert strategy signal to OKX order
  - Add order routing: route signals to correct execution (market vs limit orders)
  - Create order validation: check order against risk limits before execution
  - Implement order tracking: track order status (open, filled, cancelled, rejected)
  - Add order timeout handling: cancel orders not filled within timeout (e.g., 60 seconds)
  - Create order retry logic: retry failed orders up to 3 times
  - Add execution logging: log all execution events to audit trail

  **Must NOT do**:
  - Execute orders without risk validation (must check risk limits)
  - Allow orders to exceed position limits (must reject oversized orders)
  - Execute orders without logging (must record all execution events)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Critical execution layer, requires careful order management and validation
  - **Skills**: []
    - No special skills needed, standard execution logic

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 17-22, 24, 25)
  - **Parallel Group**: Wave 3
  - **Blocks**: Tasks 24, 25 (position tracker and manual confirmation depend on execution)
  - **Blocked By**: Tasks 22, 9, 10, 15 (needs live client, risk manager, audit)

  **References**:
  - Signal execution: convert LONG/SHORT signals to BUY/SELL orders
  - Order routing: market orders for immediate execution, limit orders for price control
  - Risk validation: check position limits, balance sufficiency before execution
  - Order tracking: status monitoring (open → filled/cancelled)

  **Acceptance Criteria**:
  - [ ] live/execution.py exists with OrderExecutionManager
  - [ ] execute_signal() converts signal to order
  - [ ] Order routing: market vs limit orders
  - [ ] Order validation against risk limits
  - [ ] Order tracking: status monitoring
  - [ ] Order timeout handling: cancel after 60s
  - [ ] Order retry logic: max 3 retries
  - [ ] Execution logging to audit trail

  **QA Scenarios**:

  ```
  Scenario: Signal execution - LONG signal
    Tool: Bash (Python script)
    Preconditions: Execution manager, live client, risk manager
    Steps:
      1. from live.execution import OrderExecutionManager
      2. from strategy.base import Signal
      3. manager = OrderExecutionManager()
      4. signal = Signal(type='LONG', pair='BTC/USDT', price=40000, quantity=0.01)
      5. Validate signal: valid = manager.validate_signal(signal)
      6. assert valid == True (risk limits passed)
      7. order = manager.execute_signal(signal)
      8. assert order['symbol'] == 'BTC/USDT'
      9. assert order['side'] == 'buy'
      10. assert order['amount'] == 0.01
      11. assert order['id'] is not None
      12. audit_record = get_audit(order['id'])
      13. assert audit_record['signal_type'] == 'LONG'
    Expected Result: LONG signal executed as BUY order, audit trail created
    Failure Indicators: Signal not validated, order not created, missing audit
    Evidence: .sisyphus/evidence/task-23-signal-exec.log

  Scenario: Order validation - oversized position
    Tool: Bash (Python script)
    Preconditions: Risk manager with max_position_pct = 30%
    Steps:
      1. manager = OrderExecutionManager()
      2. signal = Signal(type='LONG', quantity=0.5) (large position)
      3. current_balance = 10000 USDT
      4. position_value = 0.5 * 40000 = 20000 (50% of balance, exceeds 30%)
      5. valid = manager.validate_signal(signal)
      6. assert valid == False (exceeds max_position_pct)
      7. assert manager.validation_error == "Position exceeds max_position_pct"
      8. order = manager.execute_signal(signal)
      9. assert order is None (order not executed)
    Expected Result: Oversized position rejected by risk validation
    Failure Indicators: Oversized position executed, validation bypassed
    Evidence: .sisyphus/evidence/task-23-risk-validation.log

  Scenario: Order timeout handling
    Tool: Bash (Python script)
    Preconditions: Order execution with timeout
    Steps:
      1. manager = OrderExecutionManager(timeout=60)
      2. order = manager.execute_signal(signal)
      3. order_id = order['id']
      4. Wait for 60 seconds (simulate unfilled order)
      5. manager.monitor_order(order_id)
      6. After 60s, assert order status = 'cancelled' (timeout triggered)
      7. assert audit event: 'order_timeout_cancel'
      8. Retry: new_order = manager.retry_order(signal)
      9. assert new_order created
    Expected Result: Unfilled order cancelled after timeout, retry executed
    Failure Indicators: Order not cancelled, timeout not triggered
    Evidence: .sisyphus/evidence/task-23-order-timeout.log
  ```

  **Evidence to Capture**:
  - [ ] Signal execution output with order creation
  - [ ] Risk validation rejection for oversized position
  - [ ] Order timeout handling log

  **Commit**: YES (Wave 3 partial)
  - Message: `feat(live): order execution manager with risk validation and timeout`
  - Files: live/execution.py, tests/test_execution.py
  - Pre-commit: `pytest tests/test_execution.py`

- [ ] 24. Live Trading - Position tracker

  **What to do**:
  - Create live/position_tracker.py with PositionTracker class
  - Implement position creation: create_position() when order fills
  - Add position tracking: track open positions (symbol, quantity, entry_price, current_value)
  - Create position update: update position value each tick (current_price * quantity)
  - Implement position PnL calculation: unrealized_pnl = (current_price - entry_price) * quantity
  - Add position status monitoring: check if position active, closed, or liquidated
  - Create position history: record all position events (open, close, stop-loss trigger)
  - Implement position query: query positions by symbol, status, date

  **Must NOT do**:
  - Track positions without entry price (must record entry for PnL calculation)
  - Allow position tracking to drift from real positions (must sync with OKX positions)
  - Implement position tracking without logging (must log all position events)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Critical for monitoring live positions, requires accurate tracking
  - **Skills**: []
    - No special skills needed, standard position tracking

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 17-23, 25)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 25, 17 (manual confirmation and kill switch depend on position tracker)
  - **Blocked By**: Task 23 (needs order execution for position creation)

  **References**:
  - Position tracking: symbol, quantity, entry_price, current_value
  - PnL calculation: unrealized_pnl = (current_price - entry_price) * quantity
  - Position status: active, closed, liquidated, stop_loss_triggered
  - Position sync: match tracker positions with OKX open positions

  **Acceptance Criteria**:
  - [ ] live/position_tracker.py exists with PositionTracker
  - [ ] create_position() when order fills
  - [ ] Position tracking: symbol, quantity, entry_price, current_value
  - [ ] Position update each tick
  - [ ] PnL calculation: unrealized_pnl
  - [ ] Position status monitoring
  - [ ] Position history recording
  - [ ] Position query by criteria

  **QA Scenarios**:

  ```
  Scenario: Position creation on order fill
    Tool: Bash (Python script)
    Preconditions: Order filled, position tracker active
    Steps:
      1. from live.position_tracker import PositionTracker
      2. tracker = PositionTracker()
      3. order_fill_event = {'symbol': 'BTC/USDT', 'side': 'buy', 'quantity': 0.01, 'price': 40000, 'order_id': '123'}
      4. position = tracker.create_position(order_fill_event)
      5. assert position['symbol'] == 'BTC/USDT'
      6. assert position['quantity'] == 0.01
      7. assert position['entry_price'] == 40000
      8. assert position['status'] == 'active'
      9. assert position['entry_value'] == 400 (40000 * 0.01)
      10. Check tracker positions: assert len(tracker.positions) == 1
    Expected Result: Position created on order fill with correct entry data
    Failure Indicators: Position not created, wrong entry data, missing fields
    Evidence: .sisyphus/evidence/task-24-position-create.log

  Scenario: Position PnL calculation
    Tool: Bash (Python script)
    Preconditions: Active position, price update
    Steps:
      1. tracker has position: BTC/USDT, quantity=0.01, entry_price=40000
      2. Current price = 42000 (price increased)
      3. tracker.update_position_value(symbol='BTC/USDT', current_price=42000)
      4. position = tracker.get_position('BTC/USDT')
      5. assert position['current_value'] == 420 (42000 * 0.01)
      6. assert position['unrealized_pnl'] == 20 (420 - 400)
      7. assert position['pnl_pct'] == 5% (20/400)
      8. Current price = 38000 (price decreased)
      9. tracker.update_position_value(symbol='BTC/USDT', current_price=38000)
      10. assert position['unrealized_pnl'] == -20 (380 - 400)
    Expected Result: PnL calculated correctly for price changes
    Failure Indicators: Wrong PnL, incorrect percentage, missing calculation
    Evidence: .sisyphus/evidence/task-24-pnl-calc.log

  Scenario: Position sync with OKX
    Tool: Bash (Python script)
    Preconditions: Live positions on OKX, tracker positions
    Steps:
      1. tracker = PositionTracker()
      2. okx_positions = client.fetch_positions() (from OKX API)
      3. tracker.sync_positions(okx_positions)
      4. assert tracker.positions match okx_positions
      5. If OKX has 2 positions, tracker should have 2 positions
      6. If OKX position closed, tracker position should be closed
      7. Check sync validation: assert tracker.validate_sync()
    Expected Result: Tracker positions synced with OKX positions
    Failure Indicators: Mismatch between tracker and OKX, sync validation fails
    Evidence: .sisyphus/evidence/task-24-position-sync.log
  ```

  **Evidence to Capture**:
  - [ ] Position creation log with entry data
  - [ ] PnL calculation output for price changes
  - [ ] Position sync validation results

  **Commit**: YES (Wave 3 partial)
  - Message: `feat(live): position tracker with PnL calculation and OKX sync`
  - Files: live/position_tracker.py, tests/test_position_tracker.py
  - Pre-commit: `pytest tests/test_position_tracker.py`

- [ ] 25. Live Trading - Manual confirmation mechanism

  **What to do**:
  - Create live/confirmation.py with ManualConfirmation class
  - Implement confirmation requirement: require manual confirmation for first live trade
  - Add confirmation prompt: display signal details, ask for user approval (yes/no)
  - Create confirmation timeout: cancel if no response within 30 seconds
  - Implement confirmation logging: log all confirmation events (approved, rejected, timeout)
  - Add confirmation bypass: after N successful trades, auto-confirm subsequent trades
  - Create confirmation audit: record who approved/rejected each trade
  - Implement emergency rejection: reject all signals if kill switch active

  **Must NOT do**:
  - Execute live trades without confirmation (first trade must be manually confirmed)
  - Allow confirmation bypass on day 1 (must require manual confirmation initially)
  - Execute trades during kill switch safe mode (must reject all signals)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple confirmation logic, user prompt and logging
  - **Skills**: []
    - No special skills needed, standard user interaction

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 17-24)
  - **Parallel Group**: Wave 3
  - **Blocks**: None (confirmation is safety layer, doesn't block other tasks)
  - **Blocked By**: Task 23 (needs order execution to confirm)

  **References**:
  - Manual confirmation: first live trade requires user approval
  - Confirmation prompt: display signal, ask yes/no
  - Confirmation timeout: 30 seconds, cancel if no response
  - Confirmation bypass: after N successful trades, auto-confirm

  **Acceptance Criteria**:
  - [ ] live/confirmation.py exists with ManualConfirmation
  - [ ] Confirmation required for first live trade
  - [ ] Confirmation prompt displays signal details
  - [ ] Confirmation timeout: 30 seconds
  - [ ] Confirmation logging: approved/rejected/timeout
  - [ ] Confirmation bypass after N trades
  - [ ] Confirmation audit records
  - [ ] Emergency rejection during kill switch

  **QA Scenarios**:

  ```
  Scenario: First trade manual confirmation
    Tool: interactive_bash (tmux)
    Preconditions: Live trading starting, first trade signal
    Steps:
      1. python cli/main.py --mode live --strategy cta
      2. Signal generated: LONG BTC/USDT at 40000, quantity 0.01
      3. Output: "First live trade detected. Signal details:"
      4. Output: "LONG BTC/USDT | Price: 40000 | Quantity: 0.01 | Value: 400 USDT"
      5. Output: "Approve this trade? (yes/no) [timeout: 30s]"
      6. Input: 'yes'
      7. Assert output: "Trade approved. Executing..."
      8. Assert order created
      9. Assert audit record: 'manual_confirmation_approved'
    Expected Result: First trade requires manual confirmation, approved on 'yes'
    Failure Indicators: Trade executed without confirmation, timeout not enforced
    Evidence: .sisyphus/evidence/task-25-first-confirm.log

  Scenario: Confirmation timeout
    Tool: interactive_bash (tmux)
    Preconditions: Live trading, confirmation prompt
    Steps:
      1. python cli/main.py --mode live --strategy cta
      2. Signal generated, confirmation prompt displayed
      3. No input for 30 seconds (timeout)
      4. Assert output: "Confirmation timeout. Trade cancelled."
      5. Assert order not created
      6. Assert audit record: 'manual_confirmation_timeout'
      7. Signal retry: new signal generated later
    Expected Result: Confirmation timeout cancels trade, no order created
    Failure Indicators: Trade executed despite timeout, no audit record
    Evidence: .sisyphus/evidence/task-25-confirm-timeout.log

  Scenario: Confirmation bypass after N trades
    Tool: Bash (Python script)
    Preconditions: N successful trades completed (e.g., N=5)
    Steps:
      1. from live.confirmation import ManualConfirmation
      2. confirmation = ManualConfirmation(bypass_after=5)
      3. Execute 5 trades with manual confirmation
      4. After 5 trades, assert confirmation.bypass_enabled == True
      5. New signal generated
      6. response = confirmation.check_confirmation_needed(signal)
      7. assert response['needs_confirmation'] == False (bypass active)
      8. assert output: "Auto-confirming (bypass enabled after 5 successful trades)"
      9. Order executed without prompt
    Expected Result: Confirmation bypassed after N successful trades
    Failure Indicators: Confirmation still required, bypass not activated
    Evidence: .sisyphus/evidence/task-25-confirm-bypass.log
  ```

  **Evidence to Capture**:
  - [ ] First trade manual confirmation output
  - [ ] Confirmation timeout log
  - [ ] Confirmation bypass activation log

  **Commit**: YES (Wave 3 final)
  - Message: `feat(live): manual confirmation mechanism with timeout and bypass`
  - Files: live/confirmation.py, tests/test_confirmation.py
  - Pre-commit: `pytest tests/test_confirmation.py`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `pytest` + `ruff` (Python linter). Review all changed files for: hardcoded secrets, empty catches, print() in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names.
  Output: `Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task. Test cross-task integration. Test edge cases. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Wave 1**: `feat(data): OKX API client and data storage` - data/*.py, pytest data/
- **Wave 2**: `feat(backtest): CTA strategy and backtest engine` - strategy/*.py, backtest/*.py
- **Wave 3**: `feat(risk-cli): Risk management and CLI interface` - risk/*.py, cli/*.py
- **Wave 4**: `feat(live): Paper trading and live trading module` - live/*.py, paper_trading.py
- **Final**: `feat(complete): Statistical arbitrage and final integration` - strategy/stat_arb/*.py

---

## Success Criteria

### Verification Commands
```bash
# Data module
python -m data.manager --download BTC/USDT --days 365
# Expected: data/historical/btc_usdt_1h.parquet created, 8760 rows

# Backtest
python main.py --mode backtest --strategy cta --pair BTC/USDT
# Expected: Sharpe > 1.0, MaxDD < 20%, WinRate > 40%

# Paper trading
python main.py --mode paper --strategy cta --validate 7d
# Expected: No exceptions, all orders logged, risk limits respected

# Kill switch
python main.py --mode paper --test-kill-switch
# Expected: All positions closed < 5s

# CLI
python main.py --status
# Expected: Current positions, balance, strategy state displayed
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] Paper trading validated for 7 days
- [ ] Kill switch tested successfully
- [ ] API keys in environment variables only
- [ ] Audit logs complete for all trades