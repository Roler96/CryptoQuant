# CryptoQuant 项目改进 TODO

> 最后更新: 2026-04-30  
> 项目状态: 开发中，核心功能待完善

---

## 项目现状

| 指标 | 状态 |
|------|------|
| 源文件 | 33 个 Python 文件 |
| 测试文件 | 3 个 (覆盖率低) |
| 测试用例 | 34 个 (仅覆盖 backtest) |
| LSP 警告 | 49 个 (未使用导入) |
| 大文件 | 10 个 (>500行) |
| 异步支持 | 未实现 |
| WebSocket | 未实现 |

---

## 🔴 P0 - 高优先级 (必须完成)

### 1. CLI 命令完整实现
**状态:** 🔴 未完成  
**影响:** 用户无法使用 paper/live 模式  
**位置:** `cli/main.py:295, 334`

**任务:**
- [ ] 实现 `run_paper()` 连接 `live/paper_trading.py`
- [ ] 实现 `run_live()` 连接 `live/trading.py`
- [ ] 添加策略初始化逻辑
- [ ] 添加循环执行机制
- [ ] 测试命令端到端流程

**相关文件:**
- `cli/main.py` - 入口
- `live/paper_trading.py` - 模拟交易 (667行)
- `live/trading.py` - 实盘交易 (856行)

---

### 2. 测试覆盖率提升
**状态:** 🔴 严重不足 (仅 9%)  
**影响:** 代码质量无保障  
**目标:** 覆盖率 > 80%

**任务:**
- [ ] 添加 `tests/test_data_manager.py`
  - OKX API 调用测试
  - RateLimiter 测试
  - 异常处理测试
- [ ] 添加 `tests/test_strategy_base.py`
  - StrategyBase 抽象类测试
  - Signal 生成测试
  - Context 处理测试
- [ ] 添加 `tests/test_risk_controls.py`
  - PositionSizer 测试
  - StopLossManager 测试
  - DrawdownMonitor 测试
- [ ] 添加 `tests/test_live_paper.py`
  - PaperTrader 测试
  - 虚拟余额测试
  - P&L 计算测试
- [ ] 添加 `tests/test_cli_commands.py`
  - 各命令参数解析测试
  - 错误处理测试
- [ ] 配置 pytest coverage 报告

---

### 3. 清理代码警告
**状态:** 🔴 49 个警告  
**影响:** 代码整洁度、潜在问题  
**难度:** 低 (自动化)

**任务:**
- [ ] 运行 `ruff check . --fix` 清理未使用导入
- [ ] 修复 f-string 无占位符问题
- [ ] 修复未使用的局部变量
- [ ] 验证修复后测试仍通过

**警告分布:**
```
cli/           - 13 个
data/          - 5 个
live/          - 7 个
backtest/      - 4 个
strategy/      - 2 个
risk/          - 1 个
tests/         - 2 个
logs/          - 1 个
```

---

## 🟡 P1 - 中优先级 (功能增强)

### 4. 异步架构实现
**状态:** 🟡 未实现  
**影响:** 高频策略无法支持  
**难度:** 高

**任务:**
- [ ] 改造 `data/manager.py` 为异步
  - 使用 aiohttp 替代同步请求
  - async fetch_ohlcv, fetch_ticker
- [ ] 改造 `live/trading.py` 为异步
  - async execute_signal
  - async monitor_positions
- [ ] 添加异步事件循环管理
- [ ] 更新测试使用 pytest-asyncio

**依赖:** requirements.txt 已包含 asyncio 相关包

---

### 5. WebSocket 实时数据
**状态:** 🟡 未实现  
**影响:** 无法实现高频策略  
**难度:** 高

**任务:**
- [ ] 实现 WebSocket 连接管理器
  - OKX WebSocket API 集成
  - 连接保活/重连逻辑
- [ ] 实现实时数据订阅
  - ticker 实时推送
  - orderbook 实时推送
  - OHLCV 实时推送
- [ ] 添加数据回调机制
- [ ] 实现 tick-based 策略支持

**位置:** 新增 `data/websocket.py`

---

### 6. 数据下载功能
**状态:** 🟡 缺失  
**影响:** backtest 无数据可用  
**位置:** `data/historical/` 空目录

**任务:**
- [ ] 添加 CLI `fetch` 命令
  - `python -m cli.main fetch --pair BTC/USDT --timeframe 1h --days 30`
- [ ] 实现批量历史数据下载
- [ ] 添加数据验证和清洗
- [ ] 保存为 Parquet 格式
- [ ] 添加示例数据集 (README 引用)

---

### 7. Status 命令完善
**状态:** 🟡 placeholder 实现  
**位置:** `cli/commands/status.py:48`

**任务:**
- [ ] 实现实时状态查询
  - 当前持仓显示
  - 余额显示
  - 策略状态
- [ ] 添加 WebSocket 状态 (如果实现)
- [ ] 添加性能统计显示

---

## 🟢 P2 - 低优先级 (优化完善)

### 8. 类型检查强制化
**状态:** 🟢 有注解但未强制  
**影响:** 类型错误可能遗漏

**任务:**
- [ ] 添加 `mypy.ini` 配置
- [ ] CI 中强制 mypy 检查
- [ ] 修复所有类型错误
- [ ] 添加 strict 模式

---

### 9. 文档完善
**状态:** 🟢 仅 README  
**影响:** 新用户上手困难

**任务:**
- [ ] 添加 API 文档 (Sphinx/MkDocs)
- [ ] 策略开发指南
- [ ] 部署运维文档
- [ ] 配置参数说明
- [ ] 添加 `docs/` 目录

---

### 10. CI/CD 流程
**状态:** 🟢 无  
**影响:** 手动测试易遗漏

**任务:**
- [ ] GitHub Actions 配置
  - 自动测试运行
  - coverage 报告
  - lint/type check
- [ ] Pre-commit hooks 完善
- [ ] 自动发布流程

---

### 11. 监控告警
**状态:** 🟢 部分实现  
**位置:** requirements.txt 有 prometheus-client

**任务:**
- [ ] Prometheus metrics 导出
- [ ] Grafana dashboard 配置
- [ ] Telegram 通知集成
- [ ] 异常告警机制

---

### 12. 多交易所支持
**状态:** 🟢 仅 OKX  
**影响:** 限制应用范围

**任务:**
- [ ] 抽象交易所接口
- [ ] 支持 Binance
- [ ] 支持 Coinbase
- [ ] 配置文件多交易所设置

---

## 执行路线图

### Phase 1: 基础完善 (1-2 周)
```
目标: 项目可运行
任务:
  ✅ 清理代码警告
  🔄 完成 CLI paper/live 实现
  ⏳ 添加核心模块测试
```

### Phase 2: 功能增强 (2-4 周)
```
目标: 功能完整
任务:
  ⏳ 异步架构改造
  ⏳ WebSocket 实时数据
  ⏳ 数据下载功能
```

### Phase 3: 生产准备 (4-8 周)
```
目标: 可生产部署
任务:
  ⏳ 完整测试覆盖 (>80%)
  ⏳ CI/CD 流程
  ⏳ 文档完善
  ⏳ 监控告警
```

---

## 快速命令

```bash
# 立即可执行的改进
ruff check . --fix          # 清理警告
pytest tests/ -v --cov=.    # 测试+覆盖率
mypy . --ignore-missing-imports  # 类型检查
black .                     # 格式化
```

---

## 进度追踪

| 任务 | 状态 | 开始日期 | 完成日期 |
|------|------|----------|----------|
| 清理代码警告 | ⏳ 待开始 | - | - |
| CLI 实现 | ⏳ 待开始 | - | - |
| 测试覆盖率 | ⏳ 待开始 | - | - |
| 异步架构 | ⏳ 待开始 | - | - |
| WebSocket | ⏳ 待开始 | - | - |

---

## 备注

- 状态标记: ✅ 完成 | 🔄 进行中 | ⏳ 待开始 | ❌ 阻塞
- 优先级: 🔴 P0 | 🟡 P1 | 🟢 P2
- 更新此文件时同步更新进度追踪表