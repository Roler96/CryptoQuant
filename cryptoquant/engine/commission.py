"""Commission models for backtesting and simulation."""
from abc import ABC, abstractmethod


class CommissionModel(ABC):
    """Abstract base class for commission models."""

    @abstractmethod
    def calculate(
        self, price: float, amount: float, side: str, is_maker: bool = False
    ) -> float:
        """Return commission in same currency as ``price`` (usually quote).

        Args:
            price: Fill price.
            amount: Fill amount (base currency).
            side: ``"buy"`` or ``"sell"``.
            is_maker: Whether the order is a maker (limit) order.

        Returns:
            Absolute commission value.
        """
        ...


class FlatCommission(CommissionModel):
    """Fixed percentage commission (current behavior)."""

    def __init__(self, commission: float = 0.001):
        self.commission = commission

    def calculate(
        self, price: float, amount: float, side: str, is_maker: bool = False
    ) -> float:
        return price * amount * self.commission


class TieredCommission(CommissionModel):
    """Exchange-agnostic tiered commission.

    Tiers default to:
        taker      = 0.0005
        maker      = 0.0003
        vip_taker  = 0.0003
        vip_maker  = 0.0001
    """

    def __init__(
        self,
        tiers: dict[str, float] | None = None,
        vip: bool = False,
    ):
        default = {
            "taker": 0.0005,
            "maker": 0.0003,
            "vip_taker": 0.0003,
            "vip_maker": 0.0001,
        }
        self.tiers = {**default, **(tiers or {})}
        self.vip = vip

    def calculate(
        self, price: float, amount: float, side: str, is_maker: bool = False
    ) -> float:
        tier_key = f"{'vip_' if self.vip else ''}{'maker' if is_maker else 'taker'}"
        rate = self.tiers.get(tier_key, self.tiers["taker"])
        return price * amount * rate
