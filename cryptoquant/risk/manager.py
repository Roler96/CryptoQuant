"""Risk management — pre-trade checks and daily limits."""
import time
from dataclasses import dataclass
from datetime import date

from loguru import logger




@dataclass
class DailyStats:
    """Daily trading statistics."""

    date: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl_pct: float = 0.0
    total_pnl_abs: float = 0.0
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
    """Risk manager — pre-trade gatekeeper.

    Checks multiple constraints before allowing entry.
    Any single failure rejects the trade.
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
        sizer=None,
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

    def can_enter(
        self,
        symbol: str,
        side: int,
        current_balance: float,
        current_positions: int = 0,
    ) -> tuple[bool, str]:
        """Check if entry is allowed.

        Returns:
            (allowed, reason)
        """
        if self._emergency_stop:
            return False, "emergency stop triggered"

        if current_balance < self.min_balance:
            self._trigger_emergency(
                f"balance {current_balance:.1f} < min {self.min_balance}"
            )
            return False, f"balance below minimum ({current_balance:.1f} < {self.min_balance})"

        if current_positions >= self.max_positions:
            return False, f"max positions ({self.max_positions}) reached"

        if symbol in self._positions:
            return False, f"already holding {symbol}"

        if self._daily_stats.total_trades >= self.max_daily_trades:
            return False, f"daily trade limit ({self.max_daily_trades}) reached"

        if self._daily_stats.total_pnl_abs < -self.max_daily_loss_abs:
            return False, f"daily loss limit ({self.max_daily_loss_abs}) exceeded"

        if self._daily_stats.daily_pnl_pct < -self.max_daily_loss_pct:
            return False, f"daily loss limit ({self.max_daily_loss_pct}%) exceeded"

        if self._peak_balance > 0:
            current_drawdown = (current_balance / self._peak_balance - 1) * 100
            if abs(current_drawdown) > self.max_drawdown_pct:
                self._trigger_emergency(
                    f"max drawdown ({self.max_drawdown_pct}%) exceeded: "
                    f"{abs(current_drawdown):.1f}%"
                )
                return False, f"max drawdown exceeded ({current_drawdown:.1f}%)"

        return True, "ok"

    def can_exit(self, symbol: str, side: str) -> tuple[bool, str]:
        """Check if exit is allowed (usually always yes)."""
        if symbol not in self._positions:
            return False, f"no position in {symbol}"
        return True, "ok"

    def position_size(self, balance: float, price: float, **kwargs) -> float:
        """Calculate position size. Delegates to Sizer."""
        if self.sizer:
            return self.sizer.calculate(balance, price, **kwargs)
        return balance * 0.98

    def record_entry(self, symbol: str, side: str) -> None:
        self._positions[symbol] = side

    def record_exit(self, symbol: str, pnl_pct: float, pnl_abs: float) -> None:
        self._positions.pop(symbol, None)
        self._daily_stats.total_trades += 1

        if pnl_pct > 0:
            self._daily_stats.wins += 1
        else:
            self._daily_stats.losses += 1

        self._daily_stats.total_pnl_pct += pnl_pct
        self._daily_stats.total_pnl_abs += pnl_abs

    def update_balance(self, balance: float, calibrate: bool = False) -> None:
        if calibrate:
            drift = balance - self._daily_stats.current_balance
            if abs(drift) > 0.01:
                logger.debug(f"Balance calibrated: drift={drift:+.2f} USDT")

        self._daily_stats.current_balance = balance
        if balance > self._peak_balance:
            self._peak_balance = balance

    def reset_daily(self, new_balance: float) -> None:
        self._daily_stats = DailyStats(
            date=date.today().isoformat(),
            start_balance=new_balance,
            current_balance=new_balance,
        )
        logger.info(f"Daily stats reset. Balance: {new_balance:.1f} USDT")

    def _trigger_emergency(self, reason: str) -> None:
        if not self._emergency_stop:
            self._emergency_stop = True
            self._emergency_triggered_at = time.time()
            logger.critical(f"EMERGENCY STOP: {reason}")

    def is_emergency_stop(self) -> bool:
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

    def clear_emergency(self) -> None:
        logger.warning("Emergency stop cleared (manual)")
        self._emergency_stop = False
        self._emergency_triggered_at = None

    def get_daily_stats(self) -> DailyStats:
        return self._daily_stats

    def get_positions(self) -> dict[str, str]:
        return dict(self._positions)
