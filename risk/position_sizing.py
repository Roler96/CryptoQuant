"""Position sizing module for CryptoQuant risk management.

Provides position sizing methods including fixed percentage, volatility-based,
and Kelly criterion calculations for optimal position sizing.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import structlog


logger = structlog.get_logger(__name__)


@dataclass
class PositionSizeResult:
    """Result of position size calculation.

    Attributes:
        size: Calculated position size
        method: Sizing method used
        risk_amount: Dollar amount at risk
        is_valid: Whether position passes validation
        validation_errors: List of validation error messages
    """
    size: Decimal
    method: str
    risk_amount: Decimal
    is_valid: bool
    validation_errors: List[str] = field(default_factory=list)


@dataclass
class PositionLimits:
    """Position sizing limits and constraints.

    Attributes:
        max_position_pct: Maximum position size as percentage of portfolio (default 0.3 = 30%)
        max_leverage: Maximum allowed leverage (default 2.0 = 2x)
        min_position_size: Minimum position size in base currency
        max_position_size: Maximum position size in base currency (optional)
    """
    max_position_pct: Decimal = Decimal('0.3')
    max_leverage: Decimal = Decimal('2.0')
    min_position_size: Decimal = Decimal('0.001')
    max_position_size: Optional[Decimal] = None


class PositionSizer:
    """Position sizing calculator with multiple sizing methods.

    Provides methods for calculating position sizes based on:
    - Fixed percentage of portfolio
    - Volatility-adjusted sizing
    - Kelly criterion

    Attributes:
        limits: PositionLimits instance with constraints
        logger: Structured logger
    """

    def __init__(self, limits: Optional[PositionLimits] = None) -> None:
        """Initialize position sizer with limits.

        Args:
            limits: PositionLimits instance (uses defaults if None)
        """
        self.limits = limits or PositionLimits()
        self.logger = structlog.get_logger(__name__)

    def fixed_pct(
        self,
        portfolio_value: Decimal,
        risk_pct: Decimal,
        price: Decimal
    ) -> PositionSizeResult:
        """Calculate position size as fixed percentage of portfolio.

        Position size = (portfolio_value * risk_pct) / price

        Args:
            portfolio_value: Total portfolio value
            risk_pct: Risk percentage (e.g., 0.02 for 2%)
            price: Current asset price

        Returns:
            PositionSizeResult with calculated size and validation
        """
        if price <= 0:
            error_msg = "Price must be positive"
            self.logger.error(error_msg, price=price)
            return PositionSizeResult(
                size=Decimal('0'),
                method="fixed_pct",
                risk_amount=Decimal('0'),
                is_valid=False,
                validation_errors=[error_msg]
            )

        risk_amount = portfolio_value * risk_pct
        size = risk_amount / price

        result = PositionSizeResult(
            size=size,
            method="fixed_pct",
            risk_amount=risk_amount,
            is_valid=True
        )

        result = self._apply_validation(size, portfolio_value, result)

        self.logger.debug(
            "Fixed percentage sizing calculated",
            portfolio_value=portfolio_value,
            risk_pct=risk_pct,
            price=price,
            size=result.size,
            is_valid=result.is_valid
        )

        return result

    def volatility_based(
        self,
        portfolio_value: Decimal,
        risk_pct: Decimal,
        price: Decimal,
        recent_volatility: Decimal,
        target_volatility: Decimal = Decimal('0.02'),
        lookback_periods: int = 20
    ) -> PositionSizeResult:
        """Calculate position size adjusted for volatility.

        Position is scaled inversely to volatility - higher volatility
        results in smaller positions to maintain constant risk exposure.

        Args:
            portfolio_value: Total portfolio value
            risk_pct: Risk percentage (e.g., 0.02 for 2%)
            price: Current asset price
            recent_volatility: Recent price volatility (standard deviation)
            target_volatility: Target volatility level (default 2%)
            lookback_periods: Number of periods for volatility calculation

        Returns:
            PositionSizeResult with volatility-adjusted size
        """
        if price <= 0:
            error_msg = "Price must be positive"
            self.logger.error(error_msg, price=price)
            return PositionSizeResult(
                size=Decimal('0'),
                method="volatility_based",
                risk_amount=Decimal('0'),
                is_valid=False,
                validation_errors=[error_msg]
            )

        if recent_volatility <= 0:
            error_msg = "Volatility must be positive"
            self.logger.error(error_msg, volatility=recent_volatility)
            return PositionSizeResult(
                size=Decimal('0'),
                method="volatility_based",
                risk_amount=Decimal('0'),
                is_valid=False,
                validation_errors=[error_msg]
            )

        base_risk_amount = portfolio_value * risk_pct

        volatility_ratio = target_volatility / recent_volatility
        adjusted_risk_amount = base_risk_amount * volatility_ratio

        size = adjusted_risk_amount / price

        result = PositionSizeResult(
            size=size,
            method="volatility_based",
            risk_amount=adjusted_risk_amount,
            is_valid=True
        )

        result = self._apply_validation(size, portfolio_value, result)

        self.logger.debug(
            "Volatility-based sizing calculated",
            portfolio_value=portfolio_value,
            risk_pct=risk_pct,
            recent_volatility=recent_volatility,
            target_volatility=target_volatility,
            volatility_ratio=volatility_ratio,
            size=result.size,
            is_valid=result.is_valid
        )

        return result

    def kelly(
        self,
        portfolio_value: Decimal,
        win_rate: Decimal,
        win_loss_ratio: Decimal,
        price: Decimal,
        kelly_fraction: Decimal = Decimal('0.5')
    ) -> PositionSizeResult:
        """Calculate position size using Kelly criterion.

        Kelly formula: f = (p*b - q) / b
        Where:
            f = fraction of portfolio to risk
            p = win rate (probability of win)
            q = loss rate (1 - p)
            b = win/loss ratio (average win / average loss)

        The full Kelly can be aggressive, so kelly_fraction (default 0.5 = Half Kelly)
        is applied to reduce risk.

        Args:
            portfolio_value: Total portfolio value
            win_rate: Probability of winning (0.0 to 1.0)
            win_loss_ratio: Average win size / average loss size
            price: Current asset price
            kelly_fraction: Fraction of full Kelly to use (default 0.5)

        Returns:
            PositionSizeResult with Kelly-optimal size
        """
        if price <= 0:
            error_msg = "Price must be positive"
            self.logger.error(error_msg, price=price)
            return PositionSizeResult(
                size=Decimal('0'),
                method="kelly",
                risk_amount=Decimal('0'),
                is_valid=False,
                validation_errors=[error_msg]
            )

        if win_rate <= 0 or win_rate >= 1:
            error_msg = "Win rate must be between 0 and 1"
            self.logger.error(error_msg, win_rate=win_rate)
            return PositionSizeResult(
                size=Decimal('0'),
                method="kelly",
                risk_amount=Decimal('0'),
                is_valid=False,
                validation_errors=[error_msg]
            )

        if win_loss_ratio <= 0:
            error_msg = "Win/loss ratio must be positive"
            self.logger.error(error_msg, win_loss_ratio=win_loss_ratio)
            return PositionSizeResult(
                size=Decimal('0'),
                method="kelly",
                risk_amount=Decimal('0'),
                is_valid=False,
                validation_errors=[error_msg]
            )

        loss_rate = Decimal('1') - win_rate

        kelly_pct = (win_rate * win_loss_ratio - loss_rate) / win_loss_ratio

        if kelly_pct <= 0:
            warning_msg = "Kelly criterion suggests no position (negative expectancy)"
            self.logger.warning(
                warning_msg,
                win_rate=win_rate,
                win_loss_ratio=win_loss_ratio,
                kelly_pct=kelly_pct
            )
            return PositionSizeResult(
                size=Decimal('0'),
                method="kelly",
                risk_amount=Decimal('0'),
                is_valid=False,
                validation_errors=[warning_msg]
            )

        adjusted_kelly_pct = kelly_pct * kelly_fraction
        risk_amount = portfolio_value * adjusted_kelly_pct
        size = risk_amount / price

        result = PositionSizeResult(
            size=size,
            method="kelly",
            risk_amount=risk_amount,
            is_valid=True
        )

        result = self._apply_validation(size, portfolio_value, result)

        self.logger.debug(
            "Kelly sizing calculated",
            portfolio_value=portfolio_value,
            win_rate=win_rate,
            win_loss_ratio=win_loss_ratio,
            kelly_pct=kelly_pct,
            kelly_fraction=kelly_fraction,
            adjusted_kelly_pct=adjusted_kelly_pct,
            size=result.size,
            is_valid=result.is_valid
        )

        return result

    def validate_position(
        self,
        position_size: Decimal,
        portfolio_value: Decimal,
        max_position_pct: Optional[Decimal] = None
    ) -> Tuple[bool, List[str]]:
        """Validate position size against limits.

        Checks:
        - Position size doesn't exceed max_position_pct of portfolio
        - Position size meets minimum size requirement
        - Position size doesn't exceed max_position_size if set
        - Leverage doesn't exceed max_leverage

        Args:
            position_size: Calculated position size
            portfolio_value: Total portfolio value
            max_position_pct: Override max position percentage (uses self.limits if None)

        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        errors: List[str] = []

        max_pct = max_position_pct if max_position_pct is not None else self.limits.max_position_pct

        if position_size < 0:
            errors.append("Position size cannot be negative")
            return False, errors

        if position_size == 0:
            return True, errors

        position_value = position_size

        if portfolio_value > 0:
            position_pct = position_value / portfolio_value
            if position_pct > max_pct:
                errors.append(
                    f"Position size {position_pct:.2%} exceeds max {max_pct:.2%}"
                )

        if position_size < self.limits.min_position_size:
            errors.append(
                f"Position size {position_size} below minimum {self.limits.min_position_size}"
            )

        if self.limits.max_position_size is not None:
            if position_size > self.limits.max_position_size:
                errors.append(
                    f"Position size {position_size} exceeds maximum {self.limits.max_position_size}"
                )

        if portfolio_value > 0:
            leverage = position_value / portfolio_value
            if leverage > self.limits.max_leverage:
                errors.append(
                    f"Leverage {leverage:.2f}x exceeds max {self.limits.max_leverage}x"
                )

        is_valid = len(errors) == 0

        if not is_valid:
            self.logger.warning(
                "Position validation failed",
                position_size=position_size,
                portfolio_value=portfolio_value,
                errors=errors
            )

        return is_valid, errors

    def _apply_validation(
        self,
        size: Decimal,
        portfolio_value: Decimal,
        result: PositionSizeResult
    ) -> PositionSizeResult:
        """Apply validation to a PositionSizeResult.

        Args:
            size: Position size to validate
            portfolio_value: Total portfolio value
            result: PositionSizeResult to update

        Returns:
            Updated PositionSizeResult with validation results
        """
        is_valid, errors = self.validate_position(size, portfolio_value)
        result.is_valid = is_valid
        result.validation_errors = errors
        return result

    def get_limits(self) -> PositionLimits:
        """Get current position limits.

        Returns:
            PositionLimits instance
        """
        return self.limits

    def set_limits(self, limits: PositionLimits) -> None:
        """Update position limits.

        Args:
            limits: New PositionLimits instance
        """
        self.limits = limits
        self.logger.info("Position limits updated", limits=limits)
