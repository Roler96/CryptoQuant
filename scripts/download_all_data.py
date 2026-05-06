"""Download all historical data for all trading pairs and timeframes."""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.loader import get_data_stats, get_latest_timestamp, save_candles, use_database
from data.manager import OKXClient
from data.models import OHLCVCandle

console = Console()

TIMEFRAMES = {
    "1m": 7, "5m": 30, "15m": 90, "30m": 180,
    "1h": 365, "2h": 730, "4h": 1460, "6h": 2190,
    "8h": 2920, "12h": 3650, "1d": 3650, "3d": 3650,
    "1w": 3650, "1M": 3650,
}

DEFAULT_PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "DOGE/USDT", "TON/USDT", "ADA/USDT", "AVAX/USDT", "SHIB/USDT",
]


def fetch_candles_batch(
    client: OKXClient,
    pair: str,
    timeframe: str,
    since: int,
    limit: int = 100,
) -> list[OHLCVCandle]:
    try:
        return client.fetch_ohlcv(
            symbol=pair,
            timeframe=timeframe,
            since=since,
            limit=limit,
        )
    except Exception as e:
        console.print(f"[red]Error fetching {pair} {timeframe}: {e}[/red]")
        return []


def download_pair_timeframe(
    client: OKXClient,
    pair: str,
    timeframe: str,
    max_days: int,
    progress: Progress,
    task_id: int,
) -> dict:
    console.print(f"[cyan]Downloading {pair} {timeframe}...[/cyan]")
    
    existing_stats = get_data_stats(pair, timeframe)
    existing_count = existing_stats["count"]
    
    if existing_count > 0:
        last_ts = existing_stats["max_timestamp"]
        last_dt = datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc)
        since = last_ts + 1
        console.print(f"  [dim]Resuming from {last_dt} ({existing_count} existing)[/dim]")
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(days=max_days)
        since = int(since_dt.timestamp() * 1000)
    
    total_candles = 0
    new_candles = []
    batch_num = 0
    max_batches = 1000
    
    while batch_num < max_batches:
        candles = fetch_candles_batch(client, pair, timeframe, since)
        
        if not candles:
            break
        
        valid = []
        for c in candles:
            if (c.open_price > 0 and c.close_price > 0 and 
                c.high_price >= c.low_price and c.volume >= 0):
                valid.append(c)
        
        if not valid:
            break
        
        new_candles.extend(valid)
        total_candles += len(valid)
        progress.update(task_id, advance=len(valid))
        since = candles[-1].timestamp + 1
        batch_num += 1
        time.sleep(0.1)
        
        if len(candles) < 100:
            break
    
    if new_candles:
        count = save_candles(new_candles, pair, timeframe)
        console.print(f"  [green]✓ Saved {count} new candles[/green]")
    
    return {
        "pair": pair,
        "timeframe": timeframe,
        "downloaded": len(new_candles),
        "total": existing_count + len(new_candles),
    }


def download_all_data(
    pairs: Optional[list[str]] = None,
    timeframes: Optional[list[str]] = None,
    sandbox: bool = True,
) -> list[dict]:
    pairs = pairs or DEFAULT_PAIRS
    timeframes = timeframes or list(TIMEFRAMES.keys())
    
    console.print(Panel("[bold blue]Downloading All Historical Data[/bold blue]", expand=False))
    console.print(f"Pairs: {len(pairs)}")
    console.print(f"Timeframes: {', '.join(timeframes)}")
    console.print(f"Storage: {'database' if use_database() else 'file'}")
    console.print(f"Sandbox: {sandbox}")
    console.print()
    
    with console.status("[bold green]Connecting to OKX..."):
        client = OKXClient(sandbox=sandbox)
    console.print("[green]✓ Connected[/green]")
    console.print()
    
    results = []
    total_tasks = len(pairs) * len(timeframes)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        overall_task = progress.add_task("[cyan]Overall Progress", total=total_tasks)
        
        for pair in pairs:
            for timeframe in timeframes:
                max_days = TIMEFRAMES.get(timeframe, 365)
                task_desc = f"{pair} {timeframe}"
                task_id = progress.add_task(task_desc, total=None)
                
                try:
                    result = download_pair_timeframe(
                        client, pair, timeframe, max_days, progress, task_id
                    )
                    results.append(result)
                except Exception as e:
                    console.print(f"[red]Failed {pair} {timeframe}: {e}[/red]")
                    results.append({
                        "pair": pair,
                        "timeframe": timeframe,
                        "downloaded": 0,
                        "error": str(e),
                    })
                
                progress.update(overall_task, advance=1)
                progress.remove_task(task_id)
    
    return results


def display_summary(results: list[dict]) -> None:
    console.print()
    console.print(Panel("[bold blue]Download Summary[/bold blue]", expand=False))
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Pair", style="cyan")
    table.add_column("Timeframe", style="cyan")
    table.add_column("Downloaded", justify="right", style="green")
    table.add_column("Total", justify="right", style="blue")
    table.add_column("Status", style="yellow")
    
    total_downloaded = 0
    total_candles = 0
    
    for r in results:
        downloaded = r.get("downloaded", 0)
        total = r.get("total", downloaded)
        error = r.get("error")
        status = "[red]✗ Error" if error else "[green]✓ OK"
        
        table.add_row(r["pair"], r["timeframe"], str(downloaded), str(total), status)
        total_downloaded += downloaded
        total_candles += total
    
    console.print(table)
    console.print()
    console.print(f"[bold]Total Downloaded:[/bold] {total_downloaded:,} candles")
    console.print(f"[bold]Total in Storage:[/bold] {total_candles:,} candles")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Download all historical data")
    parser.add_argument("--pairs", type=str, help="Comma-separated pairs (default: top 10)")
    parser.add_argument("--timeframes", type=str, help="Comma-separated timeframes (default: all)")
    parser.add_argument("--sandbox", action="store_true", default=True, help="Use sandbox mode")
    
    args = parser.parse_args()
    
    pairs = args.pairs.split(",") if args.pairs else None
    timeframes = args.timeframes.split(",") if args.timeframes else None
    
    results = download_all_data(pairs, timeframes, args.sandbox)
    display_summary(results)
    
    console.print()
    console.print("[green]✓ Download complete![/green]")


if __name__ == "__main__":
    main()
