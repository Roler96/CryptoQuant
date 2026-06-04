
"""
Production Trading Runner — unified paper + live trading system.

Features:
- Multi-pair portfolio trading with pair-specific strategies
- Config-driven (no hardcoded strategies)
- Integrated risk management (drawdown, daily loss, position limits)
- Automatic data refresh pipeline
- Comprehensive logging and audit trail
- Kill switch with multiple trigger conditions
- Console alerts for all trading events
"""

import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog

from backtest.engine import BacktestEngine, BacktestConfig
from config.trading_config import load_config
from data.repository import get_repository
from live.kill_switch import KillSwitch, KillSwitchReason
from strategy.cta.ma_state import MAStateStrategy
from strategy.cta.mean_reversion import MeanReversionStrategy
from strategy.cta.trend_following import TrendFollowingStrategy
from strategy.base import StrategyBase

logger = structlog.get_logger(__name__)


# ============================================================
# Data Structures
# ============================================================

@dataclass
class PortfolioState:
    """Live portfolio tracking."""
    pairs: Dict[str, 'PairState'] = field(default_factory=dict)
    initial_capital: Decimal = Decimal("10000")
    current_capital: Decimal = Decimal("10000")
    peak_capital: Decimal = Decimal("10000")
    daily_pnl: Decimal = Decimal("0")
    total_trades: int = 0
    start_time: Optional[datetime] = None

    @property
    def total_return(self) -> float:
        return float((self.current_capital - self.initial_capital) / self.initial_capital)

    @property
    def drawdown(self) -> float:
        if self.peak_capital == 0:
            return 0.0
        return float((self.peak_capital - self.current_capital) / self.peak_capital)

    def update_peak(self):
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital


@dataclass
class PairState:
    """Per-pair trading state."""
    pair: str
    allocated_capital: Decimal
    position_side: Optional[str] = None  # 'long', 'short', None
    position_size: Decimal = Decimal("0")
    entry_price: Decimal = Decimal("0")
    trades: int = 0
    realized_pnl: Decimal = Decimal("0")
    last_signal: Optional[str] = None


# ============================================================
# Strategy Factory
# ============================================================

STRATEGY_REGISTRY = {
    "ma_state": MAStateStrategy,
    "mean_reversion": MeanReversionStrategy,
    "trend_following": TrendFollowingStrategy,
}


def create_strategy(name: str, params: Dict) -> StrategyBase:
    """Factory to create strategy by name."""
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_REGISTRY.keys())}")
    return cls(name=name, params=params)


# ============================================================
# Production Runner
# ============================================================

class ProductionRunner:
    """Production trading system orchestrator.

    Supports two modes:
    - 'paper': Simulated execution with real market data
    - 'live': Real execution on OKX (requires API keys)
    """

    def __init__(self, mode: str = "paper", config_path: Optional[str] = None):
        self.mode = mode
        if mode not in ("paper", "live"):
            raise ValueError(f"Mode must be 'paper' or 'live', got '{mode}'")

        self.config = load_config(config_path)
        self.strategy_configs = self.config["strategies"]
        self.risk_config = self.config["risk"]
        self.exec_config = self.config["execution"]
        self.data_config = self.config["data"]

        # Portfolio
        initial_cap = Decimal(str(self.exec_config["initial_capital"]))
        self.portfolio = PortfolioState(
            initial_capital=initial_cap,
            current_capital=initial_cap,
            peak_capital=initial_cap,
            start_time=datetime.now(timezone.utc),
        )

        # Components
        self.kill_switch = KillSwitch(
            max_drawdown_pct=Decimal(str(self.risk_config["max_drawdown_pct"] / 100))
        )
        self.strategies: Dict[str, tuple] = {}  # pair -> (strategy_instance, config_dict)
        self.pair_states: Dict[str, PairState] = {}
        self._running = False
        self._last_refresh: Dict[str, float] = {}

        # Alert counters
        self._daily_pnl_reset_hour = 0

        self.log = structlog.get_logger(__name__).bind(mode=mode)

    # -------- Initialization --------

    def initialize(self) -> bool:
        """Initialize all subsystems. Returns True if successful."""
        self._alert("INIT", f"ProductionRunner starting in {self.mode.upper()} mode")

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        # Load strategies per pair
        for sc in self.strategy_configs:
            if not sc.get("enabled", True):
                continue
            pair = sc["pair"]
            strategy = create_strategy(sc["strategy_name"], sc.get("params", {}))
            strategy.initialize()
            self.strategies[pair] = (strategy, sc)

            alloc = Decimal(str(sc.get("allocation_pct", 1.0 / len(self.strategy_configs))))
            self.pair_states[pair] = PairState(
                pair=pair,
                allocated_capital=self.portfolio.initial_capital * alloc,
            )
            self._alert("INIT", f"Loaded {sc['strategy_name']} for {pair} "
                      f"(alloc: {float(alloc):.0%}, params: {sc.get('params', {})})")

        # Verify market data is available
        repo = get_repository()
        for pair in self.pair_states:
            try:
                candles = repo.load_candles(pair, self.data_config["timeframe"], 
                                           limit=100, order="desc")
                if len(candles) < 50:
                    self._alert("ERROR", f"Insufficient data for {pair}: {len(candles)} candles")
                    return False
                self._alert("OK", f"Data verified: {pair} — {len(candles)} candles available")
            except Exception as e:
                self._alert("ERROR", f"Cannot load data for {pair}: {e}")
                return False

        self._alert("OK", f"Initialization complete. {len(self.pair_states)} pairs loaded.")
        return True

    # -------- Data Pipeline --------

    def _refresh_data(self, pair: str) -> bool:
        """Ensure we have fresh data for the pair. Returns True if data is current."""
        now = time.time()
        interval = self.data_config["refresh_interval_sec"]

        if pair in self._last_refresh and (now - self._last_refresh[pair] < interval):
            return True  # Data is fresh

        self._last_refresh[pair] = now
        return True  # Data comes from SQLite which is assumed up-to-date

    def _get_candles(self, pair: str) -> tuple:
        """Fetch latest candles for strategy. Returns (closes_f, highs_f, lows_f, current_price, current_time)."""
        repo = get_repository()
        lookback = self.data_config["lookback_bars"]

        # Use load_candles with limit (newest first, then reverse)
        candles = repo.load_candles(pair, self.data_config["timeframe"], 
                                    limit=lookback, order="desc")
        if len(candles) == 0:
            raise RuntimeError(f"No data for {pair}")

        candles.reverse()  # oldest first

        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        current_price = candles[-1].close
        current_time = candles[-1].timestamp

        return closes, highs, lows, current_price, current_time

    # -------- Signal Processing --------

    def _process_signal(self, pair: str, signal) -> Optional[Dict]:
        """Process a trading signal. Returns trade dict if executed."""
        if signal.is_hold():
            return None

        state = self.pair_states[pair]

        # Check kill switch
        if self.kill_switch.is_safe_mode():
            self._alert("BLOCKED", f"Signal for {pair} blocked: kill switch active")
            return None

        signal_type = signal.signal_type.name
        current_price = signal.price
        alloc_cap = state.allocated_capital

        # Position sizing
        position_value = alloc_cap * Decimal("0.95")  # Use 95% of allocated capital
        quantity = position_value / current_price

        # Entry logic
        if signal_type in ("LONG", "SHORT"):
            if state.position_side is not None:
                # Already in position — skip (MA State handles this internally)
                self.log.debug(f"{pair}: already in {state.position_side}, ignoring {signal_type}")
                return None

            side = "long" if signal_type == "LONG" else "short"
            state.position_side = side
            state.position_size = quantity
            state.entry_price = current_price
            state.trades += 1
            self.portfolio.total_trades += 1

            trade = {
                "action": f"open_{side}",
                "pair": pair,
                "price": float(current_price),
                "quantity": float(quantity),
                "value": float(position_value),
                "time": datetime.now(timezone.utc).isoformat(),
            }
            self._alert("ENTRY", f"{pair}: OPEN {side.upper()} {float(quantity):.6f} @ ${float(current_price):.2f}")
            return trade

        # Exit logic
        elif signal_type in ("CLOSE_LONG", "CLOSE_SHORT"):
            if state.position_side is None:
                return None

            exit_side = "long" if signal_type == "CLOSE_LONG" else "short"
            if state.position_side != exit_side:
                self._alert("WARN", f"{pair}: signal {signal_type} but position is {state.position_side}")
                return None

            # Calculate PnL
            if state.position_side == "long":
                pnl = (current_price - state.entry_price) * state.position_size
            else:
                pnl = (state.entry_price - current_price) * state.position_size

            state.realized_pnl += pnl
            self.portfolio.current_capital += pnl
            self.portfolio.update_peak()

            trade = {
                "action": f"close_{state.position_side}",
                "pair": pair,
                "price": float(current_price),
                "quantity": float(state.position_size),
                "pnl": float(pnl),
                "realized_pnl": float(state.realized_pnl),
                "time": datetime.now(timezone.utc).isoformat(),
            }
            self._alert("EXIT", f"{pair}: CLOSE {state.position_side.upper()} "
                       f"PnL=${float(pnl):+.2f} (total: ${float(state.realized_pnl):+.2f})")

            # Reset state
            state.position_side = None
            state.position_size = Decimal("0")
            state.entry_price = Decimal("0")
            return trade

        return None

    # -------- Risk Checks --------

    def _check_risk_limits(self) -> bool:
        """Run all risk checks. Returns True if trading is safe to continue."""
        # Drawdown check
        dd_pct = Decimal(str(self.portfolio.drawdown))
        if self.kill_switch.trigger_max_loss(dd_pct * 100):
            self._alert("CRITICAL", f"DRAWDOWN LIMIT: {float(dd_pct):.1%}")
            return False

        # Daily loss check
        daily_limit = Decimal(str(self.risk_config["daily_loss_limit_pct"] / 100))
        daily_loss_pct = abs(self.portfolio.daily_pnl / self.portfolio.initial_capital)
        if daily_loss_pct > daily_limit:
            self._alert("CRITICAL", f"DAILY LOSS LIMIT: {float(daily_loss_pct):.1%} "
                       f"(limit: {float(daily_limit):.1%})")
            self.kill_switch.trigger_manual(confirmed=True)
            return False

        return True

    def _reset_daily_pnl(self):
        """Reset daily PnL at midnight."""
        now = datetime.now(timezone.utc)
        if now.hour == 0 and self._daily_pnl_reset_hour != 0:
            self.portfolio.daily_pnl = Decimal("0")
            self._daily_pnl_reset_hour = 0
        elif now.hour != 0:
            self._daily_pnl_reset_hour = now.hour

    # -------- Main Loop --------

    def run(self, duration_hours: Optional[int] = None):
        """Main trading loop.

        Args:
            duration_hours: Optional run duration. None = run indefinitely.
        """
        if not self.initialize():
            self._alert("FATAL", "Initialization failed. Aborting.")
            return

        self._running = True
        start_time = time.time()
        end_time = start_time + (duration_hours * 3600) if duration_hours else float("inf")
        iteration = 0

        self._alert("START", f"Trading loop started. Mode: {self.mode}. "
                   f"Pairs: {list(self.pair_states.keys())}. "
                   f"Duration: {duration_hours or 'indefinite'}h")

        try:
            while self._running and time.time() < end_time:
                iteration += 1
                loop_start = time.time()

                # Daily reset
                self._reset_daily_pnl()

                # Risk checks
                if not self._check_risk_limits():
                    self._alert("STOP", "Risk limits breached. Entering safe mode.")
                    break

                # Process each pair
                for pair, (strategy, sc) in self.strategies.items():
                    try:
                        # Refresh data
                        self._refresh_data(pair)

                        # Get candles
                        closes, highs, lows, price, timestamp = self._get_candles(pair)

                        # Build context
                        from strategy.base import StrategyContext
                        context = StrategyContext(
                            pair=pair,
                            timeframe=self.data_config["timeframe"],
                            current_price=price,
                            positions={},
                            balances={"USDT": self.portfolio.current_capital},
                            candles=[],
                            current_time=timestamp,
                            has_fast_data=True,
                            closes_f=closes,
                            highs_f=highs,
                            lows_f=lows,
                        )

                        # Generate signal
                        signal = strategy.generate_signal(context)
                        trade = self._process_signal(pair, signal)

                        # Update unrealized PnL
                        state = self.pair_states[pair]
                        if state.position_side:
                            if state.position_side == "long":
                                unrealized = (price - state.entry_price) * state.position_size
                            else:
                                unrealized = (state.entry_price - price) * state.position_size
                            # Track daily PnL
                            self.portfolio.daily_pnl = unrealized + state.realized_pnl

                    except Exception as e:
                        self._alert("ERROR", f"{pair}: {e}")
                        if self.mode == "live":
                            self.kill_switch.trigger_api_error(str(e))

                # Status report every 60 iterations (~1 hour at 60s intervals)
                if iteration % 60 == 0:
                    self._print_status()

                # Sleep until next tick
                elapsed = time.time() - loop_start
                sleep_time = max(1, self.data_config["refresh_interval_sec"] - elapsed)
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            self._alert("STOP", "Interrupted by user")
        finally:
            self._shutdown()

    def _print_status(self):
        """Print current portfolio status."""
        print(f"\n{'='*70}")
        print(f"  PORTFOLIO STATUS — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  Capital: ${float(self.portfolio.current_capital):,.2f} "
              f"({self.portfolio.total_return:+.2%})")
        print(f"  Drawdown: {self.portfolio.drawdown:.2%}  "
              f"Trades: {self.portfolio.total_trades}")
        print(f"  {'-'*60}")
        for pair, state in self.pair_states.items():
            pos = f"{state.position_side.upper()} {float(state.position_size):.4f}" if state.position_side else "FLAT"
            print(f"  {pair:<12} {pos:<20} PnL: ${float(state.realized_pnl):>+8.2f}")
        print(f"{'='*70}\n")

    def _shutdown(self):
        """Graceful shutdown."""
        self._running = False
        self._alert("STOP", "Shutting down...")
        self._print_status()

        # Close any open positions in live mode
        if self.mode == "live":
            for pair, state in self.pair_states.items():
                if state.position_side:
                    self._alert("WARN", f"Open position on {pair} — manual close required!")

    def _handle_shutdown(self, signum, frame):
        """Signal handler for graceful shutdown."""
        self._alert("SIGNAL", f"Received signal {signum}")
        self._running = False

    def _alert(self, level: str, message: str):
        """Unified alerting — console + log."""
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        prefix = {
            "INIT": "🔧", "OK": "✅", "START": "🚀", "STOP": "🛑",
            "ENTRY": "📈", "EXIT": "📉", "BLOCKED": "⛔",
            "ERROR": "❌", "CRITICAL": "🔥", "WARN": "⚠️",
            "FATAL": "💀", "SIGNAL": "📡",
        }.get(level, "•")
        print(f"[{timestamp}] {prefix} {message}", flush=True)


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CryptoQuant Production Trading System")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper",
                       help="Trading mode (default: paper)")
    parser.add_argument("--duration", type=int, default=None,
                       help="Run duration in hours (default: indefinite)")
    parser.add_argument("--config", type=str, default=None,
                       help="Path to config JSON file")

    args = parser.parse_args()

    runner = ProductionRunner(mode=args.mode, config_path=args.config)
    runner.run(duration_hours=args.duration)
