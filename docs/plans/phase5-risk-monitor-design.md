# Phase 5: Risk Management + Monitoring — 详细设计文档

> **版本:** 1.0 | **日期:** 2026-06-10 | **作者:** Hermes + Roler

---

## 1. 概述

Phase 5 是最后一块拼图。风控层在信号和下单之间做最后一道防线；监控层负责所有可观测性（日志、交易记录、PnL 报告）。

```
Strategy.generate_signal()
        │
        ▼
┌───────────────────────────────┐
│       RiskManager              │
│  ┌─────────────────────────┐  │
│  │ can_enter(symbol, side)  │  │  ← LiveEngine 调用
│  │ can_exit(symbol, side)   │  │
│  │ position_size(balance)  │  │  ← 委托给 Sizer
│  └─────────────────────────┘  │
│  ┌─────────────────────────┐  │
│  │ Sizer                    │  │
│  │  fixed / kelly / atr    │  │
│  └─────────────────────────┘  │
└───────────────┬───────────────┘
                │ approved
                ▼
        Broker.place_order()
                │
                ▼
┌───────────────────────────────┐
│         Monitor                │
│  ├── logger (loguru)          │
│  ├── TradeJournal             │
│  └── Reporter (PnL summary)  │
└───────────────────────────────┘
```

---

## 2. Position Sizer 设计 (sizer.py)

### 2.1 三种方法

```python
# cryptoquant/risk/sizer.py
from abc import ABC, abstractmethod
from enum import Enum
import math

import numpy as np
import pandas as pd


class SizerMethod(str, Enum):
    FIXED = "fixed"           # 固定比例
    KELLY = "kelly"           # 凯利公式
    ATR = "atr"               # 波动率调整


class PositionSizer(ABC):
    """仓位计算抽象基类。"""

    @abstractmethod
    def calculate(
        self,
        balance: float,
        price: float,
        **kwargs,
    ) -> float:
        """计算仓位大小。

        Args:
            balance: 账户可用余额（USDT）
            price: 当前价格

        Returns:
            下单金额（USDT），总是 >= min_order 且 <= balance
        """
        ...


class FixedSizer(PositionSizer):
    """固定比例仓位。

    position = balance * risk_pct / 100
    """

    def __init__(self, risk_pct: float = 100.0, min_order: float = 10.0):
        self.risk_pct = risk_pct
        self.min_order = min_order

    def calculate(self, balance: float, price: float, **kwargs) -> float:
        amount = balance * self.risk_pct / 100
        return max(self.min_order, amount)


class KellySizer(PositionSizer):
    """凯利公式仓位。

    f* = win_rate - (1 - win_rate) / (avg_win / avg_loss)
    position = balance * f* * fraction

    其中 fraction 是凯利分数的折扣系数（通常 0.25-0.5），
    因为纯凯利波动太大，半凯利更稳健。

    参数可通过 update_from_trades() 动态更新。
    """

    def __init__(
        self,
        win_rate: float = 0.5,
        avg_win_pct: float = 2.0,
        avg_loss_pct: float = 1.0,
        fraction: float = 0.5,
        min_order: float = 10.0,
        max_pct: float = 100.0,
        lookback_trades: int = 50,
    ):
        self.win_rate = win_rate
        self.avg_win_pct = avg_win_pct
        self.avg_loss_pct = avg_loss_pct
        self.fraction = fraction
        self.min_order = min_order
        self.max_pct = max_pct
        self.lookback_trades = lookback_trades

    def calculate(self, balance: float, price: float, **kwargs) -> float:
        # 防御性计算：处理各种边界情况
        if self.avg_loss_pct <= 0 or self.avg_win_pct <= 0:
            # 无盈利或无亏损数据 → 使用保守默认值
            kelly = 0.0
        else:
            b = self.avg_win_pct / self.avg_loss_pct  # 盈亏比
            if b <= 0:
                kelly = 0.0
            else:
                kelly = self.win_rate - (1 - self.win_rate) / b

        kelly = max(0.0, min(kelly, 1.0))  # 限制在 [0, 1]

        position_pct = min(kelly * self.fraction * 100, self.max_pct)
        amount = balance * position_pct / 100
        return max(self.min_order, amount)

    def update_from_trades(self, trades: list[dict]) -> None:
        """从最近 N 笔交易动态更新凯利参数。

        Args:
            trades: 交易记录列表，每条包含 {"pnl_pct": float}
        """
        recent = trades[-self.lookback_trades:]
        if len(recent) < 10:
            return  # 数据不足，保持默认参数

        wins = [t for t in recent if t.get("pnl_pct", 0) > 0]
        losses = [t for t in recent if t.get("pnl_pct", 0) <= 0]

        # 全赢或全亏时不更新（避免除零或极端凯利值）
        if not wins or not losses:
            logger.debug(
                f"Kelly update skipped: {len(wins)} wins, {len(losses)} losses "
                f"(need both to compute)"
            )
            return

        self.win_rate = len(wins) / len(recent)
        self.avg_win_pct = sum(t["pnl_pct"] for t in wins) / len(wins)
        self.avg_loss_pct = abs(sum(t["pnl_pct"] for t in losses) / len(losses))

        # 安全检查：确保更新后的参数有效
        if self.avg_win_pct <= 0 or self.avg_loss_pct <= 0 or not np.isfinite(self.win_rate):
            logger.warning("Kelly update produced invalid params, keeping previous values")
            return


class ATRSizer(PositionSizer):
    """波动率调整仓位。

    核心公式:
        risk_amount = balance * base_risk_pct / 100
        position_size = risk_amount / (ATR * multiplier)

    等价于:
        position_pct = base_risk_pct / (ATR_pct * multiplier)

    其中 ATR_pct = ATR / price * 100 (波动率百分比)
    multiplier 控制风险敏感度，默认 1.0

    示例 (base_risk_pct=10%, multiplier=1.0):
    - ATR_pct = 2%  → position_pct = 10% / 2% = 500% → 上限 100%
    - ATR_pct = 5%  → position_pct = 10% / 5% = 200% → 上限 100%
    - ATR_pct = 10% → position_pct = 10% / 10% = 100%
    - ATR_pct = 20% → position_pct = 10% / 20% = 50%
    """

    def __init__(
        self,
        base_risk_pct: float = 10.0,
        atr_period: int = 14,
        multiplier: float = 1.0,
        min_order: float = 10.0,
        max_pct: float = 100.0,
    ):
        self.base_risk_pct = base_risk_pct
        self.atr_period = atr_period
        self.multiplier = multiplier
        self.min_order = min_order
        self.max_pct = max_pct

    def calculate(
        self,
        balance: float,
        price: float,
        df: pd.DataFrame | None = None,
        **kwargs,
    ) -> float:
        if df is None or len(df) < self.atr_period:
            return balance * self.base_risk_pct / 100

        from cryptoquant.strategy.signals import atr
        atr_val = atr(df, self.atr_period).iloc[-1]

        if pd.isna(atr_val) or atr_val == 0 or price == 0:
            return balance * self.base_risk_pct / 100

        atr_pct = atr_val / price * 100
        position_pct = min(
            self.base_risk_pct / (atr_pct * self.multiplier),
            self.max_pct,
        )
        amount = balance * position_pct / 100
        return max(self.min_order, amount)


def create_sizer(method: SizerMethod, **kwargs) -> PositionSizer:
    """工厂函数。"""
    sizers = {
        SizerMethod.FIXED: FixedSizer,
        SizerMethod.KELLY: KellySizer,
        SizerMethod.ATR: ATRSizer,
    }
    return sizers[method](**kwargs)
```

---

## 3. Risk Manager 设计 (manager.py)

### 3.1 类图

```
┌────────────────────────────────────────────────────────────┐
│                     RiskManager                             │
├────────────────────────────────────────────────────────────┤
│ - max_positions: int              # 最大同时持仓数          │
│ - max_daily_trades: int           # 每日最大交易次数        │
│ - max_daily_loss_pct: float       # 每日最大亏损（%）       │
│ - max_daily_loss_abs: float       # 每日最大亏损（USDT）    │
│ - max_per_trade_risk_pct: float   # 单笔最大风险（%）       │
│ - max_drawdown_pct: float         # 累计最大回撤（%）       │
│ - min_balance: float              # 最低余额（低于则停）    │
│ - sizer: PositionSizer            # 仓位计算器              │
│ - _daily_stats: DailyStats        # 当日统计               │
│ - _trade_log: list[TradeRecord]   # 交易记录               │
├────────────────────────────────────────────────────────────┤
│ + can_enter(symbol, side) → (bool, str)                    │
│ + can_exit(symbol, side) → (bool, str)                     │
│ + position_size(balance, price, **kw) → float              │
│ + record_trade(trade)                                       │
│ + get_daily_stats() → DailyStats                            │
│ + reset_daily()                                             │
│ + is_emergency_stop() → bool                                │
└────────────────────────────────────────────────────────────┘
```

### 3.2 完整实现

```python
# cryptoquant/risk/manager.py
import time
from dataclasses import dataclass, field
from datetime import datetime, date

import numpy as np
from loguru import logger

from cryptoquant.exceptions import EmergencyStopError, RiskError


@dataclass
class DailyStats:
    """当日交易统计。"""
    date: str                    # "2026-06-10"
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl_pct: float = 0.0   # 累计盈亏（%）
    total_pnl_abs: float = 0.0   # 累计盈亏（USDT）
    start_balance: float = 0.0
    current_balance: float = 0.0
    max_drawdown_pct: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades * 100

    @property
    def daily_pnl_pct(self) -> float:
        if self.start_balance <= 0:
            return 0.0
        return (self.current_balance / self.start_balance - 1) * 100


class RiskManager:
    """风险管理器。

    在每笔交易前检查多个约束条件。任一条件不满足即拒绝交易。
    """

    def __init__(
        self,
        max_positions: int = 3,
        max_daily_trades: int = 20,
        max_daily_loss_pct: float = 5.0,
        max_daily_loss_abs: float = 500.0,
        max_per_trade_risk_pct: float = 2.0,
        max_drawdown_pct: float = 20.0,
        min_balance: float = 50.0,
        sizer: "PositionSizer | None" = None,
        initial_balance: float = 0.0,
        emergency_cooldown_minutes: int = 60,
    ):
        self.max_positions = max_positions
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_daily_loss_abs = max_daily_loss_abs
        self.max_per_trade_risk_pct = max_per_trade_risk_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.min_balance = min_balance
        self.sizer = sizer
        self.emergency_cooldown_minutes = emergency_cooldown_minutes

        today = date.today().isoformat()
        self._daily_stats = DailyStats(
            date=today,
            start_balance=initial_balance,
            current_balance=initial_balance,
        )
        self._positions: dict[str, str] = {}
        self._emergency_stop = False
        self._emergency_triggered_at: float | None = None
        self._peak_balance = initial_balance

    # ===== 入场检查 =====

    def can_enter(
        self,
        symbol: str,
        side: int,
        current_balance: float,
        current_positions: int = 0,
    ) -> tuple[bool, str]:
        """检查是否可以入场。

        Returns:
            (allowed, reason)
        """

        # 1. 紧急停止
        if self._emergency_stop:
            return False, "emergency stop triggered"

        # 2. 余额不足
        if current_balance < self.min_balance:
            self._trigger_emergency(f"balance {current_balance:.1f} < min {self.min_balance}")
            return False, f"balance below minimum ({current_balance:.1f} < {self.min_balance})"

        # 3. 持仓数上限
        if current_positions >= self.max_positions:
            return False, f"max positions ({self.max_positions}) reached"

        # 4. 已有同 symbol 持仓
        if symbol in self._positions:
            return False, f"already holding {symbol}"

        # 5. 当日交易次数上限
        if self._daily_stats.total_trades >= self.max_daily_trades:
            return False, f"daily trade limit ({self.max_daily_trades}) reached"

        # 6. 当日亏损上限
        if self._daily_stats.total_pnl_abs < -self.max_daily_loss_abs:
            return False, f"daily loss limit ({self.max_daily_loss_abs}) exceeded"

        if self._daily_stats.daily_pnl_pct < -self.max_daily_loss_pct:
            return False, f"daily loss limit ({self.max_daily_loss_pct}%) exceeded"

        # 7. 累计回撤
        if self._peak_balance > 0:
            current_drawdown = (current_balance / self._peak_balance - 1) * 100
            if abs(current_drawdown) > self.max_drawdown_pct:
                self._trigger_emergency(
                    f"max drawdown ({self.max_drawdown_pct}%) exceeded: {abs(current_drawdown):.1f}%"
                )
                return False, f"max drawdown exceeded ({current_drawdown:.1f}%)"

        return True, "ok"

    # ===== 出场检查 =====

    def can_exit(self, symbol: str, side: str) -> tuple[bool, str]:
        """检查是否可以平仓（通常总是允许）。"""
        if symbol not in self._positions:
            return False, f"no position in {symbol}"
        return True, "ok"

    # ===== 仓位大小 =====

    def position_size(
        self,
        balance: float,
        price: float,
        **kwargs,
    ) -> float:
        """计算仓位大小。委托给 Sizer。"""
        if self.sizer:
            return self.sizer.calculate(balance, price, **kwargs)
        return balance * 0.98

    # ===== 记录交易 =====

    def record_entry(self, symbol: str, side: str):
        """记录新开仓。"""
        self._positions[symbol] = side

    def record_exit(self, symbol: str, pnl_pct: float, pnl_abs: float):
        """记录平仓 + 更新统计。"""
        self._positions.pop(symbol, None)
        self._daily_stats.total_trades += 1

        if pnl_pct > 0:
            self._daily_stats.wins += 1
        else:
            self._daily_stats.losses += 1

        self._daily_stats.total_pnl_pct += pnl_pct
        self._daily_stats.total_pnl_abs += pnl_abs

    def update_balance(self, balance: float, calibrate: bool = False):
        """更新当前余额 + 峰值。"""
        if calibrate:
            drift = balance - self._daily_stats.current_balance
            if abs(drift) > 0.01:
                logger.debug(f"Balance calibrated: drift={drift:+.2f} USDT")

        self._daily_stats.current_balance = balance
        if balance > self._peak_balance:
            self._peak_balance = balance

    # ===== 日重置 =====

    def reset_daily(self, new_balance: float):
        """新的一天，重置当日统计。"""
        self._daily_stats = DailyStats(
            date=date.today().isoformat(),
            start_balance=new_balance,
            current_balance=new_balance,
        )
        logger.info(f"Daily stats reset. Balance: {new_balance:.1f} USDT")

    # ===== 紧急停止 =====

    def _trigger_emergency(self, reason: str):
        """触发紧急停止 — 暂停所有新开仓。"""
        if not self._emergency_stop:
            self._emergency_stop = True
            self._emergency_triggered_at = time.time()
            logger.critical(f"EMERGENCY STOP: {reason}")

    def is_emergency_stop(self) -> bool:
        """检查是否处于紧急停止状态。

        自动降级恢复机制：
        - 紧急停止触发后，经过 emergency_cooldown_minutes 分钟冷却期
        - 冷却期结束后自动降级为「半仓限制」模式（max_positions 减半）
        - 不再阻止交易，但限制仓位规模
        - 需要人工 clear_emergency() 完全恢复
        """
        if not self._emergency_stop:
            return False

        if self._emergency_triggered_at is not None:
            elapsed = time.time() - self._emergency_triggered_at
            if elapsed > self.emergency_cooldown_minutes * 60:
                logger.warning(
                    f"Emergency stop cooldown expired ({self.emergency_cooldown_minutes}min), "
                    f"downgrading to half-position mode"
                )
                self._emergency_stop = False
                self.max_positions = max(1, self.max_positions // 2)
                return False

        return True

    def clear_emergency(self):
        """手动清除紧急停止（需要人工确认）。"""
        logger.warning("Emergency stop cleared (manual)")
        self._emergency_stop = False
        self._emergency_triggered_at = None

    # ===== 状态 =====

    def get_daily_stats(self) -> DailyStats:
        return self._daily_stats

    def get_positions(self) -> dict[str, str]:
        return dict(self._positions)
```

### 3.3 风控检查流程图

```
can_enter(symbol, side)
    │
    ├─ 紧急停止？ ──yes──▶ REJECT
    ├─ 余额 < 最低？ ──yes──▶ EMERGENCY STOP + REJECT
    ├─ 持仓数已满？ ──yes──▶ REJECT
    ├─ 已有此币持仓？ ──yes──▶ REJECT
    ├─ 今日交易太多次？ ──yes──▶ REJECT
    ├─ 今日亏太多？ ──yes──▶ REJECT
    ├─ 累计回撤太大？ ──yes──▶ EMERGENCY STOP + REJECT
    └─ 全部通过 ──▶ APPROVED
```

---

## 4. 监控层：日志 (monitor/)

### 4.1 loguru 配置

```python
# cryptoquant/monitor/logger.py
"""统一日志配置。所有模块通过 `from loguru import logger` 使用。"""

import sys
from pathlib import Path

from loguru import logger


def setup_logging(
    level: str = "INFO",
    log_dir: str = "logs",
    rotation: str = "10 MB",
    retention: str = "30 days",
    json_format: bool = False,
):
    """配置 loguru 日志系统。

    Args:
        level: 日志级别 (DEBUG|INFO|WARNING|ERROR|CRITICAL)
        log_dir: 日志目录
        rotation: 文件轮转策略
        retention: 日志保留时间
        json_format: True=JSON 格式（便于日志分析系统消费）
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # 移除默认 handler
    logger.remove()

    # 控制台 handler（彩色）
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # 文件 handler — 全量日志（JSON 格式适合后期分析）
    if json_format:
        logger.add(
            log_path / "cryptoquant_{time:YYYY-MM-DD}.jsonl",
            level="DEBUG",
            format="{time} | {level} | {name}:{function}:{line} | {message}",
            rotation=rotation,
            retention=retention,
            serialize=True,  # JSON
        )
    else:
        logger.add(
            log_path / "cryptoquant_{time:YYYY-MM-DD}.log",
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
            rotation=rotation,
            retention=retention,
        )

    # 错误日志单独文件
    logger.add(
        log_path / "error_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
        rotation=rotation,
        retention=retention,
    )

    logger.info(f"Logging configured: level={level}, dir={log_dir}")

    return logger
```

### 4.3 日志脱敏

防止敏感信息（API Key、账户余额等）泄露到日志文件：

```python
# cryptoquant/monitor/sanitizer.py
import re
from loguru import logger


_SENSITIVE_PATTERNS = [
    (re.compile(r"(api[_-]?key['\":\s=]+)([A-Za-z0-9]{8,})"), r"\1***REDACTED***"),
    (re.compile(r"(secret['\":\s=]+)([A-Za-z0-9]{8,})"), r"\1***REDACTED***"),
    (re.compile(r"(password['\":\s=]+)(\S+)"), r"\1***REDACTED***"),
    (re.compile(r"(passphrase['\":\s=]+)(\S+)"), r"\1***REDACTED***"),
]


def sanitize(message: str) -> str:
    """脱敏日志消息中的敏感信息。"""
    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


class SanitizingLogger:
    """日志脱敏包装器。

    Usage:
        safe_logger = SanitizingLogger(logger)
        safe_logger.info(f"API key: {api_key}")  # key 被替换为 ***REDACTED***
    """

    def __init__(self, base_logger):
        self._logger = base_logger

    def __getattr__(self, name):
        attr = getattr(self._logger, name)
        if callable(attr) and name in ("debug", "info", "warning", "error", "critical"):
            def wrapper(message, *args, **kwargs):
                if isinstance(message, str):
                    message = sanitize(message)
                return attr(message, *args, **kwargs)
            return wrapper
        return attr
```

**在 Broker 等模块中使用：**

```python
from cryptoquant.monitor.sanitizer import SanitizingLogger
from loguru import logger

log = SanitizingLogger(logger)

# 即使不小心打印了 API key，日志中也会显示 ***REDACTED***
log.info(f"Connected with key: {api_key}")
```

### 4.2 日志使用模式

```python
# 各模块使用示例
from loguru import logger

# 策略信号
logger.debug(f"Signal: {signal} for {symbol}")

# 风控决策
logger.info(f"Risk check: {reason} — {'PASS' if passed else 'REJECT'}")

# 交易执行
logger.info(f"ORDER: {side} {symbol} amount={amount:.4f} price={price}")

# 异常
logger.error(f"Order failed: {e}")

# 紧急
logger.critical(f"EMERGENCY STOP: daily loss {loss} exceeds limit")
```

---

## 5. Trade Journal — 交易日志

### 5.1 设计

每笔完成的交易写入独立日志文件，便于事后审计和分析。

```python
# cryptoquant/monitor/journal.py
import json
from pathlib import Path
from datetime import datetime


class TradeJournal:
    """交易日志 — 每笔交易一行 JSON。

    格式：
    {"time": "2026-06-10T14:30:00", "symbol": "BTC/USDT", "side": "long",
     "entry_price": 95000.0, "exit_price": 96000.0, "pnl_pct": 1.05,
     "pnl_abs": 10.5, "exit_reason": "take_profit", "balance_after": 10010.5}

    线程安全: 使用文件锁防止多进程并发写入导致行交错。
    """

    def __init__(self, journal_dir: str = "logs", strategy_name: str = "default"):
        safe_name = strategy_name.replace("/", "_").replace(" ", "_")
        self.journal_path = Path(journal_dir) / f"trade_journal_{safe_name}.jsonl"
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.journal_path.with_suffix(".lock")

    def record(self, trade_data: dict) -> None:
        """追加一条交易记录（线程安全）。"""
        import fcntl

        trade_data["recorded_at"] = datetime.utcnow().isoformat()

        with open(self.journal_path, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(trade_data) + "\n")
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def load_all(self) -> list[dict]:
        """加载全部交易记录。"""
        if not self.journal_path.exists():
            return []
        trades = []
        with open(self.journal_path) as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))
        return trades

    def stats(self) -> dict:
        """交易统计快照。"""
        trades = self.load_all()
        if not trades:
            return {"total": 0}

        wins = [t for t in trades if t.get("pnl_pct", 0) > 0]
        losses = [t for t in trades if t.get("pnl_pct", 0) <= 0]

        return {
            "total": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(trades) * 100 if trades else 0,
            "total_pnl_pct": sum(t.get("pnl_pct", 0) for t in trades),
            "total_pnl_abs": sum(t.get("pnl_abs", 0) for t in trades),
            "avg_win": sum(t.get("pnl_pct", 0) for t in wins) / len(wins) if wins else 0,
            "avg_loss": sum(t.get("pnl_pct", 0) for t in losses) / len(losses) if losses else 0,
            "best_trade": max(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None,
            "worst_trade": min(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None,
        }
```

---

## 6. Reporter — PnL 报告

### 6.1 设计

```python
# cryptoquant/monitor/reporter.py
from datetime import datetime

from cryptoquant.risk.manager import RiskManager


class Reporter:
    """每日/每周 PnL 摘要生成器。"""

    def __init__(self, risk_manager: RiskManager, journal: "TradeJournal"):
        self.risk_manager = risk_manager
        self.journal = journal

    def daily_summary(self) -> str:
        """生成当日交易摘要。"""
        stats = self.risk_manager.get_daily_stats()
        journal_stats = self.journal.stats()

        lines = [
            "━━━ Daily Trading Summary ━━━",
            f"  Date:       {stats.date}",
            f"  Trades:     {stats.total_trades}",
            f"  Win Rate:   {stats.win_rate:.1f}%",
            f"  PnL (%):    {stats.total_pnl_pct:+.2f}%",
            f"  PnL (USDT): {stats.total_pnl_abs:+.2f}",
            f"  Balance:    {stats.current_balance:.2f} USDT",
            f"  Max DD:     {stats.max_drawdown_pct:.2f}%",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]

        # 风控状态
        if self.risk_manager.is_emergency_stop():
            lines.append("  ⚠️  EMERGENCY STOP ACTIVE")

        return "\n".join(lines)

    def weekly_summary(self) -> str:
        """生成最近 7 天摘要。"""
        all_trades = self.journal.load_all()
        if not all_trades:
            return "No trades this week."

        # 按天分组
        from collections import defaultdict
        by_day = defaultdict(list)
        for t in all_trades:
            day = t.get("recorded_at", "")[:10]
            by_day[day].append(t)

        lines = ["━━━ Weekly Trading Summary ━━━"]
        total_pnl = 0
        for day in sorted(by_day.keys())[-7:]:
            day_trades = by_day[day]
            day_pnl = sum(t.get("pnl_pct", 0) for t in day_trades)
            total_pnl += day_pnl
            lines.append(
                f"  {day}: {len(day_trades):2d} trades, "
                f"PnL {day_pnl:+.2f}%"
            )
        lines.append(f"  ─────────────────────────")
        lines.append(f"  Week PnL: {total_pnl:+.2f}%")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
```

---

## 7. Telegram 通知集成（可选）

```python
# cryptoquant/monitor/notifier.py
"""可选：通过 Telegram 发送交易通知。

需要用户在 config.yaml 中配置 telegram 相关参数，
或直接通过 Hermes cron 的 Telegram delivery 实现。
"""

from dataclasses import dataclass


@dataclass
class NotificationConfig:
    """通知配置。"""
    on_entry: bool = True         # 入场时通知
    on_exit: bool = True          # 出场时通知
    on_error: bool = True         # 错误时通知
    on_emergency: bool = True     # 紧急停止时通知
    daily_summary: bool = True    # 每日摘要
    min_pnl_pct: float = 0.5      # 只有盈亏超过此值才通知
```

**实现方式（Phase 5 保持简单）：**

- Hermes cron job（`no_agent=true` 运行策略脚本）天然支持 Telegram delivery
- 独立运行模式（LiveEngine.run()）通过 stdout 打印，由 Hermes 转发
- 不做内置 Telegram SDK 依赖 — 用 Hermes 的平台能力

---

## 8. LiveEngine 集成

### 8.1 修改 tick() 接入风控

```python
# LiveEngine.tick() 中的改动

def tick(self) -> TickResult:
    # ... 前面的代码不变 ...

    if has_position:
        # 平仓前检查
        if self.risk_manager:
            allowed, reason = self.risk_manager.can_exit(
                self.symbol, position.side
            )
            if not allowed:
                logger.warning(f"Exit blocked: {reason}")
                # 平仓通常不阻止，但记录
    else:
        if signal in (1, -1):
            # 入场前风控检查
            if self.risk_manager:
                current_positions = len(self.risk_manager.get_positions())
                balance = self._get_balance()
                allowed, reason = self.risk_manager.can_enter(
                    self.symbol, signal, balance, current_positions
                )
                if not allowed:
                    logger.warning(f"Entry blocked: {reason}")
                    return TickResult(
                        action=TickAction.SKIP,
                        signal=signal,
                        reason=f"risk: {reason}",
                        order=None,
                        balance=balance,
                        timestamp=timestamp,
                    )

                # 通过风控, 计算仓位
                order_amount = self.risk_manager.position_size(
                    balance,
                    df["close"].iloc[-1],
                    df=df,
                )
            else:
                order_amount = self._calculate_position_size(balance)

            return self._enter_position(signal, timestamp, order_amount)

    # ... 后面的代码 ...
```

### 8.2 交易后记录

```python
def _on_exit_complete(self, trade_data: dict):
    """平仓完成后调用。"""
    if self.risk_manager:
        self.risk_manager.record_exit(
            trade_data["symbol"],
            trade_data["pnl_pct"],
            trade_data["pnl_abs"],
        )
        self.risk_manager.update_balance(trade_data["balance_after"])

        # 动态更新 Kelly 参数
        if isinstance(self.risk_manager.sizer, KellySizer):
            trades = self.journal.load_all() if self.journal else []
            self.risk_manager.sizer.update_from_trades(trades)

    if self.journal:
        self.journal.record(trade_data)

    self._check_day_rollover()
```

### 8.3 定期余额校准

浮点累加会产生误差。每小时从交易所获取真实余额进行校准：

```python
# LiveEngine.run() 中增加
_last_calibration = 0
CALIBRATION_INTERVAL = 3600  # 1 小时

# 在 tick 循环中
now = time.time()
if now - self._last_calibration > CALIBRATION_INTERVAL:
    real_balance = self.broker.get_balance("USDT")
    if self.risk_manager:
        self.risk_manager.update_balance(real_balance, calibrate=True)
    self._last_calibration = now
```

---

## 9. 配置

### 9.1 config.yaml 追加

```yaml
# config.yaml — Phase 5 新增

risk:
  max_positions: 3                    # 最大同时持仓数
  max_daily_trades: 20                # 每日最大交易次数
  max_daily_loss_pct: 5.0             # 每日最大亏损（%）
  max_daily_loss_abs: 500.0           # 每日最大亏损（USDT）
  max_per_trade_risk_pct: 2.0         # 单笔风险上限（%）
  max_drawdown_pct: 20.0              # 累计最大回撤（%）
  min_balance: 50.0                   # 最低余额
  calibration_interval: 3600          # 余额校准间隔（秒）
  sizer:
    method: atr                        # fixed | kelly | atr
    base_risk_pct: 20.0               # ATR 方法的基础风险比例
    atr_period: 14
    multiplier: 1.0                    # ATR 风险敏感度
    max_pct: 100.0
    # Kelly 专用
    lookback_trades: 50               # 动态更新 Kelly 参数的回看窗口
    fraction: 0.5                      # 半凯利

notifications:
  on_entry: true
  on_exit: true
  on_error: true
  on_emergency: true
  daily_summary: true
  min_pnl_pct: 0.5                    # 盈亏 < 0.5% 不通知
```

### 9.2 风控参数选择指南

| 参数 | 保守 | 中性 | 激进 | 说明 |
|------|------|------|------|------|
| max_positions | 1 | 3 | 5 | 分散风险 vs 资金效率 |
| max_daily_loss | 2% | 5% | 10% | 亏损熔断，保护本金 |
| max_drawdown | 10% | 20% | 30% | 长期回撤熔断 |
| sizer | fixed 50% | atr | kelly | 仓位计算方式 |

---

## 10. 测试策略

### 10.1 Sizer 测试

| 测试 | 说明 |
|------|------|
| `test_fixed_sizer_50pct` | balance=10000 → amount=5000 |
| `test_fixed_sizer_min_order` | 小于 min_order 时 clamped |
| `test_kelly_sizer_positive` | average win > loss 时 f* > 0 |
| `test_kelly_sizer_zero_when_losing` | win_rate=0 时 amount=min_order |
| `test_atr_sizer_high_vol` | 高 ATR → 仓位减小 |
| `test_atr_sizer_low_vol` | 低 ATR → 仓位增大 |
| `test_atr_sizer_no_data_fallback` | 无数据 → 回退固定比例 |

### 10.2 RiskManager 测试

| 测试 | 说明 |
|------|------|
| `test_can_enter_all_clear` | 无约束时通过 |
| `test_can_enter_max_positions` | 达到上限时拒绝 |
| `test_can_enter_daily_trade_limit` | 达到日交易上限拒绝 |
| `test_can_enter_daily_loss_limit` | 日亏损超限拒绝 |
| `test_can_enter_drawdown_emergency` | 回撤超限 → 触发紧急停止 |
| `test_can_enter_balance_below_min` | 余额不足 → 紧急停止 |
| `test_emergency_stop_blocks_all` | 紧急停止后所有入场被拒 |
| `test_record_exit_updates_stats` | 平仓后统计正确更新 |
| `test_reset_daily` | 日重置后统计归零 |
| `test_peak_balance_tracking` | 峰值余额正确更新 |

### 10.3 Monitor 测试

| 测试 | 说明 |
|------|------|
| `test_journal_record_and_load` | 写入→读回→数据一致 |
| `test_journal_stats` | 统计计算正确 |
| `test_daily_summary_format` | 摘要包含必要字段 |
| `test_logger_setup_creates_files` | 日志文件正确创建 |

---

## 11. 文件清单

| 文件 | 行数估算 | 职责 |
|------|---------|------|
| `cryptoquant/risk/__init__.py` | ~5 | 导出 |
| `cryptoquant/risk/sizer.py` | ~180 | FixedSizer, KellySizer, ATRSizer |
| `cryptoquant/risk/manager.py` | ~280 | RiskManager 风控检查 + 余额校准 + 紧急停止自动恢复 |
| `cryptoquant/monitor/__init__.py` | ~5 | 导出 |
| `cryptoquant/monitor/logger.py` | ~50 | loguru 配置 |
| `cryptoquant/monitor/sanitizer.py` | ~40 | 日志脱敏（API Key、密码等） |
| `cryptoquant/monitor/journal.py` | ~90 | TradeJournal JSONL (线程安全) |
| `cryptoquant/monitor/reporter.py` | ~80 | 每日/每周摘要 |
| `tests/test_sizer.py` | ~100 | Sizer 单元测试 |
| `tests/test_risk_manager.py` | ~200 | RiskManager 测试（含紧急停止恢复） |
| `tests/test_monitor.py` | ~120 | Monitor 测试（含脱敏验证） |

---

## 12. 实现顺序

```
Task 5.1a: PositionSizer 基类 + FixedSizer
Task 5.1b: KellySizer
Task 5.1c: ATRSizer + create_sizer 工厂
Task 5.2a: DailyStats + RiskManager 入场检查
Task 5.2b: RiskManager 记录交易 + 紧急停止
Task 5.3a: setup_logging + TradeJournal
Task 5.3b: Reporter + 集成到 LiveEngine
```

---

## 13. 五层完整架构回顾

```
┌────────────────────────────────────────────────────────────┐
│                    CryptoQuant v1                           │
│                                                             │
│  ┌──────────┐   ┌───────────┐   ┌───────────────┐         │
│  │  Data    │   │ Strategy  │   │   Backtest    │         │
│  │  Layer   │   │  Layer    │   │   Engine      │         │
│  │          │   │           │   │               │         │
│  │ Fetcher  │   │ Strategy  │   │ BacktestEngine │         │
│  │ Store    │   │ Signals   │   │  Metrics      │         │
│  │ Cache    │   │ MACross   │   │  Report       │         │
│  └──────────┘   └───────────┘   └───────────────┘         │
│       │              │                  │                   │
│       └──────────────┼──────────────────┘                   │
│                      │                                      │
│  ┌───────────────────┼──────────────────────────────┐      │
│  │          Live Engine (编排)                       │      │
│  │    tick() → data → signal → risk → execute       │      │
│  └──────┬────────────────────────────────┬──────────┘      │
│         │                                │                  │
│  ┌──────▼──────┐   ┌──────────┐   ┌─────▼──────────┐     │
│  │  Execution  │   │   Risk   │   │   Monitor      │     │
│  │   Layer     │   │  Manager │   │                │     │
│  │             │   │          │   │  Logger        │     │
│  │  Broker     │   │  Sizer   │   │  Journal       │     │
│  │  Order      │   │  Limits  │   │  Reporter      │     │
│  │  Position   │   │  Stop    │   │  Notifier      │     │
│  └─────────────┘   └──────────┘   └────────────────┘     │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

所有 5 个 Phase 的设计文档已完成：

| Phase | 文档 | 大小 |
|-------|------|------|
| 1 Data | `phase1-data-layer-design.md` | ~28KB |
| 2 Strategy | `phase2-strategy-design.md` | ~27KB |
| 3 Backtest | `phase3-backtest-design.md` | ~32KB |
| 4 Live | `phase4-execution-live-design.md` | ~35KB |
| 5 Risk+Monitor | `phase5-risk-monitor-design.md` | ~26KB |

**总计 ~148KB 详细设计文档，覆盖 5 个 Phase，25 个 Task。**
