"""Enhance database with more historical data and fix metadata."""

import sys
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import requests
import structlog
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, BarColumn
from rich.table import Table
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import OHLCVCandleDB, DataVersionDB, Base

load_dotenv()
console = Console()
logger = structlog.get_logger(__name__)

PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
    "MATIC/USDT", "LTC/USDT", "BCH/USDT", "UNI/USDT", "ATOM/USDT"
]
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
BATCH_SIZE = 100
SLEEP_TIME = 0.05


def fetch_ohlcv(pair, timeframe, after=None, limit=100):
    """Fetch OHLCV data from OKX."""
    inst_id = pair.replace("/", "-")
    timeframe_map = {
        "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "8h": "8H", "12h": "12H",
        "1d": "1D", "3d": "3D", "1w": "1W", "1M": "1M"
    }
    bar = timeframe_map.get(timeframe, "1H")
    
    url = "https://www.okx.com/api/v5/market/history-candles"
    params = {"instId": inst_id, "bar": bar, "limit": limit}
    if after:
        params["after"] = after
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        if data.get("code") != "0":
            return []
        
        candles = []
        for item in data["data"]:
            candles.append({
                "timestamp": int(item[0]),
                "open": Decimal(item[1]),
                "high": Decimal(item[2]),
                "low": Decimal(item[3]),
                "close": Decimal(item[4]),
                "volume": Decimal(item[5]),
            })
        
        candles.reverse()
        return candles
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to fetch {pair} {timeframe}: {e}[/yellow]")
        return []


def save_candles(session, candles, pair, timeframe):
    """Save candles to database."""
    for candle_data in candles:
        candle = OHLCVCandleDB(
            timestamp=candle_data["timestamp"],
            pair=pair,
            timeframe=timeframe,
            open_price=float(candle_data["open"]),
            high_price=float(candle_data["high"]),
            low_price=float(candle_data["low"]),
            close_price=float(candle_data["close"]),
            volume=float(candle_data["volume"]),
        )
        session.merge(candle)
    session.commit()


def update_version_metadata(session, pair, timeframe):
    """Update version metadata with correct time range."""
    result = session.query(
        func.min(OHLCVCandleDB.timestamp),
        func.max(OHLCVCandleDB.timestamp),
        func.count(OHLCVCandleDB.id)
    ).filter(
        OHLCVCandleDB.pair == pair,
        OHLCVCandleDB.timeframe == timeframe
    ).first()
    
    if result and result[2] > 0:
        version = session.query(DataVersionDB).filter_by(
            pair=pair, timeframe=timeframe
        ).first()
        
        if version:
            version.min_timestamp = result[0]
            version.max_timestamp = result[1]
            version.count = result[2]
            version.updated_at = datetime.now(timezone.utc)
        else:
            version = DataVersionDB(
                pair=pair,
                timeframe=timeframe,
                version=1,
                min_timestamp=result[0],
                max_timestamp=result[1],
                count=result[2],
                data_source="OKX"
            )
            session.add(version)
        
        session.commit()
        return result[2]
    return 0


def download_historical_data(pair, timeframe, days=90):
    """Download historical data going back N days."""
    db_url = "sqlite:///data/cryptoquant.db"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Get existing range
        existing = session.query(
            func.min(OHLCVCandleDB.timestamp)
        ).filter(
            OHLCVCandleDB.pair == pair,
            OHLCVCandleDB.timeframe == timeframe
        ).scalar()
        
        target_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        
        if existing:
            after_ts = existing
        else:
            after_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        
        all_candles = []
        batch_count = 0
        max_batches = 500
        
        while after_ts > target_ts and batch_count < max_batches:
            batch_count += 1
            candles = fetch_ohlcv(pair, timeframe, after=after_ts, limit=BATCH_SIZE)
            
            if not candles:
                break
            
            save_candles(session, candles, pair, timeframe)
            all_candles.extend(candles)
            
            after_ts = min(c["timestamp"] for c in candles)
            
            if after_ts <= target_ts:
                break
            
            time.sleep(SLEEP_TIME)
        
        # Update metadata
        total_count = update_version_metadata(session, pair, timeframe)
        
        return {
            "pair": pair,
            "timeframe": timeframe,
            "new_candles": len(all_candles),
            "total_candles": total_count,
            "status": "success"
        }
        
    except Exception as e:
        return {
            "pair": pair,
            "timeframe": timeframe,
            "new_candles": 0,
            "total_candles": 0,
            "status": f"error: {str(e)[:50]}"
        }
    finally:
        session.close()


def fix_all_metadata():
    """Fix metadata for all existing data."""
    db_url = "sqlite:///data/cryptoquant.db"
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        versions = session.query(DataVersionDB).all()
        fixed = 0
        
        for version in versions:
            result = session.query(
                func.min(OHLCVCandleDB.timestamp),
                func.max(OHLCVCandleDB.timestamp),
                func.count(OHLCVCandleDB.id)
            ).filter(
                OHLCVCandleDB.pair == version.pair,
                OHLCVCandleDB.timeframe == version.timeframe
            ).first()
            
            if result and result[2] > 0:
                version.min_timestamp = result[0]
                version.max_timestamp = result[1]
                version.count = result[2]
                fixed += 1
        
        session.commit()
        return fixed
    finally:
        session.close()


def main():
    console.print("=" * 60)
    console.print("[bold blue]Enhancing Database with More Historical Data[/bold blue]")
    console.print("=" * 60)
    console.print()
    
    # First fix existing metadata
    console.print("[cyan]Fixing existing metadata...[/cyan]")
    fixed = fix_all_metadata()
    console.print(f"[green]Fixed {fixed} version records[/green]")
    console.print()
    
    # Download more data
    days = 90
    target_pairs = PAIRS[:5]  # Start with top 5 pairs
    target_timeframes = ["1h", "4h", "1d"]
    
    console.print(f"Downloading {days} days of data for {len(target_pairs)} pairs")
    console.print(f"Pairs: {', '.join(target_pairs)}")
    console.print(f"Timeframes: {', '.join(target_timeframes)}")
    console.print()
    
    results = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        total_tasks = len(target_pairs) * len(target_timeframes)
        main_task = progress.add_task("[cyan]Overall progress", total=total_tasks)
        
        for pair in target_pairs:
            for timeframe in target_timeframes:
                task_desc = f"{pair} {timeframe}"
                task = progress.add_task(task_desc, total=None)
                
                result = download_historical_data(pair, timeframe, days)
                results.append(result)
                
                progress.update(task, completed=True)
                progress.advance(main_task)
    
    # Show results
    console.print()
    console.print("[bold]Download Results:[/bold]")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Pair")
    table.add_column("Timeframe")
    table.add_column("New")
    table.add_column("Total")
    table.add_column("Status")
    
    for r in results:
        status_color = "green" if r["status"] == "success" else "red"
        table.add_row(
            r["pair"],
            r["timeframe"],
            str(r["new_candles"]),
            str(r["total_candles"]),
            f"[{status_color}]{r['status']}[/]"
        )
    
    console.print(table)
    
    total_new = sum(r["new_candles"] for r in results)
    success_count = sum(1 for r in results if r["status"] == "success")
    
    console.print()
    console.print(f"[bold green]Enhanced: {total_new} new candles across {success_count}/{len(results)} tasks[/bold green]")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
