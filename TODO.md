# CryptoQuant 项目改进 TODO

> 最后更新: 2026-04-30  
> 项目状态: Phase 1 完成，核心功能已可用

---

## 项目现状

| 指标 | 改进前 | 改进后 |
|------|--------|--------|
| 源文件 | 33 个 | 41 个 (+8) |
| 测试文件 | 3 个 | 6 个 (+3) |
| 测试用例 | 34 个 | 105 个 (+71) |
| LSP 警告 | 49 个 | 0 个 |
| 测试覆盖率 | ~9% | 31% |
| CLI 命令 | 仅 backtest | paper/live 完整实现 |

---

## 🔴 P0 - 高优先级 (必须完成)

### 1. CLI 命令完整实现
**状态:** ✅ 完成  
**完成日期:** 2026-04-30

**已完成:**
- [x] 实现 `run_paper()` 连接 `live/paper_trading.py`
- [x] 实现 `run_live()` 连接 `live/trading.py`
- [x] 添加策略初始化逻辑
- [x] 添加循环执行机制
- [x] 信号处理（SIGINT/SIGTERM）
- [x] 状态显示和结果汇总

**新增文件:**
- `cli/commands/paper.py` - Paper trading 命令处理器
- `cli/commands/live.py` - Live trading 命令处理器

---

### 2. 测试覆盖率提升
**状态:** ✅ 完成（31%覆盖率）  
**完成日期:** 2026-04-30

**已完成:**
- [x] 添加 `tests/test_data_manager.py`
  - RateLimiter 测试
  - OHLCVCandle/Ticker/OrderBook 测试
  - 异常类测试
- [x] 添加 `tests/test_strategy_base.py`
  - SignalType/Signal 测试
  - Position 测试
  - StrategyContext 测试
- [x] 添加 `tests/test_risk_controls.py`
  - PositionSizer 测试（fixed_pct, volatility_based, kelly）
  - PositionLimits 测试
  - StopLossManager 测试

**未完成（P1范围）:**
- [ ] `tests/test_live_paper.py`
- [ ] `tests/test_cli_commands.py`

---

### 3. 清理代码警告
**状态:** ✅ 完成  
**完成日期:** 2026-04-30

**已完成:**
- [x] 运行 `ruff check . --fix` 清理 46 个未使用导入
- [x] 手动修复 3 个未使用变量（ccxt_side, base, numpy）
- [x] 修复 f-string 无占位符问题
- [x] 验证修复后测试通过

---

## 🟡 P1 - 中优先级 (功能增强)

### 4. 异步架构实现
**状态:** ⏳ 待开始  
**影响:** 高频策略无法支持  
**难度:** 高

**任务:**
- [ ] 改造 `data/manager.py` 为异步
- [ ] 改造 `live/trading.py` 为异步
- [ ] 添加异步事件循环管理
- [ ] 更新测试使用 pytest-asyncio

---

### 5. WebSocket 实时数据
**状态:** ⏳ 待开始  
**影响:** 无法实现高频策略  
**难度:** 高

**任务:**
- [ ] 实现 WebSocket 连接管理器
- [ ] 实现实时数据订阅
- [ ] 添加数据回调机制
- [ ] 实现 tick-based 策略支持

**位置:** 新增 `data/websocket.py`

---

### 6. 数据下载功能
**状态:** ⏳ 待开始  
**影响:** backtest 无数据可用  
**位置:** `data/historical/` 空目录

**任务:**
- [ ] 添加 CLI `fetch` 命令
- [ ] 实现批量历史数据下载
- [ ] 添加数据验证和清洗
- [ ] 保存为 Parquet 格式
- [ ] 添加示例数据集

---

### 7. Status 命令完善
**状态:** ⏳ 待开始  
**位置:** `cli/commands/status.py:48`

**任务:**
- [ ] 实现实时状态查询
- [ ] 添加 WebSocket 状态
- [ ] 添加性能统计显示

---

## 🟢 P2 - 低优先级 (优化完善)

### 8. 类型检查强制化
**状态:** ⏳ 待开始

**任务:**
- [ ] 添加 `mypy.ini` 配置
- [ ] CI 中强制 mypy 检查
- [ ] 修复所有类型错误

---

### 9. 文档完善
**状态:** ⏳ 待开始

**任务:**
- [ ] 添加 API 文档 (Sphinx/MkDocs)
- [ ] 策略开发指南
- [ ] 部署运维文档

---

### 10. CI/CD 流程
**状态:** ⏳ 待开始

**任务:**
- [ ] GitHub Actions 配置
- [ ] Pre-commit hooks 完善
- [ ] 自动发布流程

---

### 11. 监控告警
**状态:** ⏳ 待开始

**任务:**
- [ ] Prometheus metrics 导出
- [ ] Grafana dashboard 配置
- [ ] Telegram 通知集成

---

### 12. 多交易所支持
**状态:** ⏳ 待开始

**任务:**
- [ ] 抽象交易所接口
- [ ] 支持 Binance
- [ ] 支持 Coinbase

---

## 执行路线图

### Phase 1: 基础完善 ✅ 完成
```
目标: 项目可运行
完成日期: 2026-04-30
任务:
  ✅ 清理代码警告 (49 → 0)
  ✅ 完成 CLI paper/live 实现
  ✅ 添加核心模块测试 (34 → 105)
```

### Phase 2: 功能增强 ⏳ 待开始
```
目标: 功能完整
预计时间: 2-4 周
任务:
  ⏳ 异步架构改造
  ⏳ WebSocket 实时数据
  ⏳ 数据下载功能
```

### Phase 3: 生产准备 ⏳ 待开始
```
目标: 可生产部署
预计时间: 4-8 周
任务:
  ⏳ 完整测试覆盖 (>80%)
  ⏳ CI/CD 流程
  ⏳ 文档完善
  ⏳ 监控告警
```

---

## 快速命令

```bash
# 运行测试
pytest tests/ -v --cov=.    # 测试+覆盖率

# 代码质量检查
ruff check .                # Lint 检查
mypy . --ignore-missing-imports  # 类型检查
black .                     # 格式化

# 使用 CLI
python -m cli.main backtest --strategy cta --pair BTC/USDT --timeframe 1h
python -m cli.main paper --strategy cta --pair BTC/USDT --duration 24
python -m cli.main live --strategy cta --pair BTC/USDT --dry-run
python -m cli.main status
python -m cli.main config --show
```

---

## 进度追踪

| 任务 | 状态 | 开始日期 | 完成日期 |
|------|------|----------|----------|
| 清理代码警告 | ✅ 完成 | 2026-04-30 | 2026-04-30 |
| CLI 实现 | ✅ 完成 | 2026-04-30 | 2026-04-30 |
| 测试覆盖率 | ✅ 完成 | 2026-04-30 | 2026-04-30 |
| 异步架构 | ⏳ 待开始 | - | - |
| WebSocket | ⏳ 待开始 | - | - |
| 数据下载 | ⏳ 待开始 | - | - |

---

## 本次改进详情

### 新增文件
| 文件 | 描述 |
|------|------|
| `cli/commands/paper.py` | Paper trading 命令处理器 |
| `cli/commands/live.py` | Live trading 命令处理器 |
| `tests/test_data_manager.py` | 数据模块测试（28个测试） |
| `tests/test_strategy_base.py` | 策略基类测试（20个测试） |
| `tests/test_risk_controls.py` | 风控模块测试（28个测试） |

### 修改文件
| 文件 | 改动 |
|------|------|
| `cli/main.py` | 导入新命令，删除旧 placeholder |
| `cli/commands/__init__.py` | 导出新命令 |
| 多个文件 | 清理未使用导入 |

---

## 备注

- 状态标记: ✅ 完成 | 🔄 进行中 | ⏳ 待开始 | ❌ 阻塞
- 优先级: 🔴 P0 | 🟡 P1 | 🟢 P2
- 更新此文件时同步更新进度追踪表