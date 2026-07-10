"""Live trading runner — production entry point.

Automates wiring of all components (config, broker, data, risk, strategy)
and starts the live trading loop with health checks and graceful shutdown.

Usage:
    uv run python live_runner.py [--symbol BTC/USDT] [--timeframe 1h] [--interval 60]
"""

import argparse
import os
import sys
import time

from loguru import logger

from cryptoquant.config import load_config
from cryptoquant.data.fetcher import OHLCVFetcher
from cryptoquant.data.live_feed import LiveDataFeed
from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.live import LiveEngine
from cryptoquant.execution.broker import Broker
from cryptoquant.monitor.alerts import AlertHandler
from cryptoquant.monitor.health import HealthChecker
from cryptoquant.monitor.journal import TradeJournal
from cryptoquant.monitor.logger import setup_logging
from cryptoquant.risk.manager import RiskManager
from cryptoquant.strategy.base import Strategy


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="CryptoQuant Live Trading Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--symbol", default="BTC/USDT", help="Trading symbol (default: BTC/USDT)"
    )
    p.add_argument(
        "--timeframe", default=None,
        help="OHLCV timeframe (default: from config trading.default_timeframe)"
    )
    p.add_argument(
        "--interval", type=int, default=60,
        help="Tick interval in seconds (default: 60)"
    )
    p.add_argument(
        "--config", default=None,
        help="Path to config.yaml (default: project root)"
    )
    p.add_argument(
        "--strategy", default=None,
        help="Strategy name (module name in strategies/ package, e.g. bb_upper_breakout)"
    )
    p.add_argument(
        "--state-dir", default="state",
        help="Directory for state persistence (default: state/)"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Validate setup without starting trade loop"
    )
    p.add_argument(
        "--paper", action="store_true",
        help="Use PaperBroker (local simulation, no exchange API needed). "
             "Overrides config.paper_trading.enabled"
    )
    p.add_argument(
        "--live", action="store_true",
        help="Acknowledge LIVE trading risks. Required when testnet=false. "
             "Without this flag, live (non-testnet) startup is blocked."
    )
    p.add_argument(
        "--no-reconcile", action="store_true",
        help="Skip exchange reconciliation on startup"
    )
    return p


def resolve_strategy(strategy_name: str | None, config) -> Strategy:
    """Resolve strategy class from name or config."""
    if strategy_name:
        name = strategy_name
    else:
        name = getattr(config.trading, "strategy", None)

    if not name:
        logger.error(
            "No strategy specified. Use --strategy or set trading.strategy in config.yaml"
        )
        sys.exit(1)

    # Try to import from strategies package
    try:
        import importlib
        module = importlib.import_module(f"strategies.{name}")

        # Find the Strategy subclass (skip the base class and re-exports)
        strategy_cls = None
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, Strategy)
                and obj is not Strategy
            ):
                strategy_cls = obj
                break

        if strategy_cls:
            return strategy_cls()
    except ImportError:
        pass

    logger.error(f"Strategy '{name}' not found in strategies/ package")
    sys.exit(1)


def health_check_startup(broker, data_feed, risk_manager) -> bool:
    """Run health check on startup. Returns True if healthy."""
    checker = HealthChecker()
    try:
        status = checker.check(broker, data_feed, risk_manager)
        if not all([
            status.exchange_ok,
            status.data_fresh,
            status.balance_sane,
        ]):
            logger.error(
                f"Startup health check FAILED: {status.details}"
            )
            return False
        logger.info(f"Startup health check PASSED: balance={status.details.get('balance', 'N/A')}")
        return True
    except Exception as e:
        logger.error(f"Startup health check error: {e}")
        return False


def main():
    args = build_argparser().parse_args()

    # 1. Load config
    config = load_config(args.config)
    logger.info(f"Config loaded: exchange={config.exchange.default}")

    # 2. Setup logging
    setup_logging(
        level=config.logging.level,
        log_dir=config.logging.dir,
        json_format=getattr(config.logging, "json_format", False),
        alert_handler=(
            AlertHandler(
                webhook_url=config.alert.webhook_url,
                alert_levels=config.alert.alert_levels,
            )
            if config.alert.webhook_url
            else None
        ),
    )
    logger.info("Logging initialized")

    # 2.5. P0 SAFETY GATE — refuse non-testnet startup until P0 issues resolved.
    #      See docs/review-2026-07-10.md for unresolved P0 items.
    okx_cfg = config.exchange.okx
    if not okx_cfg.testnet:
        live_allowed = os.environ.get("LIVE_MODE_ALLOWED", "").lower() in (
            "1", "true", "yes"
        )

        if not args.live and not live_allowed:
            logger.error(
                "LIVE MODE BLOCKED: P0 safety issues remain unresolved.\n"
                "  Use --live flag or set LIVE_MODE_ALLOWED=true to acknowledge risks.\n"
                "  See docs/review-2026-07-10.md for the list of unresolved P0 issues."
            )
            sys.exit(1)

        # Config conflict: can't have paper_trading enabled in live mode
        if config.paper_trading.enabled:
            logger.error(
                "CONFIG CONFLICT: testnet=false but paper_trading.enabled=true.\n"
                "  Paper trading must be disabled for live mode.\n"
                "  Set paper_trading.enabled: false in config.yaml"
            )
            sys.exit(1)

        logger.warning(
            "=" * 55 + "\n"
            " LIVE MODE — REAL MONEY TRADING\n"
            " P0 safety issues remain unresolved.\n"
            " See docs/review-2026-07-10.md\n"
            "=" * 55
        )
        time.sleep(5)

    # 3. Initialize broker
    paper_mode = args.paper or config.paper_trading.enabled
    exchange_name = config.exchange.default

    if paper_mode:
        from cryptoquant.execution.paper_broker import PaperBroker

        broker = PaperBroker(
            initial_balance=config.paper_trading.initial_balance,
            quote=config.trading.default_quote,
            slippage_bps=config.paper_trading.slippage_bps,
            latency_ms=config.paper_trading.latency_ms,
            commission_bps=config.paper_trading.commission_bps,
        )
        logger.info(
            f"PaperBroker initialized: balance={config.paper_trading.initial_balance} "
            f"{config.trading.default_quote}, slippage={config.paper_trading.slippage_bps}bps, "
            f"commission={config.paper_trading.commission_bps}bps, "
            f"latency={config.paper_trading.latency_ms}ms"
        )
    else:
        okx_cfg = config.exchange.okx
        broker = Broker(
            exchange=exchange_name,
            api_key=config.okx_api_key,
            secret=config.okx_api_secret,
            password=config.okx_passphrase,
            testnet=okx_cfg.testnet,
            account_type=getattr(config.trading, "account_type", "spot"),
        )

        if not okx_cfg.testnet:
            logger.warning(
                "=" * 50 + "\n"
                " LIVE BROKER INITIALIZED — REAL MONEY\n"
                " P0 safety issues remain unresolved.\n" +
                "=" * 50
            )
            # Allow 5 seconds for user to abort
            time.sleep(5)

    # 4. Initialize data pipeline
    db_path = config.data.db_path
    store = OHLCVStore(db_path)
    fetch_cfg = config.data.fetch
    okx_cfg = config.exchange.okx

    # --timeframe from CLI or fall back to config default
    timeframe = args.timeframe or getattr(config.trading, "default_timeframe", "1h")
    fetcher = OHLCVFetcher(
        exchange=exchange_name,
        testnet=okx_cfg.testnet,
        timeout=fetch_cfg.timeout_ms,
        max_candles=fetch_cfg.max_candles_per_request,
    )
    data_feed = LiveDataFeed(
        fetcher=fetcher,
        store=store,
        exchange=exchange_name,
        symbol=args.symbol,
        timeframe=timeframe,
        strict_validation=True,
        quality_check=True,
        fail_on_quality=False,
    )
    logger.info(f"Data feed: {args.symbol} {timeframe}")

    # 5. Initialize risk manager
    risk_cfg = config.risk
    risk = RiskManager(
        max_positions=risk_cfg.max_positions,
        max_daily_trades=risk_cfg.max_daily_trades,
        max_daily_loss_pct=risk_cfg.max_daily_loss_pct,
        max_daily_loss_abs=risk_cfg.max_daily_loss_abs,
        max_per_trade_risk_pct=risk_cfg.max_per_trade_risk_pct,
        max_drawdown_pct=risk_cfg.max_drawdown_pct,
        min_balance=risk_cfg.min_balance,
        emergency_cooldown_minutes=risk_cfg.emergency_cooldown_minutes,
        drawdown_tier1_pct=risk_cfg.drawdown_tier1_pct,
        drawdown_tier2_pct=risk_cfg.drawdown_tier2_pct,
        drawdown_tier3_pct=risk_cfg.drawdown_tier3_pct,
        tier_cooldown_minutes=risk_cfg.tier_cooldown_minutes,
        initial_balance=broker.get_balance("USDT"),
    )
    logger.info("Risk manager initialized")

    # 6. Initialize strategy
    strategy = resolve_strategy(getattr(args, "strategy", None), config)
    logger.info(f"Strategy: {strategy.name}")

    # 7. Initialize journal
    journal = TradeJournal(
        journal_dir=config.logging.dir,
        strategy_name=strategy.name,
    )

    # 7.5. Pre-fetch data so freshness check passes on first startup.
    #      Also seeds PaperBroker with a real market price.
    #      Lookback scales with timeframe: more bars needed for shorter timeframes.
    try:
        logger.info("Pre-fetching data for startup validation...")
        # Scale lookback: need enough bars to satisfy min_bars + warmup
        tf_map = {"1m": 3000, "3m": 2000, "5m": 1000, "15m": 500, "30m": 400, "1h": 200, "4h": 200}
        lookback = tf_map.get(timeframe, 500)
        df_initial = data_feed.fetch(lookback=lookback)
        if not df_initial.empty:
            last_price = float(df_initial["close"].iloc[-1])
            update_price = getattr(broker, "update_price", None)
            if callable(update_price):
                update_price(args.symbol, last_price)
            logger.info(
                f"Pre-fetch OK: {len(df_initial)} bars, "
                f"last close={last_price}"
            )
        else:
            logger.warning("Pre-fetch returned empty DataFrame")
    except Exception as e:
        logger.warning(f"Pre-fetch failed (will retry in tick loop): {e}")

    # 8. Startup health check
    if not health_check_startup(broker, data_feed, risk):
        if paper_mode:
            logger.warning(
                "Health check failed in paper mode — continuing anyway. "
                "PaperBroker does not require exchange connectivity."
            )
        else:
            logger.error("Health check failed — aborting startup")
            sys.exit(1)

    if args.dry_run:
        logger.info("Dry-run complete — all components initialized successfully")
        sys.exit(0)

    # 9. Initialize and run engine
    trading_cfg = config.trading
    engine = LiveEngine(
        broker=broker,
        strategy=strategy,
        data_feed=data_feed,
        risk_manager=risk,
        state_dir=args.state_dir,
        symbol=args.symbol,
        min_order_usdt=trading_cfg.min_order_usdt,
        max_order_usdt=trading_cfg.max_order_usdt,
        cooldown_bars=trading_cfg.cooldown_bars,
        order_timeout=trading_cfg.order_timeout,
        stop_loss_pct=trading_cfg.stop_loss_pct,
        take_profit_pct=trading_cfg.take_profit_pct,
        max_hold_hours=trading_cfg.max_hold_hours,
        reconcile_on_start=not args.no_reconcile,
        journal=journal,
    )

    logger.info(
        f"Starting live engine: {strategy.name} on {args.symbol} "
        f"interval={args.interval}s"
    )
    engine.run(interval=args.interval)


if __name__ == "__main__":
    main()
