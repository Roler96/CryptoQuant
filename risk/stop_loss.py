"""Stop loss management module for CryptoQuant risk management.

Provides stop-loss calculation methods including percentage-based,
trailing stops, and volatility-based stops for risk control.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

import structlog


logger = structlog.get_logger(__name__)


class StopLossMethod(Enum):
    """Stop loss calculation methods."""
    PERCENTAGE = auto()
    TRAILING = auto()
    VOLATILITY = auto()


@dataclass
class StopLossResult:
    """Result of stop loss calculation.

    Attributes:
        stop_price: Calculated stop price
        method: Stop loss method used
        is_triggered: Whether stop has been triggered
        highest_price: Highest price seen (for trailing stops)
        lowest_price: Lowest price seen (for trailing stops on shorts)
        metadata: Additional calculation data
    """
    stop_price: Decimal
    method: StopLossMethod
    is_triggered: bool = False
    highest_price: Optional[Decimal] = None
    lowest_price: Optional[Decimal] = None
    metadata: Dict[str, Decimal] = field(default_factory=dict)


@dataclass
class TrailingStopState:
    """State for tracking trailing stop progress.

    Attributes:
        entry_price: Initial entry price
        highest_price: Highest price seen since entry
        lowest_price: Lowest price seen since entry
        current_stop: Current stop price level
        side: Position side ("long" or "short")
    """
    entry_price: Decimal
    highest_price: Decimal
    lowest_price: Decimal
    current_stop: Decimal
    side: str = "long"


class StopLossManager:
    """Stop loss calculator and manager with multiple stop types.

    Provides methods for calculating stop loss prices:
    - Fixed percentage from entry
    - Trailing stops that follow price
    - Volatility-based stops using ATR or standard deviation

    Attributes:
        logger: Structured logger
    """

    def __init__(self) -> None:
        """Initialize stop loss manager."""
        self.logger = structlog.get_logger(__name__)
        self._trailing_states: Dict[str, TrailingStopState] = {}

    def calculate_stop(
        self,
        entry_price: Decimal,
        method: str = "percentage",
        stop_pct: Decimal = Decimal('0.05'),
        side: str = "long",
        **kwargs
    ) -> StopLossResult:
        """Calculate stop loss price using specified method.

        Args:
            entry_price: Position entry price
            method: Stop calculation method ("percentage", "trailing", "volatility")
            stop_pct: Stop percentage distance from entry (default 5%)
            side: Position side ("long" or "short")
            **kwargs: Additional method-specific arguments

        Returns:
            StopLossResult with calculated stop price

        Raises:
            ValueError: If method is not recognized
        """
        if entry_price <= 0:
            raise ValueError("Entry price must be positive")

        if method == "percentage":
            stop_price = self.percentage_stop(entry_price, stop_pct, side)
            return StopLossResult(
                stop_price=stop_price,
                method=StopLossMethod.PERCENTAGE,
                highest_price=entry_price if side == "long" else None,
                lowest_price=entry_price if side == "short" else None
            )

        elif method == "trailing":
            trail_pct = kwargs.get('trail_pct', stop_pct)
            return self.trailing_stop(entry_price, entry_price, trail_pct, side)

        elif method == "volatility":
            recent_volatility = kwargs.get('recent_volatility')
            if recent_volatility is None:
                raise ValueError("recent_volatility required for volatility stop")
            multiplier = kwargs.get('multiplier', Decimal('2'))
            stop_price = self.volatility_stop(entry_price, recent_volatility, multiplier, side)
            return StopLossResult(
                stop_price=stop_price,
                method=StopLossMethod.VOLATILITY,
                highest_price=entry_price if side == "long" else None,
                lowest_price=entry_price if side == "short" else None,
                metadata={"multiplier": multiplier, "volatility": recent_volatility}
            )

        else:
            raise ValueError(f"Unknown stop loss method: {method}")

    def percentage_stop(
        self,
        entry_price: Decimal,
        stop_pct: Decimal,
        side: str = "long"
    ) -> Decimal:
        """Calculate stop price as percentage distance from entry.

        For longs: stop = entry * (1 - stop_pct)
        For shorts: stop = entry * (1 + stop_pct)

        Args:
            entry_price: Position entry price
            stop_pct: Stop percentage (e.g., 0.05 for 5%)
            side: Position side ("long" or "short")

        Returns:
            Stop loss price
        """
        if entry_price <= 0:
            raise ValueError("Entry price must be positive")

        if stop_pct <= 0:
            raise ValueError("Stop percentage must be positive")

        if side == "long":
            stop_price = entry_price * (Decimal('1') - stop_pct)
        elif side == "short":
            stop_price = entry_price * (Decimal('1') + stop_pct)
        else:
            raise ValueError(f"Invalid side: {side}. Must be 'long' or 'short'")

        self.logger.debug(
            "Percentage stop calculated",
            entry_price=entry_price,
            stop_pct=stop_pct,
            side=side,
            stop_price=stop_price
        )

        return stop_price

    def trailing_stop(
        self,
        current_price: Decimal,
        highest_price: Decimal,
        trail_pct: Decimal,
        side: str = "long"
    ) -> StopLossResult:
        """Calculate trailing stop price.

        For longs: stop = highest * (1 - trail_pct)
        For shorts: stop = lowest * (1 + trail_pct)

        Args:
            current_price: Current market price
            highest_price: Highest price seen since entry
            trail_pct: Trail percentage distance (e.g., 0.05 for 5%)
            side: Position side ("long" or "short")

        Returns:
            StopLossResult with trailing stop price
        """
        if current_price <= 0:
            raise ValueError("Current price must be positive")

        if trail_pct <= 0:
            raise ValueError("Trail percentage must be positive")

        if side == "long":
            stop_price = highest_price * (Decimal('1') - trail_pct)
        elif side == "short":
            stop_price = highest_price * (Decimal('1') + trail_pct)
        else:
            raise ValueError(f"Invalid side: {side}. Must be 'long' or 'short'")

        is_triggered = self.check_trigger(current_price, stop_price, side)

        result = StopLossResult(
            stop_price=stop_price,
            method=StopLossMethod.TRAILING,
            is_triggered=is_triggered,
            highest_price=highest_price if side == "long" else None,
            lowest_price=highest_price if side == "short" else None
        )

        self.logger.debug(
            "Trailing stop calculated",
            current_price=current_price,
            highest_price=highest_price,
            trail_pct=trail_pct,
            side=side,
            stop_price=stop_price,
            is_triggered=is_triggered
        )

        return result

    def volatility_stop(
        self,
        entry_price: Decimal,
        recent_volatility: Decimal,
        multiplier: Decimal = Decimal('2'),
        side: str = "long"
    ) -> Decimal:
        """Calculate stop price based on volatility (e.g., 2x ATR).

        Stop distance = volatility * multiplier
        For longs: stop = entry - distance
        For shorts: stop = entry + distance

        Args:
            entry_price: Position entry price
            recent_volatility: Recent volatility measure (e.g., ATR, std dev)
            multiplier: Volatility multiplier (default 2.0 for 2x ATR)
            side: Position side ("long" or "short")

        Returns:
            Stop loss price based on volatility
        """
        if entry_price <= 0:
            raise ValueError("Entry price must be positive")

        if recent_volatility < 0:
            raise ValueError("Volatility cannot be negative")

        if multiplier <= 0:
            raise ValueError("Multiplier must be positive")

        stop_distance = recent_volatility * multiplier

        if side == "long":
            stop_price = entry_price - stop_distance
        elif side == "short":
            stop_price = entry_price + stop_distance
        else:
            raise ValueError(f"Invalid side: {side}. Must be 'long' or 'short'")

        self.logger.debug(
            "Volatility stop calculated",
            entry_price=entry_price,
            volatility=recent_volatility,
            multiplier=multiplier,
            stop_distance=stop_distance,
            side=side,
            stop_price=stop_price
        )

        return stop_price

    def check_trigger(
        self,
        current_price: Decimal,
        stop_price: Decimal,
        side: str = "long"
    ) -> bool:
        """Check if stop loss has been triggered.

        For longs: triggered if current <= stop
        For shorts: triggered if current >= stop

        Args:
            current_price: Current market price
            stop_price: Stop loss price
            side: Position side ("long" or "short")

        Returns:
            True if stop loss is triggered
        """
        if side == "long":
            return current_price <= stop_price
        elif side == "short":
            return current_price >= stop_price
        else:
            raise ValueError(f"Invalid side: {side}. Must be 'long' or 'short'")

    def update_trailing_stop(
        self,
        current_price: Decimal,
        highest_price: Decimal,
        trail_pct: Decimal,
        side: str = "long"
    ) -> StopLossResult:
        """Update trailing stop level based on new price data.

        Recalculates the trailing stop price and checks if triggered.

        Args:
            current_price: Current market price
            highest_price: Highest price seen since entry (for longs)
                            or lowest for shorts
            trail_pct: Trail percentage distance
            side: Position side ("long" or "short")

        Returns:
            Updated StopLossResult
        """
        return self.trailing_stop(current_price, highest_price, trail_pct, side)

    def initialize_trailing_state(
        self,
        position_id: str,
        entry_price: Decimal,
        trail_pct: Decimal,
        side: str = "long"
    ) -> TrailingStopState:
        """Initialize state tracking for a trailing stop position.

        Args:
            position_id: Unique identifier for the position
            entry_price: Position entry price
            trail_pct: Trail percentage
            side: Position side ("long" or "short")

        Returns:
            TrailingStopState instance
        """
        if side == "long":
            current_stop = entry_price * (Decimal('1') - trail_pct)
        else:
            current_stop = entry_price * (Decimal('1') + trail_pct)

        state = TrailingStopState(
            entry_price=entry_price,
            highest_price=entry_price,
            lowest_price=entry_price,
            current_stop=current_stop,
            side=side
        )

        self._trailing_states[position_id] = state

        self.logger.info(
            "Trailing stop state initialized",
            position_id=position_id,
            entry_price=entry_price,
            trail_pct=trail_pct,
            side=side,
            initial_stop=current_stop
        )

        return state

    def update_trailing_state(
        self,
        position_id: str,
        current_price: Decimal,
        trail_pct: Decimal
    ) -> Optional[TrailingStopState]:
        """Update trailing stop state with new price.

        Args:
            position_id: Position identifier
            current_price: Current market price
            trail_pct: Trail percentage

        Returns:
            Updated TrailingStopState or None if position not found
        """
        state = self._trailing_states.get(position_id)
        if state is None:
            self.logger.warning("Trailing state not found", position_id=position_id)
            return None

        if state.side == "long":
            if current_price > state.highest_price:
                state.highest_price = current_price
                state.current_stop = state.highest_price * (Decimal('1') - trail_pct)
        else:  # short
            if current_price < state.lowest_price:
                state.lowest_price = current_price
                state.current_stop = state.lowest_price * (Decimal('1') + trail_pct)

        return state

    def get_trailing_state(self, position_id: str) -> Optional[TrailingStopState]:
        """Get trailing stop state for a position.

        Args:
            position_id: Position identifier

        Returns:
            TrailingStopState or None if not found
        """
        return self._trailing_states.get(position_id)

    def remove_trailing_state(self, position_id: str) -> bool:
        """Remove trailing stop state for a closed position.

        Args:
            position_id: Position identifier

        Returns:
            True if state was removed, False if not found
        """
        if position_id in self._trailing_states:
            del self._trailing_states[position_id]
            self.logger.info("Trailing state removed", position_id=position_id)
            return True
        return False

    def validate_position(self, position: Dict) -> Tuple[bool, List[str]]:
        """Validate that a position has proper stop loss configuration.

        Mandatory stop-loss check - all positions must have stop loss.

        Args:
            position: Position dictionary with keys like 'entry_price', 'stop_price', etc.

        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        errors: List[str] = []

        if not position:
            errors.append("Position cannot be empty")
            return False, errors

        entry_price = position.get('entry_price')
        if entry_price is None:
            errors.append("Position must have entry_price")
        elif entry_price <= 0:
            errors.append("Entry price must be positive")

        stop_price = position.get('stop_price')
        if stop_price is None:
            errors.append("Position MUST have a stop loss (stop_price is required)")
        elif stop_price <= 0:
            errors.append("Stop price must be positive")

        side = position.get('side', 'long')
        if side not in ('long', 'short'):
            errors.append("Side must be 'long' or 'short'")

        if entry_price and stop_price and side:
            if side == 'long' and stop_price >= entry_price:
                errors.append("Long position stop must be below entry price")
            elif side == 'short' and stop_price <= entry_price:
                errors.append("Short position stop must be above entry price")

        is_valid = len(errors) == 0

        if not is_valid:
            self.logger.warning(
                "Position validation failed - stop loss required",
                position=position,
                errors=errors
            )

        return is_valid, errors

    def calculate_risk_amount(
        self,
        entry_price: Decimal,
        stop_price: Decimal,
        position_size: Decimal
    ) -> Decimal:
        """Calculate dollar amount at risk based on stop distance.

        Args:
            entry_price: Position entry price
            stop_price: Stop loss price
            position_size: Position size

        Returns:
            Dollar amount at risk
        """
        stop_distance = abs(entry_price - stop_price)
        risk_amount = stop_distance * position_size

        self.logger.debug(
            "Risk amount calculated",
            entry_price=entry_price,
            stop_price=stop_price,
            position_size=position_size,
            risk_amount=risk_amount
        )

        return risk_amount

    def calculate_risk_pct(
        self,
        entry_price: Decimal,
        stop_price: Decimal
    ) -> Decimal:
        """Calculate risk as percentage of entry price.

        Args:
            entry_price: Position entry price
            stop_price: Stop loss price

        Returns:
            Risk percentage
        """
        if entry_price == 0:
            return Decimal('0')

        stop_distance = abs(entry_price - stop_price)
        return stop_distance / entry_price
