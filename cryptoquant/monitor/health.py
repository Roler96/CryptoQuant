"""Health check endpoint for monitoring system status."""
import time
from dataclasses import dataclass, field

from loguru import logger

from cryptoquant.data.closed_bar import ClosedBarFeed
from cryptoquant.data.live_feed import LiveDataFeed


@dataclass
class HealthStatus:
    """System health snapshot."""

    exchange_ok: bool
    data_fresh: bool
    balance_sane: bool
    risk_ok: bool
    last_check_ts: int
    details: dict = field(default_factory=dict)


class HealthChecker:
    """Performs health checks on trading system components."""

    def __init__(
        self,
        max_data_staleness_ms: int = 300_000,
        min_balance_threshold: float = 50.0,
        quote_currency: str = "USDT",
    ):
        self.max_data_staleness_ms = max_data_staleness_ms
        self.min_balance_threshold = min_balance_threshold
        self.quote_currency = quote_currency

    def check(
        self, broker, data_feed: LiveDataFeed | ClosedBarFeed, risk_manager
    ) -> HealthStatus:
        """Run all health checks and return aggregated status.

        Args:
            broker: Broker instance for exchange/balance checks.
            data_feed: LiveDataFeed | ClosedBarFeed instance for data freshness checks.
            risk_manager: RiskManager instance for risk state checks.

        Returns:
            HealthStatus with all check results.
        """
        now_ms = int(time.time() * 1000)
        details: dict = {}

        symbol = getattr(data_feed, "symbol", "BTC/USDT")
        exchange_ok, exchange_detail = self._check_exchange(broker, symbol)
        details["exchange"] = exchange_detail

        data_fresh, data_detail = self._check_data_freshness(data_feed)
        details["data"] = data_detail

        balance_sane, balance_detail = self._check_balance_sanity(broker)
        details["balance"] = balance_detail

        risk_ok, risk_detail = self._check_risk_state(risk_manager)
        details["risk"] = risk_detail

        status = HealthStatus(
            exchange_ok=exchange_ok,
            data_fresh=data_fresh,
            balance_sane=balance_sane,
            risk_ok=risk_ok,
            last_check_ts=now_ms,
            details=details,
        )

        if not all([exchange_ok, data_fresh, balance_sane, risk_ok]):
            logger.warning(f"Health check failed: {details}")

        return status

    def _check_exchange(self, broker, symbol: str) -> tuple[bool, str]:
        try:
            ticker = broker.get_ticker(symbol)
            if ticker.get("last", 0) > 0:
                return True, "connected"
            return False, "zero price"
        except Exception as e:
            return False, f"error: {e}"

    def _check_data_freshness(
        self, data_feed: LiveDataFeed | ClosedBarFeed
    ) -> tuple[bool, str]:
        try:
            last_fetch = data_feed.last_fetch_ts
            if time.time() * 1000 - last_fetch < self.max_data_staleness_ms:
                return True, f"last fetch {last_fetch}"
            return False, "data stale"
        except Exception as e:
            return False, f"error: {e}"

    def _check_balance_sanity(self, broker) -> tuple[bool, str]:
        try:
            balance = broker.get_balance(self.quote_currency)
            if balance >= self.min_balance_threshold:
                return True, f"{balance:.2f} {self.quote_currency}"
            return False, f"balance {balance:.2f} < {self.min_balance_threshold}"
        except Exception as e:
            return False, f"error: {e}"

    def _check_risk_state(self, risk_manager) -> tuple[bool, str]:
        try:
            if risk_manager.is_emergency_stop():
                return False, "emergency stop active"
            tier = risk_manager.current_tier()
            if tier.value != "normal":
                return False, f"drawdown tier: {tier.value}"
            return True, "normal"
        except Exception as e:
            return False, f"error: {e}"
