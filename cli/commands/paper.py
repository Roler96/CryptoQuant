"""Paper trading command handler for CLI."""

import argparse
import signal
import sys
from decimal import Decimal

import structlog
from rich.console import Console
from rich.table import Table

from live.paper_trading import PaperTradingRunner, SimulatedTrade

logger = structlog.get_logger(__name__)
console = Console()


def run_paper(args: argparse.Namespace) -> int:
    """Execute paper trading with given arguments.

    Args:
        args: Parsed command-line arguments containing:
            - strategy: Strategy name
            - pair: Trading pair
            - timeframe: Candle timeframe
            - duration: Duration in hours to run

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    logger.info(
        "starting_paper_trading_command",
        strategy=args.strategy,
        pair=args.pair,
        timeframe=args.timeframe,
        duration=args.duration,
    )

    console.print("[bold blue]Starting Paper Trading[/bold blue]")
    console.print(f"Strategy: {args.strategy}")
    console.print(f"Pair: {args.pair}")
    console.print(f"Timeframe: {args.timeframe}")
    console.print(f"Duration: {args.duration} hours")
    console.print()

    initial_balance = Decimal("10000")
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

    try:
        runner = PaperTradingRunner(
            strategy_name=args.strategy,
            pair=args.pair,
            timeframe=args.timeframe,
            initial_balance=initial_balance,
            sandbox=True,
        )
    except Exception as e:
        logger.error("failed_to_initialize_paper_trader", error=str(e))
        console.print(f"[red]Error initializing paper trader: {e}[/red]")
        return 1

    def signal_handler(sig, frame):
        console.print("\n[yellow]Stopping paper trading...[/yellow]")
        runner.stop()
        _display_final_results(runner)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    console.print("[green]Paper trading started. Press Ctrl+C to stop.[/green]")
    console.print()

    try:
        iterations = args.duration * 3600 // interval_seconds if args.duration > 0 else None

        iteration_count = 0
        while runner.running:
            if iterations and iteration_count >= iterations:
                console.print(f"\n[green]Completed {args.duration} hours of paper trading[/green]")
                break

            trade = runner.run_iteration()
            iteration_count += 1

            if trade:
                _display_trade(trade)

            if iteration_count % 10 == 0:
                _display_status(runner, iteration_count)

            import time
            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        console.print("\n[yellow]Trading loop interrupted[/yellow]")
    finally:
        runner.stop()

    _display_final_results(runner)

    return 0


def _display_trade(trade: SimulatedTrade) -> None:
    """Display executed trade information.

    Args:
        trade: SimulatedTrade to display
    """
    console.print("\n[cyan]Trade Executed:[/cyan]")
    console.print(f"  Action: {trade.action}")
    console.print(f"  Side: {trade.side}")
    console.print(f"  Price: ${float(trade.price):.2f}")
    console.print(f"  Quantity: {float(trade.quantity):.6f}")
    console.print(f"  Value: ${float(trade.value):.2f}")
    console.print(f"  Balance: ${float(trade.balance_after):.2f}")


def _display_status(runner: PaperTradingRunner, iteration: int) -> None:
    """Display current trading status.

    Args:
        runner: PaperTradingRunner instance
        iteration: Current iteration number
    """
    table = Table(title=f"Paper Trading Status (Iteration {iteration})", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    table.add_row("Balance", f"${float(runner.balance):.2f}")
    table.add_row("Total Trades", str(len(runner.trades)))

    if runner.pair in runner.positions:
        pos = runner.positions[runner.pair]
        table.add_row("Position Side", pos.side)
        table.add_row("Position Size", f"{float(pos.size):.6f}")
        table.add_row("Entry Price", f"${float(pos.entry_price):.2f}")
        table.add_row("Unrealized P&L", f"${float(pos.unrealized_pnl):.2f}")
    else:
        table.add_row("Position", "None")

    console.print(table)


def _display_final_results(runner: PaperTradingRunner) -> None:
    """Display final paper trading results.

    Args:
        runner: PaperTradingRunner instance
    """
    console.print("\n[bold blue]Paper Trading Results[/bold blue]")

    table = Table(title="Final Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    initial = runner.initial_balance
    final = runner.balance
    pnl = final - initial
    pnl_pct = (pnl / initial) * 100 if initial > 0 else Decimal("0")

    table.add_row("Initial Balance", f"${float(initial):.2f}")
    table.add_row("Final Balance", f"${float(final):.2f}")
    table.add_row("Total P&L", f"${float(pnl):.2f}")
    table.add_row("P&L %", f"{float(pnl_pct):.2f}%")
    table.add_row("Total Trades", str(len(runner.trades)))

    if runner.trades:
        winning = sum(1 for t in runner.trades if t.balance_after > t.balance_before)
        win_rate = (winning / len(runner.trades)) * 100
        table.add_row("Win Rate", f"{win_rate:.1f}%")

    console.print(table)
    console.print()