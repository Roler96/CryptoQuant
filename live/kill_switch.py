"""Kill switch module for CryptoQuant platform.

Provides emergency position closure and safe mode functionality to protect
against catastrophic losses, API failures, and other critical situations.
All kill switch events are logged to the audit trail for compliance.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Protocol

import structlog

from logs.audit import audit_risk_event
from strategy.base import Position


logger = structlog.get_logger(__name__)


class KillSwitchReason(Enum):
    """Reason for kill switch activation.

    Attributes:
        MANUAL: Manually triggered by operator
        MAX_LOSS: Automatic trigger due to maximum drawdown exceeded
        API_ERROR: Automatic trigger due to API disconnection/failure
    """
    MANUAL = auto()
    MAX_LOSS = auto()
    API_ERROR = auto()


@dataclass
class KillSwitchState:
    """Current state of the kill switch.

    Attributes:
        is_active: Whether kill switch is currently active (safe mode)
        reason: Reason for last activation (if any)
        activated_at: Timestamp when kill switch was activated
        positions_closed: Number of positions closed during last activation
        total_pnl: Total P&L from closed positions during last activation
        metadata: Additional state information
    """
    is_active: bool = False
    reason: Optional[KillSwitchReason] = None
    activated_at: Optional[str] = None
    positions_closed: int = 0
    total_pnl: Decimal = Decimal('0')
    metadata: Dict[str, Any] = field(default_factory=dict)


class TradingClient(Protocol):
    """Protocol for trading client interface.

    Defines the minimum interface required for emergency position closure.
    """

    def close_position(self, pair: str) -> Dict[str, Any]:
        """Close position for a trading pair.

        Args:
            pair: Trading pair symbol (e.g., "BTC/USDT")

        Returns:
            Dictionary with close result information
        """
        ...

    def get_positions(self) -> Dict[str, Position]:
        """Get all current open positions.

        Returns:
            Dictionary of positions by trading pair
        """
        ...


class KillSwitch:
    """Emergency kill switch for trading system protection.

    Monitors trading conditions and provides mechanisms to immediately
    close all positions and enter safe mode when critical thresholds
    are breached or manual intervention is required.

    Attributes:
        max_drawdown_pct: Maximum allowed drawdown percentage (0-100)
        require_confirmation: Whether manual trigger requires confirmation
        state: Current kill switch state
    """

    def __init__(
        self,
        max_drawdown_pct: Decimal = Decimal('10'),
        require_confirmation: bool = True,
    ) -> None:
        """Initialize kill switch.

        Args:
            max_drawdown_pct: Maximum drawdown percentage before auto-trigger
            require_confirmation: Whether manual triggers need confirmation
        """
        self.max_drawdown_pct = max_drawdown_pct
        self.require_confirmation = require_confirmation
        self._state = KillSwitchState()

        self.logger = structlog.get_logger(__name__).bind(
            max_drawdown_pct=str(max_drawdown_pct),
            require_confirmation=require_confirmation,
        )

    @property
    def state(self) -> KillSwitchState:
        """Get current kill switch state."""
        return self._state

    def is_safe_mode(self) -> bool:
        """Check if system is in safe mode (kill switch active).

        Returns:
            True if kill switch is active and no new positions allowed
        """
        return self._state.is_active

    def reset_safe_mode(self, confirmed: bool = False) -> bool:
        """Manually reset safe mode to allow trading again.

        Args:
            confirmed: Confirmation flag to prevent accidental reset

        Returns:
            True if reset was successful, False otherwise
        """
        if not self._state.is_active:
            self.logger.debug("Kill switch already inactive, no reset needed")
            return True

        if not confirmed:
            self.logger.warning("Safe mode reset requires confirmation")
            return False

        self._state.is_active = False
        self._state.reason = None

        self.logger.info("Safe mode reset - trading resumed")
        audit_risk_event(
            event_type="kill_switch_reset",
            severity="info",
            message="Kill switch safe mode manually reset",
            metadata={"reset_at": datetime.utcnow().isoformat()},
        )

        return True

    def emergency_close_all(
        self,
        positions: Dict[str, Position],
        client: TradingClient,
    ) -> Dict[str, Any]:
        """Emergency close all open positions immediately.

        Iterates through all positions and attempts to close each one.
        Tracks success/failure for each position and logs all actions.

        Args:
            positions: Dictionary of open positions by trading pair
            client: Trading client for executing close orders

        Returns:
            Dictionary with closure results:
                - total_positions: Number of positions attempted
                - closed_successfully: Number successfully closed
                - failed: List of pairs that failed to close
                - total_pnl: Total P&L from closed positions
        """
        results = {
            "total_positions": len(positions),
            "closed_successfully": 0,
            "failed": [],
            "total_pnl": Decimal('0'),
        }

        if not positions:
            self.logger.info("No positions to close")
            return results

        self.logger.warning(
            "Emergency closing all positions",
            position_count=len(positions),
            pairs=list(positions.keys()),
        )

        for pair, position in positions.items():
            try:
                close_result = client.close_position(pair)

                pnl = close_result.get('pnl', Decimal('0'))
                results["total_pnl"] += pnl
                results["closed_successfully"] += 1

                self.logger.info(
                    "Position closed",
                    pair=pair,
                    side=position.side,
                    size=str(position.size),
                    pnl=str(pnl),
                )

                audit_risk_event(
                    event_type="emergency_position_close",
                    pair=pair,
                    severity="critical",
                    message=f"Emergency close: {position.side} position on {pair}",
                    metadata={
                        "size": str(position.size),
                        "entry_price": str(position.entry_price),
                        "pnl": str(pnl),
                    },
                )

            except Exception as e:
                results["failed"].append(pair)
                self.logger.error(
                    "Failed to close position",
                    pair=pair,
                    error=str(e),
                )

                audit_risk_event(
                    event_type="emergency_close_failed",
                    pair=pair,
                    severity="critical",
                    message=f"Failed to emergency close position on {pair}: {str(e)}",
                    metadata={
                        "error": str(e),
                        "size": str(position.size),
                        "entry_price": str(position.entry_price),
                    },
                )

        self._state.positions_closed = results["closed_successfully"]
        self._state.total_pnl = results["total_pnl"]

        return results

    def trigger_manual(self, confirmed: bool = False) -> bool:
        """Manually trigger the kill switch.

        Args:
            confirmed: Confirmation flag (required if require_confirmation is True)

        Returns:
            True if trigger was successful, False otherwise
        """
        if self._state.is_active:
            self.logger.info("Kill switch already active")
            return True

        if self.require_confirmation and not confirmed:
            self.logger.warning("Manual kill switch trigger requires confirmation")
            return False

        self._activate(KillSwitchReason.MANUAL)
        return True

    def trigger_max_loss(
        self,
        drawdown_pct: Decimal,
        max_drawdown: Optional[Decimal] = None,
    ) -> bool:
        """Trigger kill switch if maximum loss threshold exceeded.

        Automatically activates kill switch if current drawdown exceeds
        the configured maximum drawdown percentage.

        Args:
            drawdown_pct: Current portfolio drawdown percentage (0-100)
            max_drawdown: Override max drawdown threshold (uses config default if None)

        Returns:
            True if kill switch was activated, False otherwise
        """
        if self._state.is_active:
            return True

        threshold = max_drawdown if max_drawdown is not None else self.max_drawdown_pct

        if drawdown_pct >= threshold:
            self.logger.critical(
                "Maximum drawdown exceeded - activating kill switch",
                drawdown_pct=str(drawdown_pct),
                threshold=str(threshold),
            )
            self._activate(KillSwitchReason.MAX_LOSS, {
                "drawdown_pct": str(drawdown_pct),
                "threshold": str(threshold),
            })
            return True

        return False

    def trigger_api_error(self, error_message: str = "") -> bool:
        """Trigger kill switch due to API disconnection or failure.

        Automatically activates kill switch when critical API errors
        occur to prevent trading on stale or invalid data.

        Args:
            error_message: Description of the API error

        Returns:
            True if kill switch was activated, False otherwise
        """
        if self._state.is_active:
            return True

        self.logger.critical(
            "API error detected - activating kill switch",
            error_message=error_message,
        )
        self._activate(KillSwitchReason.API_ERROR, {
            "error_message": error_message,
        })
        return True

    def _activate(
        self,
        reason: KillSwitchReason,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Internal method to activate kill switch.

        Args:
            reason: Reason for activation
            metadata: Additional context information
        """
        self._state.is_active = True
        self._state.reason = reason
        self._state.activated_at = datetime.utcnow().isoformat()
        self._state.metadata = metadata or {}

        severity_map = {
            KillSwitchReason.MANUAL: "warning",
            KillSwitchReason.MAX_LOSS: "critical",
            KillSwitchReason.API_ERROR: "critical",
        }

        self.logger.critical(
            "Kill switch activated",
            reason=reason.name,
            activated_at=self._state.activated_at,
        )

        audit_risk_event(
            event_type="kill_switch_activated",
            severity=severity_map.get(reason, "critical"),
            message=f"Kill switch activated: {reason.name}",
            metadata={
                "reason": reason.name,
                "activated_at": self._state.activated_at,
                **(metadata or {}),
            },
        )

    def get_status(self) -> Dict[str, Any]:
        """Get current kill switch status information.

        Returns:
            Dictionary with current state details
        """
        return {
            "is_active": self._state.is_active,
            "reason": self._state.reason.name if self._state.reason else None,
            "activated_at": self._state.activated_at,
            "positions_closed": self._state.positions_closed,
            "total_pnl": str(self._state.total_pnl),
            "max_drawdown_pct": str(self.max_drawdown_pct),
            "require_confirmation": self.require_confirmation,
            "metadata": self._state.metadata,
        }
