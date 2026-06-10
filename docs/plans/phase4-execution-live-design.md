# Phase 4: Execution Layer + Live Trading — 详细设计文档

> **版本:** 1.0 | **日期:** 2026-06-10 | **作者:** Hermes + Roler

---

## 1. 概述

Phase 4 将策略从回测推向实盘。分两层：执行层（交易所抽象，只管下单）和实盘引擎（编排数据→信号→风控→执行的完整循环）。

```
┌─────────────────────────────────────────────────────────┐
│                    LiveEngine                            │
│                                                         │
│   tick() 循环:                                          │
│   DataCache.get_ohlcv() ──▶ Strategy.generate_signal()  │
│       │                            │                    │
│       │                     RiskManager.check()         │
│       │                            │                    │
│       │                      Broker.place_order()       │
│       │                            │                    │
│       └──── StateManager.save() ←──┘                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**核心原则：**
- 先 OKX testnet（零资金风险），验证通过再切实盘
- 策略代码在回测和实盘间**零改动复用** — Strategy 只产出信号
- 所有状态持久化，进程重启后无缝恢复
- 错误不静默 — 任何异常都告警 + 记录

---

## 2. 执行层：Broker 设计

### 2.1 类图

```
┌──────────────────────────────────────────────────────────┐
│                      Broker                              │
├──────────────────────────────────────────────────────────┤
│ - exchange: ccxt.Exchange                                │
│ - exchange_name: str                                     │
│ - testnet: bool                                          │
│ - config: dict                                           │
├──────────────────────────────────────────────────────────┤
│ + get_balance(quote="USDT") → float                       │
│ + get_positions() → list[Position]                        │
│ + get_position(symbol) → Position | None                  │
│ + get_open_orders(symbol) → list[Order]                   │
│ + market_buy(symbol, amount) → Order                      │
│ + market_sell(symbol, amount) → Order                     │
│ + limit_buy(symbol, amount, price) → Order                │
│ + limit_sell(symbol, amount, price) → Order               │
│ + cancel_order(id, symbol) → bool                         │
│ + cancel_all_orders(symbol) → int                         │
│ + fetch_order(id, symbol) → Order                         │
│ + get_ticker(symbol) → dict  # {bid, ask, last}          │
│ + is_testnet() → bool                                    │
└──────────────────────────────────────────────────────────┘
```

### 2.2 构造函数

```python
# cryptoquant/execution/broker.py
import ccxt
from loguru import logger
from typing import Optional


class Broker:
    """交易所抽象层。通过 ccxt 与交易所通信。

    设计目标：
    - 统一多交易所接口，调用方不感知是 OKX 还是 Binance
    - 所有方法有统一错误处理（网络重试 + 业务异常转换）
    - testnet 模式下可用沙盒 API Key 验证完整流程
    """

    def __init__(
        self,
        exchange: str = "okx",
        api_key: str = "",
        secret: str = "",
        password: str = "",
        testnet: bool = True,
    ):
        self.exchange_name = exchange
        self.testnet = testnet

        exchange_class = getattr(ccxt, exchange)
        self.exchange = exchange_class({
            "apiKey": api_key,
            "secret": secret,
            "password": password,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

        if testnet:
            self.exchange.set_sandbox_mode(True)
            logger.info(f"Broker initialized: {exchange} TESTNET")
        else:
            logger.warning(f"Broker initialized: {exchange} LIVE ⚠️")

    def _handle_ccxt_error(self, e: Exception, context: str) -> None:
        """统一的 ccxt 异常处理。"""
        if isinstance(e, ccxt.NetworkError):
            logger.error(f"[{context}] Network error: {e}")
            raise ConnectionError(f"Exchange network error: {e}") from e
        elif isinstance(e, ccxt.AuthenticationError):
            logger.error(f"[{context}] Auth error — check API keys")
            raise PermissionError("Exchange authentication failed") from e
        elif isinstance(e, ccxt.InsufficientFunds):
            logger.error(f"[{context}] Insufficient funds")
            raise ValueError("Insufficient funds") from e
        elif isinstance(e, ccxt.InvalidOrder):
            logger.error(f"[{context}] Invalid order: {e}")
            raise ValueError(f"Invalid order: {e}") from e
        else:
            logger.error(f"[{context}] Unknown error: {e}")
            raise
```

### 2.3 核心方法实现

```python
def get_balance(self, quote: str = "USDT") -> float:
    """获取指定计价货币的可用余额。

    Args:
        quote: 计价货币，默认 USDT

    Returns:
        可用余额（float）

    Raises:
        ConnectionError: 网络异常
    """
    try:
        balance = self.exchange.fetch_balance()
        free = balance.get(quote, {}).get("free", 0)
        if free is None:
            free = 0.0
        return float(free)
    except Exception as e:
        self._handle_ccxt_error(e, "get_balance")
        raise


def get_ticker(self, symbol: str) -> dict:
    """获取当前行情。

    Returns:
        {"bid": float, "ask": float, "last": float, "timestamp": int}
    """
    try:
        ticker = self.exchange.fetch_ticker(symbol)
        return {
            "bid": ticker.get("bid", 0),
            "ask": ticker.get("ask", 0),
            "last": ticker.get("last", 0),
            "timestamp": ticker.get("timestamp", 0),
        }
    except Exception as e:
        self._handle_ccxt_error(e, f"get_ticker({symbol})")
        raise


def market_buy(self, symbol: str, amount: float) -> Order:
    """市价买入。

    Args:
        symbol: 交易对，如 "BTC/USDT"
        amount: 买入数量（以 base 货币计，如 BTC 数量）

    Returns:
        Order 对象

    Raises:
        ValueError: 余额不足或订单无效
        ConnectionError: 网络异常
    """
    logger.info(f"MARKET BUY {symbol}: amount={amount}")
    try:
        raw = self.exchange.create_market_buy_order(symbol, amount)
        return Order.from_ccxt(raw, exchange=self.exchange_name)
    except Exception as e:
        self._handle_ccxt_error(e, f"market_buy({symbol})")
        raise


def market_sell(self, symbol: str, amount: float) -> Order:
    """市价卖出。"""
    logger.info(f"MARKET SELL {symbol}: amount={amount}")
    try:
        raw = self.exchange.create_market_sell_order(symbol, amount)
        return Order.from_ccxt(raw, exchange=self.exchange_name)
    except Exception as e:
        self._handle_ccxt_error(e, f"market_sell({symbol})")
        raise


def limit_buy(self, symbol: str, amount: float, price: float) -> Order:
    """限价买入。"""
    logger.info(f"LIMIT BUY {symbol}: amount={amount}, price={price}")
    try:
        raw = self.exchange.create_limit_buy_order(symbol, amount, price)
        return Order.from_ccxt(raw, exchange=self.exchange_name)
    except Exception as e:
        self._handle_ccxt_error(e, f"limit_buy({symbol})")
        raise


def limit_sell(self, symbol: str, amount: float, price: float) -> Order:
    """限价卖出。"""
    logger.info(f"LIMIT SELL {symbol}: amount={amount}, price={price}")
    try:
        raw = self.exchange.create_limit_sell_order(symbol, amount, price)
        return Order.from_ccxt(raw, exchange=self.exchange_name)
    except Exception as e:
        self._handle_ccxt_error(e, f"limit_sell({symbol})")
        raise


def cancel_order(self, order_id: str, symbol: str) -> bool:
    """取消指定订单。"""
    try:
        self.exchange.cancel_order(order_id, symbol)
        return True
    except Exception as e:
        self._handle_ccxt_error(e, f"cancel_order({order_id})")
        return False


def cancel_all_orders(self, symbol: str) -> int:
    """取消某交易对所有未成交订单。返回取消数量。"""
    try:
        orders = self.exchange.fetch_open_orders(symbol)
        count = 0
        for o in orders:
            try:
                self.exchange.cancel_order(o["id"], symbol)
                count += 1
            except Exception:
                pass
        return count
    except Exception as e:
        self._handle_ccxt_error(e, f"cancel_all_orders({symbol})")
        return 0


def get_open_orders(self, symbol: str) -> list[Order]:
    """获取未成交订单。"""
    try:
        raw_orders = self.exchange.fetch_open_orders(symbol)
        return [Order.from_ccxt(o, exchange=self.exchange_name) for o in raw_orders]
    except Exception as e:
        self._handle_ccxt_error(e, f"get_open_orders({symbol})")
        return []
```

### 2.4 OKX spot 特殊处理

OKX 的 ccxt 实现有几个坑，参考 memory 中的经验：

```python
# OKX 需要 contract 字段，否则 create_order 报 KeyError
# 但这是 ccxt 内部使用的，Broker 层无需关心
# 如需 bypass load_markets()：
def _ensure_market_loaded(self, symbol: str):
    """确保 market 信息已加载。"""
    if symbol not in self.exchange.markets:
        self.exchange.load_markets()
```

---

## 3. 订单数据结构

### 3.1 Order

```python
# cryptoquant/execution/order.py
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class OrderStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class Order:
    """交易所订单记录。"""

    id: str                          # 交易所订单 ID
    exchange: str                    # "okx" | "binance"
    symbol: str                      # "BTC/USDT"
    side: OrderSide
    type: OrderType
    amount: float                    # 下单数量
    price: float | None              # 限价单价格（市价单为 None）
    filled: float                    # 已成交数量
    remaining: float                 # 未成交数量
    cost: float                      # 已成交金额（quote 货币）
    fee: dict | None                 # 手续费 {cost, currency}
    status: OrderStatus
    timestamp: int                   # Unix 毫秒
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_ccxt(cls, raw: dict, exchange: str = "") -> "Order":
        """从 ccxt 原始订单字典创建 Order。"""
        return cls(
            id=str(raw.get("id", "")),
            exchange=exchange,
            symbol=raw.get("symbol", ""),
            side=OrderSide(raw["side"]),
            type=OrderType(raw.get("type", "market")),
            amount=float(raw.get("amount", 0)),
            price=float(raw["price"]) if raw.get("price") else None,
            filled=float(raw.get("filled", 0)),
            remaining=float(raw.get("remaining", 0)),
            cost=float(raw.get("cost", 0)),
            fee=raw.get("fee"),
            status=OrderStatus(raw.get("status", "open")),
            timestamp=raw.get("timestamp", 0),
            raw=raw,
        )

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.CLOSED

    @property
    def is_open(self) -> bool:
        return self.status == OrderStatus.OPEN
```

### 3.2 Position

```python
@dataclass
class Position:
    """持仓记录。"""

    symbol: str
    side: str                       # "long" | "short"
    amount: float                   # 持仓数量
    entry_price: float              # 平均入场价
    current_price: float            # 当前市价
    unrealized_pnl: float           # 未实现盈亏（%）
    unrealized_pnl_abs: float       # 未实现盈亏（USDT）
    timestamp: int                  # Unix 毫秒

    @classmethod
    def from_ccxt(cls, raw: dict) -> "Position":
        """从 ccxt 持仓数据创建。"""
        entry_price = float(raw.get("entryPrice", raw.get("entry_price", 0)))
        current_price = float(raw.get("markPrice", raw.get("mark_price", 0)))

        if entry_price > 0:
            unrealized_pnl = (current_price / entry_price - 1) * 100
        else:
            unrealized_pnl = 0.0

        return cls(
            symbol=raw.get("symbol", ""),
            side=raw.get("side", "long"),
            amount=float(raw.get("contracts", raw.get("amount", 0))),
            entry_price=entry_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_abs=float(raw.get("unrealizedPnl", 0)),
            timestamp=raw.get("timestamp", 0),
        )

    @property
    def notional(self) -> float:
        """持仓名义价值（USDT）。"""
        return self.amount * self.current_price
```

---

## 4. 状态持久化：StateManager

### 4.1 设计

实盘引擎需要在进程重启后恢复状态。StateManager 管理：

- 当前持仓
- 活跃订单
- 账户快照（余额、权益）
- 策略状态（如上次信号时间、冷却期等）

```python
# cryptoquant/engine/state.py
import json
from pathlib import Path
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class EngineState:
    """引擎完整状态快照。"""
    timestamp: int
    strategy_name: str
    symbol: str

    # 账户
    balance: float
    initial_capital: float

    # 持仓
    has_position: bool
    position_side: str              # "long" | "short" | ""
    position_entry_price: float
    position_amount: float
    position_entry_time: int

    # 订单
    active_order_ids: list[str]

    # 统计
    total_trades: int
    total_pnl_pct: float
    last_signal: int
    last_tick_time: int


class StateManager:
    """引擎状态持久化管理。

    使用 JSON 文件 — 简单、人类可读、易于调试。
    每次 tick 后原子写入，崩溃恢复只需读回文件。
    """

    def __init__(self, state_dir: str = "state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _state_path(self, strategy_name: str, symbol: str) -> Path:
        safe_symbol = symbol.replace("/", "_").lower()
        return self.state_dir / f"state_{strategy_name}_{safe_symbol}.json"

    def save(self, state: EngineState):
        """保存状态到 JSON 文件。"""
        path = self._state_path(state.strategy_name, state.symbol)
        # 先写临时文件，再 rename（原子操作）
        tmp_path = path.with_suffix(".tmp")
        data = asdict(state)
        data["saved_at"] = datetime.utcnow().isoformat()
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        tmp_path.rename(path)

    def load(self, strategy_name: str, symbol: str) -> EngineState | None:
        """加载上次保存的状态。"""
        path = self._state_path(strategy_name, symbol)
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        return EngineState(**{k: v for k, v in data.items() if k != "saved_at"})
```

---

## 5. 实盘引擎：LiveEngine

### 5.1 类图

```
┌──────────────────────────────────────────────────────────┐
│                     LiveEngine                            │
├──────────────────────────────────────────────────────────┤
│ - broker: Broker                                         │
│ - strategy: Strategy                                     │
│ - cache: DataCache                                       │
│ - risk_manager: RiskManager (Phase 5)                    │
│ - state_mgr: StateManager                                │
│ - config: dict                                           │
│ - _running: bool                                         │
├──────────────────────────────────────────────────────────┤
│ + tick() → TickResult                                    │
│ + run(interval=60)                                       │
│ + stop()                                                 │
│ + get_state() → EngineState                              │
└──────────────────────────────────────────────────────────┘
```

### 5.2 `tick()` — 单次决策循环

```python
from dataclasses import dataclass
from enum import Enum


class TickAction(str, Enum):
    NOOP = "noop"            # 无事发生
    ENTRY_LONG = "entry_long"
    ENTRY_SHORT = "entry_short"
    EXIT = "exit"            # 平仓
    SKIP = "skip"            # 有信号但被风控拦住


@dataclass
class TickResult:
    """单次 tick 结果。"""
    action: TickAction
    signal: int
    reason: str              # 决策原因
    order: Order | None
    balance: float
    timestamp: int


class LiveEngine:
    """实盘交易引擎。

    职责：
    1. 定时获取最新 K 线数据
    2. 调用策略生成信号
    3. 检查风控
    4. 通过 Broker 执行订单
    5. 持久化状态
    """

    def __init__(
        self,
        broker: Broker,
        strategy: Strategy,
        cache: "DataCache",
        risk_manager=None,            # Phase 5 接入
        state_dir: str = "state",
        symbol: str = "",
        min_order_usdt: float = 10.0,
        cooldown_bars: int = 0,       # 平仓后冷却 K 线数
    ):
        self.broker = broker
        self.strategy = strategy
        self.cache = cache
        self.risk_manager = risk_manager
        self.state_mgr = StateManager(state_dir)
        self.symbol = symbol
        self.min_order_usdt = min_order_usdt
        self.cooldown_bars = cooldown_bars

        self._running = False
        self._cooldown_remaining = 0

        # 尝试恢复状态
        saved = self.state_mgr.load(strategy.name, symbol)
        if saved:
            logger.info(f"Restored state for {strategy.name} on {symbol}")
            self._trades_count = saved.total_trades
        else:
            self._trades_count = 0

    def tick(self) -> TickResult:
        """执行一次决策循环。

        Returns:
            TickResult 描述本次 tick 的结果
        """
        timestamp = int(datetime.utcnow().timestamp() * 1000)

        # === 0. 冷却期检查 ===
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            return TickResult(
                action=TickAction.SKIP,
                signal=0,
                reason=f"cooldown ({self._cooldown_remaining} bars remaining)",
                order=None,
                balance=self._get_balance(),
                timestamp=timestamp,
            )

        # === 1. 获取数据 ===
        lookback = max(self.strategy.min_bars, 200)
        df = self.cache.get_ohlcv(
            self.broker.exchange_name,
            self.symbol,
            self.strategy.timeframe,
            lookback=lookback,
        )

        if len(df) < self.strategy.min_bars:
            logger.warning(f"Insufficient data: {len(df)} < {self.strategy.min_bars}")
            return TickResult(
                action=TickAction.SKIP,
                signal=0,
                reason="insufficient data",
                order=None,
                balance=self._get_balance(),
                timestamp=timestamp,
            )

        # === 2. 生成信号 ===
        try:
            signals = self.strategy.generate_signal(df)
            signal = int(signals.iloc[-1])
        except Exception as e:
            logger.error(f"Signal generation failed: {e}")
            return TickResult(
                action=TickAction.SKIP,
                signal=0,
                reason=f"signal error: {e}",
                order=None,
                balance=self._get_balance(),
                timestamp=timestamp,
            )

        # === 3. 检查当前持仓 ===
        try:
            position = self.broker.get_position(self.symbol)
        except Exception:
            position = None

        has_position = position is not None and position.amount > 0

        # === 4. 决策 ===
        if has_position:
            # 平仓条件：反向信号
            if (position.side == "long" and signal == -1) or \
               (position.side == "short" and signal == 1):
                return self._exit_position(position, signal, timestamp)
            else:
                return TickResult(
                    action=TickAction.NOOP,
                    signal=signal,
                    reason=f"holding {position.side}",
                    order=None,
                    balance=self._get_balance(),
                    timestamp=timestamp,
                )
        else:
            # 入场条件
            if signal in (1, -1):
                # 风控检查（Phase 5 完善）
                if self.risk_manager and not self.risk_manager.can_enter(
                    self.symbol, signal
                ):
                    return TickResult(
                        action=TickAction.SKIP,
                        signal=signal,
                        reason="risk manager rejected entry",
                        order=None,
                        balance=self._get_balance(),
                        timestamp=timestamp,
                    )
                return self._enter_position(signal, timestamp)
            else:
                return TickResult(
                    action=TickAction.NOOP,
                    signal=0,
                    reason="no signal",
                    order=None,
                    balance=self._get_balance(),
                    timestamp=timestamp,
                )

    def _enter_position(self, signal: int, timestamp: int) -> TickResult:
        """开仓。"""
        side = "long" if signal == 1 else "short"
        balance = self._get_balance()

        # 计算仓位大小
        order_amount = self._calculate_position_size(balance)

        if order_amount < self.min_order_usdt:
            return TickResult(
                action=TickAction.SKIP,
                signal=signal,
                reason=f"order amount {order_amount:.1f} < min {self.min_order_usdt}",
                order=None,
                balance=balance,
                timestamp=timestamp,
            )

        try:
            if signal == 1:
                order = self.broker.market_buy(self.symbol, order_amount)
            else:
                order = self.broker.market_sell(self.symbol, order_amount)

            logger.info(f"ENTER {side.upper()}: {order.amount} @ ~{order.price}")

            return TickResult(
                action=TickAction.ENTRY_LONG if signal == 1 else TickAction.ENTRY_SHORT,
                signal=signal,
                reason=f"entry {side}",
                order=order,
                balance=self._get_balance(),
                timestamp=timestamp,
            )
        except Exception as e:
            logger.error(f"Entry failed: {e}")
            return TickResult(
                action=TickAction.SKIP,
                signal=signal,
                reason=f"entry error: {e}",
                order=None,
                balance=self._get_balance(),
                timestamp=timestamp,
            )

    def _exit_position(
        self, position: Position, signal: int, timestamp: int
    ) -> TickResult:
        """平仓。"""
        logger.info(f"EXIT {position.side.upper()}: signal={signal}")

        try:
            if position.side == "long":
                order = self.broker.market_sell(self.symbol, position.amount)
            else:
                order = self.broker.market_buy(self.symbol, position.amount)

            self._trades_count += 1
            self._cooldown_remaining = self.cooldown_bars

            return TickResult(
                action=TickAction.EXIT,
                signal=signal,
                reason=f"exit {position.side} on signal",
                order=order,
                balance=self._get_balance(),
                timestamp=timestamp,
            )
        except Exception as e:
            logger.error(f"Exit failed: {e}")
            return TickResult(
                action=TickAction.SKIP,
                signal=signal,
                reason=f"exit error: {e}",
                order=None,
                balance=self._get_balance(),
                timestamp=timestamp,
            )

    def _get_balance(self) -> float:
        """安全获取余额。"""
        try:
            return self.broker.get_balance("USDT")
        except Exception:
            return 0.0

    def _calculate_position_size(self, balance: float) -> float:
        """计算下单金额。

        Phase 4 简化：满仓交易。
        Phase 5 改为 sizer 模块管理。
        """
        return balance * 0.98  # 预留 2% 手续费
```

### 5.3 `run()` — 循环入口

```python
import time
import signal as os_signal


def run(self, interval: int = 60):
    """启动实盘循环。

    Args:
        interval: tick 间隔（秒）。K 线周期的整数倍。
    """
    self._running = True
    logger.info(
        f"LiveEngine started: {self.strategy.name} on {self.symbol}, "
        f"interval={interval}s, testnet={self.broker.testnet}"
    )

    # 注册优雅退出
    os_signal.signal(os_signal.SIGINT, self._handle_shutdown)
    os_signal.signal(os_signal.SIGTERM, self._handle_shutdown)

    try:
        while self._running:
            try:
                result = self.tick()
                self._save_state()

                if result.action != TickAction.NOOP:
                    logger.info(f"Tick: {result.action.value} | {result.reason}")

            except Exception as e:
                logger.error(f"Tick failed: {e}")
                # 异常后继续，不退出

            # 休眠到下一个整点 K 线
            time.sleep(interval)

    finally:
        self._save_state()
        logger.info("LiveEngine stopped")

    def _handle_shutdown(self, signum, frame):
        """处理 SIGINT/SIGTERM，优雅退出。"""
        logger.info(f"Received signal {signum}, shutting down...")
        self._running = False

    def stop(self):
        """手动停止引擎。"""
        self._running = False

    def _save_state(self):
        """保存当前状态到文件。"""
        try:
            balance = self._get_balance()
            position = self.broker.get_position(self.symbol)

            state = EngineState(
                timestamp=int(datetime.utcnow().timestamp() * 1000),
                strategy_name=self.strategy.name,
                symbol=self.symbol,
                balance=balance,
                initial_capital=10000,  # TODO: 从配置读取
                has_position=position is not None and position.amount > 0,
                position_side=position.side if position else "",
                position_entry_price=position.entry_price if position else 0,
                position_amount=position.amount if position else 0,
                position_entry_time=position.timestamp if position else 0,
                active_order_ids=[],
                total_trades=self._trades_count,
                total_pnl_pct=0.0,     # TODO: 累积计算
                last_signal=0,
                last_tick_time=0,
            )
            self.state_mgr.save(state)
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")
```

---

## 6. 配置

### 6.1 config.yaml 追加

```yaml
# config.yaml — Phase 4 新增部分

live:
  testnet: true                              # 实盘前必须为 true
  interval_seconds: 60                       # tick 间隔
  cooldown_bars: 3                           # 平仓后冷却 bar 数
  min_order_usdt: 10.0                       # 最小下单金额

state:
  dir: state/                                # 状态文件目录
```

### 6.2 .env 追加

```bash
# .env — Phase 4 新增
OKX_API_KEY=your_api_key
OKX_SECRET=your_secret
OKX_PASSWORD=your_passphrase
```

---

## 7. 错误处理策略

### 7.1 分级处理

| 级别 | 场景 | 处理 |
|------|------|------|
| WARNING | 单次 tick 失败（网络超时） | 日志 + 跳过本次 + 下个 tick 重试 |
| ERROR | 下单失败（余额不足） | 日志 + 告警 + 停止该策略 |
| CRITICAL | 认证失败 | 日志 + 立即停止 |

### 7.2 网络重试

ccxt 的 `enableRateLimit: True` 已处理限速。额外的网络抖动：

```python
# 可选：在 Broker 层加装饰器
import functools
import time

def retry_on_network(max_retries=3, delay=2):
    """网络异常自动重试装饰器。"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ConnectionError) as e:
                    last_error = e
                    logger.warning(
                        f"Retry {attempt+1}/{max_retries} for {func.__name__}: {e}"
                    )
                    time.sleep(delay * (attempt + 1))  # 递增延迟
            raise last_error
        return wrapper
    return decorator
```

---

## 8. 测试策略

### 8.1 Broker 测试

| 测试 | 说明 |
|------|------|
| `test_broker_init_testnet` | testnet 初始化成功 |
| `test_get_balance_returns_float` | 余额是数字（testnet 通常返回模拟余额） |
| `test_get_ticker_has_fields` | ticker 包含 bid/ask/last |
| `test_market_order_roundtrip` | testnet 下单 → 查订单状态 → 撤销 |
| `test_insufficient_funds_raises` | testnet 超大额订单应报错 |
| `test_invalid_symbol_raises` | 无效交易对报错 |
| `test_cancel_order` | 下单→撤销→验证状态 |
| `test_order_from_ccxt` | Order.from_ccxt() 转换正确 |

### 8.2 LiveEngine 测试

| 测试 | 说明 |
|------|------|
| `test_tick_no_signal_is_noop` | 策略返回 0 → TickAction.NOOP |
| `test_tick_entry_on_buy_signal` | 策略返回 1 → TickAction.ENTRY_LONG |
| `test_tick_exit_on_reverse_signal` | 持仓 long + 信号 -1 → EXIT |
| `test_tick_skip_on_insufficient_data` | 数据不足 → SKIP |
| `test_cooldown_skips_ticks` | 平仓后在冷却期内跳过新信号 |
| `test_state_persistence_roundtrip` | save → load → 数据一致 |
| `test_state_restore_after_crash` | 模拟崩溃恢复 |

### 8.3 测试策略

由于涉及真实交易所 API（即使是 testnet），测试设计为：

- **离线单元测试**：Mock Broker，验证 LiveEngine 决策逻辑
- **testnet 集成测试**：手动运行，验证真实 OKX testnet 交互
- **不跑 CI**：交易所相关测试标记为 `@pytest.mark.integration`，CI 跳过

```python
# conftest.py
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: marks tests that hit real exchange APIs"
    )

# 测试文件
@pytest.mark.integration
def test_broker_get_balance_testnet():
    broker = Broker("okx", api_key="...", testnet=True)
    balance = broker.get_balance()
    assert isinstance(balance, float)
```

---

## 9. 从回测到实盘的切换检查清单

在从 testnet 切到实盘之前，必须全部通过：

```
[ ] testnet 环境跑满 7 天，所有交易符合策略预期
[ ] testnet 日志审核：无异常 ERROR 日志
[ ] 状态文件恢复测试：杀掉进程后重启，持仓/订单正确恢复
[ ] 手动触发止损/止盈场景（testnet 下单后手动取消改单模拟）
[ ] 手续费/滑点计算与实际成交一致
[ ] 余额检查：每笔交易资金无误
[ ] 断开网络恢复后引擎自动重连
[ ] 多策略并行运行 24h 无死锁
[ ] 性能：单次 tick < 2s（绝大部分时间在 sleep）
[ ] config.yaml 中 testnet: false 切换
```

---

## 10. 文件清单

| 文件 | 行数估算 | 职责 |
|------|---------|------|
| `cryptoquant/execution/__init__.py` | ~5 | 导出 Broker |
| `cryptoquant/execution/broker.py` | ~180 | 交易所抽象 + ccxt 封装 |
| `cryptoquant/execution/order.py` | ~100 | Order, Position 数据类 |
| `cryptoquant/engine/__init__.py` | ~5 | 导出 |
| `cryptoquant/engine/live.py` | ~300 | LiveEngine 实盘循环 |
| `cryptoquant/engine/state.py` | ~80 | StateManager 持久化 |
| `tests/test_broker.py` | ~120 | Broker 测试（mock + integration） |
| `tests/test_live_engine.py` | ~150 | LiveEngine 测试（mock broker） |
| `tests/test_state.py` | ~50 | 状态持久化测试 |

---

## 11. 实现顺序

```
Task 4.1a: Order / Position 数据类            (order.py)
Task 4.1b: Broker 交易所抽象                  (broker.py)
Task 4.2:  StateManager 状态持久化             (state.py)
Task 4.3a: LiveEngine.tick() 单次决策          (live.py)
Task 4.3b: LiveEngine.run() 循环入口           (live.py)
Task 4.3c: 端到端 testnet 验证                  (手动)
```

Task 4.1-4.2 完成后可在 testnet 手动下单验证。Task 4.3 完成后是完整自动交易。
