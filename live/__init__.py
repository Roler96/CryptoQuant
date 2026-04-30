"""Live trading module for CryptoQuant platform.

Provides live trading execution and paper trading simulation capabilities.
"""

from live.kill_switch import KillSwitch, KillSwitchReason, KillSwitchState
from live.order_manager import OrderManager, Order, OrderSide, OrderType, OrderStatus, OrderResult
from live.paper_trading import PaperTradingRunner, SimulatedTrade, SimulatedPosition
from live.trading import LiveTradingRunner, LiveTrade, LivePosition

__all__ = [
    # Kill Switch
    "KillSwitch",
    "KillSwitchReason",
    "KillSwitchState",
    # Order Manager
    "OrderManager",
    "Order",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "OrderResult",
    # Paper Trading
    "PaperTradingRunner",
    "SimulatedTrade",
    "SimulatedPosition",
    # Live Trading
    "LiveTradingRunner",
    "LiveTrade",
    "LivePosition",
]