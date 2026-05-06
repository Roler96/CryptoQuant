"""Fetch command handler for CLI.

Provides functionality to download historical OHLCV data from OKX exchange
and save it in database or Parquet format for backtesting.
"""

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

import structlog
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from data.loader import (
    IncrementalUpdater,
    get_data_stats,
    get_latest_timestamp,
    save_candles,
    use_database,
)
from data.manager import OKXClient
from data.models import OHLCVCandle

logger = structlog.get_logger(__name__)
console = Console()

VALID_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"]
DEFAULT_TIMEFRAMES = ["15m", "1h", "4h", "1d"]


def run_fetch(args: argparse.Namespace) -> int:
    """Execute data fetch with given arguments."""
    logger.info(
        "starting_fetch_command",
        pair=args.pair,
        timeframe=getattr(args, 'timeframe', None),
        timeframes=getattr(args, 'timeframes', None),
        days=getattr(args, 'days', None),
        since=getattr(args, 'since', None),
        incremental=getattr(args, 'incremental', True),
    )

    console.print("[bold blue]Fetching Historical Data[/bold blue]")
    console.print(f"Pair: {args.pair}")
    
    storage_mode = "database" if use_database() else "file"
    console.print(f"Storage: {storage_mode}")
    
    if hasattr(args, 'incremental') and args.incremental:
        console.print("Mode: incremental")
    
    if hasattr(args, 'days') and args.days:
        console.print(f"Days: {args.days}")
    elif hasattr(args, 'since') and args.since:
        console.print(f"Since: {args.since}")
    else:
        console.print(f"Days: 365 (default)")
    
    console.print(f"Sandbox: {args.sandbox}")
    console.print()

    timeframes = _get_timeframes_to_fetch(args)
    
    if not timeframes:
        console.print("[red]Error: No valid timeframes specified[/red]")
        return 1

    try:
        with console.status("[bold green]Connecting to OKX..."):
            client = OKXClient(sandbox=args.sandbox)
        
        console.print("[green]✓ Connected to OKX[/green]")
        console.print()

        updater = IncrementalUpdater()
        
        results = []
        all_success = True
        
        for timeframe in timeframes:
            console.print(Panel(f"[bold blue]Fetching {timeframe} data[/bold blue]", expand=False))
            
            # Check for incremental update
            if getattr(args, 'incremental', True):
                existing_stats = get_data_stats(args.pair, timeframe)
                if existing_stats["count"] > 0:
                    console.print(f"[dim]Existing data: {existing_stats['count']} candles[/dim]")
                    console.print(f"[dim]Latest: {datetime.fromtimestamp(existing_stats['max_timestamp']/1000, tz=timezone.utc)}[/dim]")
                    
                    start_ts, _ = updater.get_fetch_range(args.pair, timeframe)
                    console.print(f"[dim]Fetching from: {datetime.fromtimestamp(start_ts/1000, tz=timezone.utc)}[/dim]")
                else:
                    start_ts = _calculate_since_timestamp(args)
                    if start_ts is None:
                        return 1
            else:
                start_ts = _calculate_since_timestamp(args)
                if start_ts is None:
                    return 1
            
            try:
                candles = _fetch_with_progress(client, args.pair, timeframe, start_ts)

                if not candles:
                    console.print(f"[yellow]No new data for {timeframe}[/yellow]")
                    results.append((timeframe, 0, "no new data"))
                    continue

                valid_candles = _validate_candles(candles)
                
                console.print(f"[green]✓ Fetched {len(valid_candles)} candles[/green]")

                with console.status("[bold green]Saving..."):
                    count = save_candles(
                        candles=valid_candles,
                        pair=args.pair,
                        timeframe=timeframe,
                    )
                
                console.print(f"[green]✓ Saved {count} candles[/green]")
                results.append((timeframe, count, "success"))
                
            except Exception as e:
                logger.error("fetch_timeframe_failed", timeframe=timeframe, error=str(e))
                console.print(f"[red]✗ Failed to fetch {timeframe}: {e}[/red]")
                results.append((timeframe, 0, f"error: {e}"))
                all_success = False
            
            console.print()
        
        # Display summary
        _display_fetch_summary(results)
        
        return 0 if all_success else 1

    except Exception as e:
        logger.error("fetch_command_failed", error=str(e))
        console.print(f"[red]Error: {e}[/red]")
        return 1
    finally:
        try:
            if 'client' in dir():
                client.close()
        except:
            pass


def _get_timeframes_to_fetch(args: argparse.Namespace) -> List[str]:
    """Determine which timeframes to fetch based on args.
    
    Returns:
        List of timeframe strings
    """
    # Check for explicit --timeframe (single)
    if hasattr(args, 'timeframe') and args.timeframe:
        if args.timeframe in VALID_TIMEFRAMES:
            return [args.timeframe]
        else:
            console.print(f"[red]Error: Invalid timeframe '{args.timeframe}'[/red]")
            console.print(f"Valid timeframes: {', '.join(VALID_TIMEFRAMES)}")
            return []
    
    # Check for --timeframes (multiple)
    if hasattr(args, 'timeframes') and args.timeframes:
        requested = [tf.strip() for tf in args.timeframes.split(',')]
        valid = [tf for tf in requested if tf in VALID_TIMEFRAMES]
        invalid = [tf for tf in requested if tf not in VALID_TIMEFRAMES]
        
        if invalid:
            console.print(f"[yellow]Warning: Ignoring invalid timeframes: {', '.join(invalid)}[/yellow]")
        
        return valid if valid else DEFAULT_TIMEFRAMES
    
    # Default: fetch all common timeframes
    return DEFAULT_TIMEFRAMES


def _display_fetch_summary(results: List[tuple]) -> None:
    """Display summary of fetch results for all timeframes."""
    console.print(Panel("[bold blue]Fetch Summary[/bold blue]", expand=False))
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Timeframe", style="cyan")
    table.add_column("Candles", justify="right", style="green")
    table.add_column("Status", style="yellow")
    
    total_candles = 0
    for timeframe, count, status in results:
        status_icon = "✓" if status == "success" else "✗"
        status_color = "green" if status == "success" else "red" if "error" in status else "yellow"
        table.add_row(
            timeframe,
            str(count),
            f"[{status_color}]{status_icon} {status}[/{status_color}]"
        )
        total_candles += count
    
    console.print(table)
    console.print(f"\n[bold]Total candles fetched: {total_candles}[/bold]")
    console.print()


def _calculate_since_timestamp(args: argparse.Namespace) -> Optional[int]:
    """Calculate the since timestamp from args."""
    if hasattr(args, 'since') and args.since:
        try:
            date = datetime.strptime(args.since, "%Y-%m-%d")
            dt = date.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            console.print("[red]Error: Invalid date format. Use YYYY-MM-DD[/red]")
            return None
    
    days = getattr(args, 'days', 365)
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    return int(since_dt.timestamp() * 1000)


def _fetch_with_progress(
    client: OKXClient,
    pair: str,
    timeframe: str,
    since: int,
) -> List[OHLCVCandle]:
    """Fetch candles with progress display."""
    candles: List[OHLCVCandle] = []
    limit = 100
    current_since = since
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[green]Fetching data...", total=None)
        
        while True:
            try:
                batch = client.fetch_ohlcv(
                    symbol=pair,
                    timeframe=timeframe,
                    since=current_since,
                    limit=limit,
                )
                
                if not batch:
                    break
                
                candles.extend(batch)
                progress.update(task, description=f"[green]Fetched {len(candles)} candles...")
                
                if len(batch) < limit:
                    break
                
                current_since = batch[-1].timestamp + 1
                
                if len(candles) >= 10000:
                    console.print("[yellow]Warning: Reached maximum fetch limit (10000 candles)[/yellow]")
                    break
                    
            except Exception as e:
                logger.error("fetch_batch_failed", error=str(e), since=current_since)
                console.print(f"[yellow]Warning: Failed to fetch batch: {e}[/yellow]")
                break
    
    return candles


def _validate_candles(candles: List[OHLCVCandle]) -> List[OHLCVCandle]:
    """Validate and filter candles."""
    valid = []
    
    for candle in candles:
        if candle.open_price <= 0 or candle.close_price <= 0:
            logger.warning("invalid_price_candle", timestamp=candle.timestamp)
            continue
        
        if candle.high_price < candle.low_price:
            logger.warning("invalid_hl_candle", timestamp=candle.timestamp)
            continue
        
        if candle.volume < 0:
            logger.warning("negative_volume_candle", timestamp=candle.timestamp)
            continue
        
        valid.append(candle)
    
    if len(valid) < len(candles):
        console.print(f"[yellow]Filtered {len(candles) - len(valid)} invalid candles[/yellow]")
    
    return valid


def _display_data_summary(candles: List[OHLCVCandle]) -> None:
    """Display summary of fetched data."""
    if not candles:
        return
    
    table = Table(title="Data Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")
    
    first_time = datetime.fromtimestamp(candles[0].timestamp / 1000, tz=timezone.utc)
    last_time = datetime.fromtimestamp(candles[-1].timestamp / 1000, tz=timezone.utc)
    
    table.add_row("Total Candles", str(len(candles)))
    table.add_row("First Candle", first_time.strftime("%Y-%m-%d %H:%M:%S UTC"))
    table.add_row("Last Candle", last_time.strftime("%Y-%m-%d %H:%M:%S UTC"))
    table.add_row("Duration", str(last_time - first_time))
    
    prices = [c.close_price for c in candles]
    table.add_row("Min Price", f"{min(prices):,.2f}")
    table.add_row("Max Price", f"{max(prices):,.2f}")
    
    total_volume = sum(c.volume for c in candles)
    table.add_row("Total Volume", f"{total_volume:,.2f}")
    table.add_row("Avg Volume", f"{total_volume / len(candles):,.2f}")
    
    console.print(table)
    console.print()
