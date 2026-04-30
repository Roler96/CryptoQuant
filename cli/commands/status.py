"""Status command handler for CLI.

Displays current system state including active strategies, positions,
balance summary, and system health information.
"""

import argparse
from datetime import datetime
from pathlib import Path

import structlog
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from data.storage import list_available_data

logger = structlog.get_logger(__name__)
console = Console()


def run_status(args: argparse.Namespace) -> int:
    """Display current system state.

    Args:
        args: Parsed command-line arguments containing:
            - verbose: Show detailed status information

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    logger.info("displaying_system_status", verbose=args.verbose)

    console.print("[bold blue]CryptoQuant System Status[/bold blue]")
    console.print()

    try:
        # Display configuration status
        _display_config_status()

        # Display data availability
        _display_data_status()

        # Display trading status (placeholder for now)
        _display_trading_status(args.verbose)

        if args.verbose:
            # Display system information
            _display_system_info()

        return 0

    except Exception as e:
        logger.error("status_command_failed", error=str(e))
        console.print(f"[red]Error: {e}[/red]")
        return 1


def _display_config_status() -> None:
    """Display configuration status."""
    config_path = Path("config/config.yaml")

    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)

            console.print(Panel("[bold cyan]Configuration[/bold cyan]", expand=False))

            table = Table(show_header=False, box=None)
            table.add_column("Setting", style="cyan")
            table.add_column("Value", style="green")

            # Exchange settings
            exchange = config.get("exchange", {})
            table.add_row("Exchange", exchange.get("name", "unknown"))
            table.add_row("Sandbox Mode", "Enabled" if exchange.get("sandbox", True) else "Disabled")

            # Trading settings
            trading = config.get("trading", {})
            symbols = trading.get("symbols", [])
            table.add_row("Default Symbols", ", ".join(symbols) if symbols else "None")
            table.add_row("Default Timeframe", trading.get("timeframe", "unknown"))

            # Risk settings
            risk = config.get("risk", {})
            table.add_row("Max Daily Loss", f"{risk.get('max_daily_loss', 0) * 100:.1f}%")
            table.add_row("Max Drawdown", f"{risk.get('max_drawdown', 0) * 100:.1f}%")
            table.add_row("Stop Loss", f"{risk.get('stop_loss_pct', 0) * 100:.1f}%")
            table.add_row("Take Profit", f"{risk.get('take_profit_pct', 0) * 100:.1f}%")

            # Live trading status
            live = config.get("live", {})
            table.add_row("Live Trading", "Enabled" if live.get("enabled", False) else "Disabled")
            table.add_row("Dry Run", "Yes" if live.get("dry_run", True) else "No")

            console.print(table)
            console.print()

        except Exception as e:
            console.print(f"[yellow]Warning: Could not read config: {e}[/yellow]")
    else:
        console.print("[yellow]Configuration file not found[/yellow]")


def _display_data_status() -> None:
    """Display data availability status."""
    console.print(Panel("[bold cyan]Data Availability[/bold cyan]", expand=False))

    try:
        available_data = list_available_data()

        if available_data:
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Pair", style="cyan")
            table.add_column("Timeframe", style="cyan")
            table.add_column("Rows", justify="right", style="green")
            table.add_column("Last Update", style="yellow")
            table.add_column("Source", style="blue")

            for data_info in available_data:
                table.add_row(
                    data_info.get("pair", "unknown"),
                    data_info.get("timeframe", "unknown"),
                    str(data_info.get("rows_count", 0)),
                    data_info.get("last_update_timestamp", "unknown")[:19],
                    data_info.get("data_source", "unknown"),
                )

            console.print(table)
        else:
            console.print("[yellow]No historical data available[/yellow]")
            console.print("[dim]Use data collection module to fetch historical data[/dim]")

        console.print()

    except Exception as e:
        console.print(f"[yellow]Warning: Could not retrieve data status: {e}[/yellow]")
        console.print()


def _display_trading_status(verbose: bool) -> None:
    """Display trading status (placeholder for actual implementation).

    Args:
        verbose: Show detailed information
    """
    console.print(Panel("[bold cyan]Trading Status[/bold cyan]", expand=False))

    table = Table(show_header=False, box=None)
    table.add_column("Item", style="cyan")
    table.add_column("Status", style="yellow")

    # These would come from actual trading engine in production
    table.add_row("Active Strategy", "[dim]Not running[/dim]")
    table.add_row("Current Position", "[dim]None[/dim]")
    table.add_row("Open P&L", "[dim]$0.00[/dim]")
    table.add_row("Account Balance", "[dim]$0.00[/dim]")

    console.print(table)
    console.print()

    if verbose:
        console.print("[dim]Note: Trading status requires live trading module to be active[/dim]")
        console.print()


def _display_system_info() -> None:
    """Display system information."""
    console.print(Panel("[bold cyan]System Information[/bold cyan]", expand=False))

    table = Table(show_header=False, box=None)
    table.add_column("Item", style="cyan")
    table.add_column("Value", style="green")

    # Environment
    table.add_row("Working Directory", str(Path.cwd()))
    table.add_row("Config Path", "config/config.yaml")
    table.add_row("Data Path", "data/historical")
    table.add_row("Logs Path", "logs")

    # Check for .env file
    env_path = Path(".env")
    table.add_row("Environment File", "Found" if env_path.exists() else "Not found")

    # Python version info could be added here
    table.add_row("Timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    console.print(table)
    console.print()
