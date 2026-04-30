"""Backtest command handler for CLI.

Provides functionality to run historical backtests with performance metrics
display, validation against thresholds, and equity curve visualization.
"""

import argparse
import sys
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog
from rich.console import Console
from rich.table import Table

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.metrics import (
    SHARPE_THRESHOLD,
    MAX_DRAWDOWN_THRESHOLD,
    WIN_RATE_THRESHOLD,
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_average_trade,
)
from data.storage import load_historical_data

logger = structlog.get_logger(__name__)
console = Console()


def run_backtest(args: argparse.Namespace) -> int:
    """Execute backtest with given arguments and display results.

    Args:
        args: Parsed command-line arguments containing:
            - strategy: Strategy name
            - pair: Trading pair
            - timeframe: Candle timeframe
            - days: Number of days to backtest
            - initial_cash: Starting capital
            - commission: Commission rate
            - no_plot: Skip equity curve plot

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    logger.info(
        "starting_backtest_command",
        strategy=args.strategy,
        pair=args.pair,
        timeframe=args.timeframe,
        days=args.days,
        initial_cash=args.initial_cash,
    )

    console.print(f"[bold blue]Running Backtest[/bold blue]")
    console.print(f"Strategy: {args.strategy}")
    console.print(f"Pair: {args.pair}")
    console.print(f"Timeframe: {args.timeframe}")
    console.print(f"Days: {args.days}")
    console.print(f"Initial Cash: ${args.initial_cash:,.2f}")
    console.print()

    try:
        # Check if data exists
        try:
            df = load_historical_data(args.pair, args.timeframe)
            logger.info("historical_data_loaded", rows=len(df))
        except FileNotFoundError:
            console.print(f"[red]Error: No historical data found for {args.pair} {args.timeframe}[/red]")
            console.print(f"[yellow]Please fetch data first using the data collection module.[/yellow]")
            return 1

        # Configure backtest
        config = BacktestConfig(
            initial_cash=args.initial_cash,
            commission=args.commission,
            plot_results=not args.no_plot,
        )

        # Initialize engine and load strategy
        engine = BacktestEngine(config=config)
        strategy = engine.load_strategy(args.strategy)

        # Run backtest
        with console.status("[bold green]Running backtest..."):
            result = engine.run_backtest(
                strategy=strategy,
                pair=args.pair,
                timeframe=args.timeframe,
                days=args.days,
            )

        # Handle errors
        if result.error:
            console.print(f"[red]Backtest failed: {result.error}[/red]")
            return 1

        # Calculate additional metrics
        equity_curve_decimal = [Decimal(str(v)) for v in result.equity_curve]
        sharpe = calculate_sharpe_ratio(equity_curve_decimal)
        max_dd = calculate_max_drawdown(equity_curve_decimal)
        win_rate = calculate_win_rate(result.trades)
        profit_factor = calculate_profit_factor(result.trades)
        avg_trade = calculate_average_trade(result.trades)

        # Display results
        _display_performance_table(
            result=result,
            sharpe=sharpe,
            max_dd=max_dd,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_trade=avg_trade,
        )

        _display_trades_summary(result.trades)

        # Validate against thresholds
        validation_passed = _validate_metrics(
            sharpe=sharpe,
            max_dd=max_dd,
            win_rate=win_rate,
        )

        if result.plot_path:
            console.print(f"[green]Equity curve saved to: {result.plot_path}[/green]")

        if validation_passed:
            console.print("[bold green]✓ All metrics passed validation thresholds[/bold green]")
            return 0
        else:
            console.print("[bold yellow]⚠ Some metrics failed validation thresholds[/bold yellow]")
            return 0  # Return success even if thresholds not met

    except Exception as e:
        logger.error("backtest_command_failed", error=str(e))
        console.print(f"[red]Error: {e}[/red]")
        return 1


def _display_performance_table(
    result: Any,
    sharpe: Optional[Decimal],
    max_dd: Optional[Decimal],
    win_rate: Optional[Decimal],
    profit_factor: Optional[Decimal],
    avg_trade: Decimal,
) -> None:
    """Display performance metrics in a formatted table.

    Args:
        result: BacktestResult object
        sharpe: Calculated Sharpe ratio
        max_dd: Calculated maximum drawdown
        win_rate: Calculated win rate
        profit_factor: Calculated profit factor
        avg_trade: Calculated average trade P&L
    """
    table = Table(title="Performance Metrics", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")
    table.add_column("Threshold", justify="right", style="yellow")
    table.add_column("Status", justify="center")

    # Sharpe Ratio
    if sharpe is not None:
        sharpe_status = "[green]✓[/green]" if sharpe >= SHARPE_THRESHOLD else "[red]✗[/red]"
        table.add_row(
            "Sharpe Ratio",
            f"{float(sharpe):.3f}",
            f"≥ {float(SHARPE_THRESHOLD):.1f}",
            sharpe_status,
        )
    else:
        table.add_row("Sharpe Ratio", "N/A", f"≥ {float(SHARPE_THRESHOLD):.1f}", "[yellow]-[/yellow]")

    # Max Drawdown
    if max_dd is not None:
        max_dd_pct = float(max_dd) * 100
        max_dd_status = "[green]✓[/green]" if max_dd <= MAX_DRAWDOWN_THRESHOLD else "[red]✗[/red]"
        table.add_row(
            "Max Drawdown",
            f"{max_dd_pct:.2f}%",
            f"< {float(MAX_DRAWDOWN_THRESHOLD) * 100:.0f}%",
            max_dd_status,
        )
    else:
        table.add_row(
            "Max Drawdown",
            "N/A",
            f"< {float(MAX_DRAWDOWN_THRESHOLD) * 100:.0f}%",
            "[yellow]-[/yellow]",
        )

    # Win Rate
    if win_rate is not None:
        win_rate_pct = float(win_rate) * 100
        win_rate_status = "[green]✓[/green]" if win_rate >= WIN_RATE_THRESHOLD else "[red]✗[/red]"
        table.add_row(
            "Win Rate",
            f"{win_rate_pct:.2f}%",
            f"≥ {float(WIN_RATE_THRESHOLD) * 100:.0f}%",
            win_rate_status,
        )
    else:
        table.add_row(
            "Win Rate",
            "N/A",
            f"≥ {float(WIN_RATE_THRESHOLD) * 100:.0f}%",
            "[yellow]-[/yellow]",
        )

    # Profit Factor
    if profit_factor is not None:
        table.add_row(
            "Profit Factor",
            f"{float(profit_factor):.3f}",
            "> 1.0",
            "[green]✓[/green]" if profit_factor > 1 else "[red]✗[/red]",
        )
    else:
        table.add_row("Profit Factor", "∞ (no losses)", "> 1.0", "[green]✓[/green]")

    # Total Return
    total_return_pct = result.total_return * 100
    table.add_row(
        "Total Return",
        f"{total_return_pct:.2f}%",
        "-",
        "[green]✓[/green]" if total_return_pct > 0 else "[red]✗[/red]",
    )

    # Average Trade
    avg_trade_pct = float(avg_trade) * 100
    table.add_row(
        "Avg Trade P&L",
        f"{avg_trade_pct:.3f}%",
        "-",
        "[green]✓[/green]" if avg_trade > 0 else "[red]✗[/red]",
    )

    # Trade Count
    table.add_row("Total Trades", str(len(result.trades)), "-", "-")

    # Final Value
    table.add_row(
        "Final Value",
        f"${result.final_value:,.2f}",
        "-",
        "[green]✓[/green]" if result.final_value > result.initial_value else "[red]✗[/red]",
    )

    console.print(table)
    console.print()


def _display_trades_summary(trades: List[Dict[str, Any]]) -> None:
    """Display summary of trades.

    Args:
        trades: List of trade dictionaries
    """
    if not trades:
        console.print("[yellow]No trades executed during backtest[/yellow]")
        return

    console.print(f"[bold]Trades Summary:[/bold] {len(trades)} total trades")

    winning_trades = [t for t in trades if t.get("pnl", 0) > 0]
    losing_trades = [t for t in trades if t.get("pnl", 0) < 0]

    if winning_trades:
        avg_win = sum(t["pnl"] for t in winning_trades) / len(winning_trades) * 100
        console.print(f"  Winning trades: {len(winning_trades)} (avg: +{avg_win:.2f}%)")

    if losing_trades:
        avg_loss = sum(t["pnl"] for t in losing_trades) / len(losing_trades) * 100
        console.print(f"  Losing trades: {len(losing_trades)} (avg: {avg_loss:.2f}%)")

    # Best and worst trades
    best_trade = max(trades, key=lambda t: t.get("pnl", 0))
    worst_trade = min(trades, key=lambda t: t.get("pnl", 0))

    console.print(f"  Best trade: +{best_trade['pnl'] * 100:.2f}%")
    console.print(f"  Worst trade: {worst_trade['pnl'] * 100:.2f}%")
    console.print()


def _validate_metrics(
    sharpe: Optional[Decimal],
    max_dd: Optional[Decimal],
    win_rate: Optional[Decimal],
) -> bool:
    """Validate metrics against thresholds.

    Args:
        sharpe: Calculated Sharpe ratio
        max_dd: Calculated maximum drawdown
        win_rate: Calculated win rate

    Returns:
        True if all metrics pass thresholds, False otherwise
    """
    results = []

    if sharpe is not None:
        results.append(sharpe >= SHARPE_THRESHOLD)
    else:
        results.append(False)

    if max_dd is not None:
        results.append(max_dd <= MAX_DRAWDOWN_THRESHOLD)
    else:
        results.append(False)

    if win_rate is not None:
        results.append(win_rate >= WIN_RATE_THRESHOLD)
    else:
        results.append(False)

    return all(results)
