"""Batch fetch historical data from OKX."""

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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import OHLCVCandleDB, DataVersionDB, Base

load_dotenv()
console = Console()
logger = structlog.get_logger(__name__)

PAIRS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"]
TIMEFRAMES = ["1h", "4h", "1d"]
BATCH_SIZE = 100
SLEEP_TIME = 0.1


def fetch_ohlcv(pair: str, timeframe: str, after: int = None, limit: int = 100) -> list:
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
    
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    if data.get("code") != "0":
        raise ValueError(f"API error: {data.get('msg')}")
    
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


def save_candles(session, candles: list, pair: str, timeframe: str):
    """Save candles to database."""
    for candle_data in candles:
        candle = OHLCVCandleDB(
            timestamp=candle_data["timestamp"],
            pair=pair,
            timeframe=timeframe,
            open_price=Decimal(str(candle_data["open"])),
            high_price=Decimal(str(candle_data["high"])),
            low_price=Decimal(str(candle_data["low"])),
            close_price=Decimal(str(candle_data["close"])),
            volume=Decimal(str(candle_data["volume"])),
        )
        session.merge(candle)
    
    session.commit()


def download_pair_timeframe(pair: str, timeframe: str, days: int = 30) -> dict:
    """Download historical data for a pair/timeframe."""
    db_url = "sqlite:///data/cryptoquant.db"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Find existing data
        from sqlalchemy import func
        existing = session.query(func.min(OHLCVCandleDB.timestamp), func.max(OHLCVCandleDB.timestamp)).filter(
            OHLCVCandleDB.pair == pair,
            OHLCVCandleDB.timeframe == timeframe
        ).first()
        
        if existing[0]:
            # Continue from oldest timestamp
            after_ts = existing[0]
        else:
            # Start from now minus days
            after_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        
        all_candles = []
        batch_count = 0
        max_batches = min(days * 24 if timeframe == "1h" else days, 300)  # Safety limit
        
        while batch_count < max_batches:
            batch_count += 1
            candles = fetch_ohlcv(pair, timeframe, after=after_ts, limit=BATCH_SIZE)
            
            if not candles:
                break
            
            save_candles(session, candles, pair, timeframe)
            all_candles.extend(candles)
            
            # Update after to oldest timestamp in this batch
            after_ts = min(c["timestamp"] for c in candles)
            
            # Stop if we've reached the target time range
            oldest_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
            if after_ts < oldest_ts:
                break
            
            time.sleep(SLEEP_TIME)
        
        # Update version
        version = session.query(DataVersionDB).filter_by(pair=pair, timeframe=timeframe).first()
        if version:
            version.version += 1
            version.count = session.query(OHLCVCandleDB).filter_by(pair=pair, timeframe=timeframe).count()
            version.updated_at = datetime.now(timezone.utc)
        else:
            count = session.query(OHLCVCandleDB).filter_by(pair=pair, timeframe=timeframe).count()
            version = DataVersionDB(
                pair=pair,
                timeframe=timeframe,
                version=1,
                count=count,
                data_source="OKX",
            )
            session.add(version)
        
        session.commit()
        
        return {
            "pair": pair,
            "timeframe": timeframe,
            "new_candles": len(all_candles),
            "total_candles": version.count,
            "status": "success"
        }
        
    except Exception as e:
        return {
            "pair": pair,
            "timeframe": timeframe,
            "new_candles": 0,
            "total_candles": 0,
            "status": f"error: {e}"
        }
    finally:
        session.close()


def main():
    console.print("=" * 60)
    console.print("[bold blue]Batch Download OKX Historical Data[/bold blue]")
    console.print("=" * 60)
    console.print()
    
    days = 30  # Default to 30 days
    console.print(f"Downloading {days} days of data for {len(PAIRS)} pairs, {len(TIMEFRAMES)} timeframes")
    console.print(f"Pairs: {', '.join(PAIRS)}")
    console.print(f"Timeframes: {', '.join(TIMEFRAMES)}")
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
        total_tasks = len(PAIRS) * len(TIMEFRAMES)
        main_task = progress.add_task("[cyan]Overall progress", total=total_tasks)
        
        for pair in PAIRS:
            for timeframe in TIMEFRAMES:
                task_desc = f"{pair} {timeframe}"
                task = progress.add_task(task_desc, total=None)
                
                result = download_pair_timeframe(pair, timeframe, days)
                results.append(result)
                
                progress.update(task, completed=True)
                progress.advance(main_task)
                
                time.sleep(SLEEP_TIME)
    
    # Show results
    console.print()
    console.print("[bold]Download Results:[/bold]")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Pair")
    table.add_column("Timeframe")
    table.add_column("New Candles")
    table.add_column("Total Candles")
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
    
    # Summary
    total_new = sum(r["new_candles"] for r in results)
    success_count = sum(1 for r in results if r["status"] == "success")
    
    console.print()
    console.print(f"[bold green]✓ Downloaded {total_new} new candles across {success_count}/{len(results)} tasks[/bold green]")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
