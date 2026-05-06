"""Fetch command handler for CLI.

Provides functionality to download historical OHLCV data from OKX exchange
and save it in Parquet format for backtesting.
"""

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

import structlog
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from data.manager import OKXClient
from data.models import OHLCVCandle
from data.storage import save_historical_data

logger = structlog.get_logger(__name__)
console = Console()


def run_fetch(args: argparse.Namespace) -> int:
    """Execute data fetch with given arguments."""
    logger.info(
        "starting_fetch_command",
        pair=args.pair,
        timeframe=args.timeframe,
        days=getattr(args, 'days', None),
        since=getattr(args, 'since', None),
    )

    console.print("[bold blue]Fetching Historical Data[/bold blue]")
    console.print(f"Pair: {args.pair}")
    console.print(f"Timeframe: {args.timeframe}")
    
    if hasattr(args, 'days') and args.days:
        console.print(f"Days: {args.days}")
    elif hasattr(args, 'since') and args.since:
        console.print(f"Since: {args.since}")
    else:
        console.print(f"Days: 365 (default)")
    
    console.print(f"Sandbox: {args.sandbox}")
    console.print()

    try:
        with console.status("[bold green]Connecting to OKX..."):
            client = OKXClient(sandbox=args.sandbox)
        
        console.print("[green]✓ Connected to OKX[/green]")
        console.print()

        since = _calculate_since_timestamp(args)
        
        if since is None:
            console.print("[red]Error: Could not calculate start date[/red]")
            return 1

        candles = _fetch_with_progress(client, args.pair, args.timeframe, since)

        if not candles:
            console.print("[yellow]No data returned from exchange[/yellow]")
            return 1

        valid_candles = _validate_candles(candles)
        
        console.print(f"[green]✓ Fetched {len(valid_candles)} candles[/green]")
        console.print()

        _display_data_summary(valid_candles)

        with console.status("[bold green]Saving to Parquet..."):
            save_historical_data(
                candles=valid_candles,
                pair=args.pair,
                timeframe=args.timeframe,
                data_source="OKX",
            )
        
        console.print("[green]✓ Data saved successfully[/green]")
        console.print()
        
        return 0

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
