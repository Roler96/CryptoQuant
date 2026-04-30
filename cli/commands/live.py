"""Live trading command handler for CLI."""

import argparse
import signal
import sys
from decimal import Decimal

import structlog
from rich.console import Console
from rich.table import Table

from live.trading import LiveTradingRunner, LiveTrade

logger = structlog.get_logger(__name__)
console = Console()


def run_live(args: argparse.Namespace) -> int:
    """Execute live trading with given arguments.

    Args:
        args: Parsed command-line arguments containing:
            - strategy: Strategy name
            - pair: Trading pair
            - timeframe: Candle timeframe
            - dry_run: Whether to simulate without real execution

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    logger.info(
        "starting_live_trading_command",
        strategy=args.strategy,
        pair=args.pair,
        timeframe=args.timeframe,
        dry_run=args.dry_run,
    )

    console.print("[bold blue]Starting Live Trading[/bold blue]")
    console.print(f"Strategy: {args.strategy}")
    console.print(f"Pair: {args.pair}")
    console.print(f"Timeframe: {args.timeframe}")
    console.print(f"Mode: {'DRY-RUN (simulated)' if args.dry_run else 'LIVE (real funds)'}")
    console.print()

    if not args.dry_run:
        console.print("[bold red]⚠️  WARNING: LIVE TRADING WITH REAL FUNDS[/bold red]")
        console.print()
        console.print("This will:")
        console.print("  • Execute real trades on OKX exchange")
        console.print("  • Use real funds from your account")
        console.print("  • Cannot be undone once executed")
        console.print()
        console.print("[yellow]Ensure you have:")
        console.print("  • Tested strategy thoroughly in backtest")
        console.print("  • Verified in paper trading mode")
        console.print("  • Set appropriate risk limits")
        console.print()

        try:
            confirmation = input("Type 'LIVE' to confirm you want to proceed: ").strip()
            if confirmation != "LIVE":
                console.print("[yellow]Live trading cancelled.[/yellow]")
                return 1
        except EOFError:
            console.print("[red]Cannot run live trading in non-interactive mode[/red]")
            return 1

        console.print()
        console.print("[green]Live trading confirmed. Proceeding...[/green]")
        console.print()

    interval_seconds = 60

    timeframe_intervals = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }
    interval_seconds = timeframe_intervals.get(args.timeframe, 60)

    max_drawdown_pct = Decimal("10")
    risk_per_trade_pct = Decimal("0.02")

    try:
        runner = LiveTradingRunner(
            strategy_name=args.strategy,
            pair=args.pair,
            timeframe=args.timeframe,
            sandbox=args.dry_run,
            require_confirmation=not args.dry_run,
            max_drawdown_pct=max_drawdown_pct,
            risk_per_trade_pct=risk_per_trade_pct,
        )
    except Exception as e:
        logger.error("failed_to_initialize_live_trader", error=str(e))
        console.print(f"[red]Error initializing live trader: {e}[/red]")
        return 1

    def signal_handler(sig, frame):
        console.print("\n[yellow]Stopping live trading...[/yellow]")
        runner.stop()
        _display_final_results(runner)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    console.print("[green]Live trading started. Press Ctrl+C to stop.[/green]")
    console.print()

    try:
        iteration_count = 0
        while runner.running:
            trade = runner.run_iteration()
            iteration_count += 1

            if trade:
                _display_trade(trade, args.dry_run)

            if runner.kill_switch.is_safe_mode():
                console.print("\n[bold red]🚨 KILL SWITCH ACTIVATED[/bold red]")
                console.print(f"Reason: {runner.kill_switch.reason}")
                console.print("All trading has been halted.")
                break

            if iteration_count % 10 == 0:
                _display_status(runner, iteration_count, args.dry_run)

            import time
            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        console.print("\n[yellow]Trading loop interrupted[/yellow]")
    finally:
        runner.stop()

    _display_final_results(runner)

    return 0


def _display_trade(trade: LiveTrade, dry_run: bool) -> None:
    """Display executed trade information.

    Args:
        trade: LiveTrade to display
        dry_run: Whether this is a dry-run trade
    """
    mode = "[yellow](DRY-RUN)[/yellow]" if dry_run else "[red](LIVE)[/red]"
    console.print(f"\n[cyan]Trade Executed {mode}[/cyan]")
    console.print(f"  Action: {trade.action}")
    console.print(f"  Side: {trade.side}")
    console.print(f"  Price: ${float(trade.price):.2f}")
    console.print(f"  Quantity: {float(trade.quantity):.6f}")
    console.print(f"  Value: ${float(trade.value):.2f}")
    console.print(f"  Order ID: {trade.order_id}")

    if trade.pnl != Decimal("0"):
        pnl_color = "green" if trade.pnl > 0 else "red"
        console.print(f"  P&L: [{pnl_color}]${float(trade.pnl):.2f}[/{pnl_color}]")


def _display_status(runner: LiveTradingRunner, iteration: int, dry_run: bool) -> None:
    """Display current trading status.

    Args:
        runner: LiveTradingRunner instance
        iteration: Current iteration number
        dry_run: Whether in dry-run mode
    """
    mode = "Dry-Run" if dry_run else "LIVE"
    table = Table(title=f"Live Trading Status ({mode}) - Iteration {iteration}", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    table.add_row("Mode", mode)
    table.add_row("Total Trades", str(len(runner.trades)))
    table.add_row("Kill Switch", "ACTIVE" if runner.kill_switch.is_safe_mode() else "Safe")

    if runner.pair in runner.positions:
        pos = runner.positions[runner.pair]
        table.add_row("Position Side", pos.side)
        table.add_row("Position Size", f"{float(pos.size):.6f}")
        table.add_row("Entry Price", f"${float(pos.entry_price):.2f}")
        table.add_row("Unrealized P&L", f"${float(pos.unrealized_pnl):.2f}")
        if pos.stop_loss:
            table.add_row("Stop Loss", f"${float(pos.stop_loss):.2f}")
    else:
        table.add_row("Position", "None")

    console.print(table)


def _display_final_results(runner: LiveTradingRunner) -> None:
    """Display final live trading results.

    Args:
        runner: LiveTradingRunner instance
    """
    console.print("\n[bold blue]Live Trading Results[/bold blue]")

    table = Table(title="Final Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    table.add_row("Total Trades", str(len(runner.trades)))
    table.add_row("Kill Switch Status", "Triggered" if runner.kill_switch.is_safe_mode() else "Not Triggered")

    if runner.trades:
        total_pnl = sum(float(t.pnl) for t in runner.trades)
        table.add_row("Total Realized P&L", f"${total_pnl:.2f}")

        winning_trades = [t for t in runner.trades if t.pnl > 0]
        losing_trades = [t for t in runner.trades if t.pnl < 0]

        if winning_trades:
            avg_win = sum(float(t.pnl) for t in winning_trades) / len(winning_trades)
            table.add_row("Winning Trades", f"{len(winning_trades)} (avg: +${avg_win:.2f})")

        if losing_trades:
            avg_loss = sum(float(t.pnl) for t in losing_trades) / len(losing_trades)
            table.add_row("Losing Trades", f"{len(losing_trades)} (avg: -${abs(avg_loss):.2f})")

        if runner.trades:
            win_rate = (len(winning_trades) / len(runner.trades)) * 100
            table.add_row("Win Rate", f"{win_rate:.1f}%")

    console.print(table)
    console.print()

    if runner.kill_switch.is_safe_mode():
        console.print("[bold yellow]⚠️  Trading was stopped by kill switch[/bold yellow]")
        console.print(f"Reason: {runner.kill_switch.reason}")
        console.print("Please review your strategy and risk parameters before resuming.")