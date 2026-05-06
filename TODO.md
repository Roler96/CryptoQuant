# CryptoQuant 项目改进 TODO

> 最后更新: 2026-05-06  
> 项目状态: Phase 2 已完成，数据库包含 25K+ 真实数据

---

## 项目现状

| 指标 | 数量 | 备注 |
|------|------|------|
| 源文件 | 43 个 | Python 模块 |
| CLI 命令 | 7 个 | backtest/paper/live/status/config/fetch/kill |
| 数据存储 | 双模式 | File (Parquet) / Database (SQLite/PostgreSQL) |
| 真实数据 | 25,702 条 | 10 交易对 x 3 时间周期 |
| 数据时间范围 | 2025-09-18 至 2026-05-06 | 约 8 个月 |
| 支持交易对 | 10+ | BTC, ETH, BNB, SOL, XRP, DOGE, ADA, AVAX, DOT, LINK |
| 支持时间周期 | 14 个 | 1m-1M 全周期 |
| 回测引擎 | Backtrader | 集成完整指标和可视化 |

---

## 已完成 ✅

### Phase 1: 基础架构 (2026-04-30)
- [x] CLI 命令完整实现 (backtest/paper/live/status/config/kill)
- [x] 测试覆盖率提升 (31%)
- [x] 代码警告清理 (49 → 0)
- [x] 策略框架基础 (StrategyBase, Signal, Position)
- [x] 风控模块 (PositionSizer, StopLossManager)

### Phase 2: 数据层 (2026-05-06) ✅ 完成
- [x] 数据库支持 (SQLite/PostgreSQL)
- [x] 统一存储接口 (File/Database 双模式)
- [x] 增量下载功能
- [x] 批量下载脚本 (download_all_data.py)
- [x] 数据迁移工具
- [x] **移除虚假数据生成** (仅真实 API 数据)
- [x] **数据质量检查** (空值/价格/成交量/时间断层)
- [x] **数据版本管理** (自动版本递增)
- [x] **真实数据获取** (OKX API, 25,702 条)
- [x] **数据库管理工具** (status/validate/reset)

---

## 🔴 P0 - 高优先级

### 1. 回测引擎修复
**状态:** 🔄 进行中  
**影响:** backtest 命令无法运行

**任务:**
- [ ] 修复 Backtrader PandasData 参数兼容性问题
- [ ] 更新数据加载器使用 `data.loader` 模块
- [ ] 测试多周期回测
- [ ] 验证回测结果准确性

---

### 2. 实盘交易连接
**状态:** ⏳ 待开始  
**影响:** 无法执行真实交易

**任务:**
- [ ] 完善 OrderManager 订单执行逻辑
- [ ] 添加订单状态轮询机制
- [ ] 实现持仓同步功能
- [ ] 添加交易确认和日志记录

---

## 🟡 P1 - 中优先级

### 3. 更多策略实现
**状态:** ⏳ 待开始

**任务:**
- [ ] RSI 策略
- [ ] MACD 策略
- [ ] 布林带策略
- [ ] 网格交易策略
- [ ] 套利策略增强

**位置:** `strategy/`

---

### 4. 异步架构改造
**状态:** ⏳ 待开始  
**难度:** 高

**任务:**
- [ ] 改造 `data/manager.py` 为异步
- [ ] 改造 `live/trading.py` 为异步
- [ ] 添加异步事件循环管理
- [ ] 更新测试使用 pytest-asyncio

---

### 5. WebSocket 实时数据
**状态:** ⏳ 待开始  
**难度:** 高

**任务:**
- [ ] 实现 WebSocket 连接管理器
- [ ] 实现实时数据订阅
- [ ] 添加数据回调机制
- [ ] 实现 tick-based 策略支持

**位置:** 新增 `data/websocket.py`

---

### 6. Status 命令完善
**状态:** ⏳ 待开始  
**位置:** `cli/commands/status.py`

**任务:**
- [ ] 实现实时状态查询
- [ ] 添加 WebSocket 状态
- [ ] 添加性能统计显示
- [ ] 显示当前持仓和盈亏

---

## 🟢 P2 - 低优先级

### 7. 类型检查强制化
**状态:** ⏳ 待开始

**任务:**
- [ ] 添加 `mypy.ini` 配置
- [ ] CI 中强制 mypy 检查
- [ ] 修复所有类型错误

---

### 8. 文档完善
**状态:** ⏳ 待开始

**任务:**
- [ ] 添加 API 文档 (Sphinx/MkDocs)
- [ ] 策略开发指南
- [ ] 部署运维文档

---

### 9. CI/CD 流程
**状态:** ⏳ 待开始

**任务:**
- [ ] GitHub Actions 配置
- [ ] Pre-commit hooks 完善
- [ ] 自动发布流程

---

### 10. 监控告警
**状态:** ⏳ 待开始

**任务:**
- [ ] Prometheus metrics 导出
- [ ] Grafana dashboard 配置
- [ ] Telegram 通知集成

---

### 11. 多交易所支持
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
  ✅ 添加核心模块测试
```

### Phase 2: 数据层 ✅ 完成
```
目标: 完整数据支持
完成日期: 2026-05-06
任务:
  ✅ 数据库支持 (SQLite/PostgreSQL)
  ✅ 统一存储接口
  ✅ 增量下载
  ✅ 批量下载脚本
  ✅ 移除虚假数据生成
  ✅ 数据质量检查 (null/price/volume/gap)
  ✅ 数据版本管理
  ✅ 真实数据获取 (25,702 条真实数据)
  ✅ 数据库管理工具 (db_manager.py)
  
数据详情:
  - 10 交易对: BTC, ETH, BNB, SOL, XRP, DOGE, ADA, AVAX, DOT, LINK
  - 3 时间周期: 1h, 4h, 1d
  - 时间范围: 2025-09-18 至 2026-05-06
  - 数据来源: OKX 交易所
  - 总记录: 25,702 条
```

### Phase 3: 核心功能修复 🔄 进行中
```
目标: 回测和交易可用
预计时间: 1-2 周
任务:
  🔄 修复回测引擎
  ⏳ 实盘交易连接
```

### Phase 4: 高级功能 ⏳ 待开始
```
目标: 生产就绪
预计时间: 4-8 周
任务:
  ⏳ 异步架构
  ⏳ WebSocket 实时数据
  ⏳ 更多策略
  ⏳ 完整测试覆盖 (>80%)
  ⏳ CI/CD 流程
  ⏳ 监控告警
```

---

## 快速命令

```bash
# 配置环境
cp .env.example .env
# 编辑 .env 添加 OKX API 密钥

# 数据管理
python scripts/db_manager.py status     # 查看数据库状态
python scripts/db_manager.py validate   # 验证数据质量
python scripts/db_manager.py reset      # 重置数据库

# 下载数据
python scripts/fetch_real_data.py       # 获取单条数据
python scripts/batch_fetch.py           # 批量下载
python scripts/enhance_data.py          # 增强数据 (90天历史)
python -m cli.main fetch --pair BTC/USDT --timeframe 1h

# 数据迁移
python scripts/migrate_all_data.py

# 运行回测
python -m cli.main backtest --strategy cta --pair BTC/USDT --timeframe 1h --days 30

# 模拟交易
python -m cli.main paper --strategy cta --pair BTC/USDT --duration 24

# 实盘交易 (需 API 密钥)
python -m cli.main live --strategy cta --pair BTC/USDT --dry-run

# 代码质量检查
ruff check . --fix
black .
mypy . --ignore-missing-imports
pytest tests/ -v
```

---

## 进度追踪

| 任务 | 状态 | 开始日期 | 完成日期 |
|------|------|----------|----------|
| 清理代码警告 | ✅ | 2026-04-30 | 2026-04-30 |
| CLI 实现 | ✅ | 2026-04-30 | 2026-04-30 |
| 测试覆盖率 | ✅ | 2026-04-30 | 2026-04-30 |
| 数据库支持 | ✅ | 2026-05-06 | 2026-05-06 |
| 数据下载 | ✅ | 2026-05-06 | 2026-05-06 |
| 移除虚假数据 | ✅ | 2026-05-06 | 2026-05-06 |
| 数据质量检查 | ✅ | 2026-05-06 | 2026-05-06 |
| 数据版本管理 | ✅ | 2026-05-06 | 2026-05-06 |
| 真实数据获取 | ✅ | 2026-05-06 | 2026-05-06 |
| 数据库管理工具 | ✅ | 2026-05-06 | 2026-05-06 |
| 回测引擎修复 | 🔄 | - | - |
| 实盘交易连接 | ⏳ | - | - |
| 异步架构 | ⏳ | - | - |
| WebSocket | ⏳ | - | - |

---

## 文件结构

```
cryptoquant/
├── cli/                    # 命令行接口
├── config/                 # 配置文件
├── data/                   # 数据层
│   ├── database.py         # 数据库管理
│   ├── loader.py           # 统一存储接口
│   ├── manager.py          # OKX API 客户端
│   ├── models.py           # 数据模型
│   └── storage.py          # Parquet 存储
├── strategy/               # 策略框架
├── backtest/               # 回测引擎
├── live/                   # 实盘交易
├── risk/                   # 风险管理
├── logs/                   # 日志审计
├── scripts/                # 工具脚本
│   ├── fetch_real_data.py      # 真实数据获取
│   ├── batch_fetch.py          # 批量下载
│   ├── enhance_data.py         # 数据增强
│   ├── db_manager.py           # 数据库管理
│   ├── download_all_data.py    # 全量下载
│   ├── migrate_data.py         # 数据迁移
│   └── migrate_all_data.py     # 批量迁移
└── tests/                  # 测试套件
```

---

## 数据库详情

### 数据表
- `ohlcv_candles`: OHLCV 价格数据
- `data_versions`: 数据版本和元数据
- `data_quality`: 数据质量检查结果

### 数据覆盖
```
交易对: 10 个主流币种
  BTC/USDT  - 比特币
  ETH/USDT  - 以太坊
  BNB/USDT  - 币安币
  SOL/USDT  - Solana
  XRP/USDT  - Ripple
  DOGE/USDT - 狗狗币
  ADA/USDT  - Cardano
  AVAX/USDT - Avalanche
  DOT/USDT  - Polkadot
  LINK/USDT - Chainlink

时间周期: 3 个常用周期
  1h  - 1小时 (约 1,500-2,200 条/对)
  4h  - 4小时 (约 400-600 条/对)
  1d  - 1天   (约 100-200 条/对)

统计:
  总记录数: 25,702
  时间跨度: 2025-09-18 至 2026-05-06 (约 8 个月)
  数据来源: OKX 交易所真实数据
  数据质量: 100% 验证通过
```

---

## 备注

- 状态标记: ✅ 完成 | 🔄 进行中 | ⏳ 待开始 | ❌ 阻塞
- 优先级: 🔴 P0 | 🟡 P1 | 🟢 P2
- 虚假数据生成已移除，项目现在只支持真实 API 数据
- 数据库配置: `config/config.yaml` 中 `storage_mode: database`
- API 密钥配置: `.env` 文件中 `OKX_*` 相关配置
