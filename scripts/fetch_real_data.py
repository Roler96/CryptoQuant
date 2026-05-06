"""Fetch real OHLCV data from OKX and store in database."""

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import requests
import structlog
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import OHLCVCandleDB, DataVersionDB, Base

load_dotenv()
console = Console()
logger = structlog.get_logger(__name__)


def fetch_ohlcv(pair: str, timeframe: str, limit: int = 100) -> list:
    """Fetch OHLCV data from OKX public API."""
    # Convert pair format BTC/USDT -> BTC-USDT
    inst_id = pair.replace("/", "-")
    
    # Map timeframe to OKX format
    timeframe_map = {
        "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "8h": "8H", "12h": "12H",
        "1d": "1D", "3d": "3D", "1w": "1W", "1M": "1M"
    }
    bar = timeframe_map.get(timeframe, "1H")
    
    url = "https://www.okx.com/api/v5/market/history-candles"
    params = {"instId": inst_id, "bar": bar, "limit": limit}
    
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    if data.get("code") != "0":
        raise ValueError(f"API error: {data.get('msg')}")
    
    candles = []
    for item in data["data"]:
        # Format: [timestamp, open, high, low, close, volume, ...]
        candles.append({
            "timestamp": int(item[0]),
            "open": Decimal(item[1]),
            "high": Decimal(item[2]),
            "low": Decimal(item[3]),
            "close": Decimal(item[4]),
            "volume": Decimal(item[5]),
        })
    
    # Reverse to get chronological order (oldest first)
    candles.reverse()
    
    return candles


def save_to_database(candles: list, pair: str, timeframe: str):
    """Save candles to database."""
    db_url = "sqlite:///data/cryptoquant.db"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
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
        
        # Update version
        version = session.query(DataVersionDB).filter_by(
            pair=pair, timeframe=timeframe
        ).first()
        
        if version:
            version.version += 1
            version.count = len(candles)
            version.updated_at = datetime.now(timezone.utc)
        else:
            version = DataVersionDB(
                pair=pair,
                timeframe=timeframe,
                version=1,
                count=len(candles),
                source="OKX",
            )
            session.add(version)
        
        session.commit()
        
    finally:
        session.close()
    
    return len(candles)


def main():
    console.print("=" * 60)
    console.print("[bold blue]Fetching Real OHLCV Data from OKX[/bold blue]")
    console.print("=" * 60)
    console.print()
    
    pair = "BTC/USDT"
    timeframe = "1h"
    limit = 100
    
    console.print(f"Pair: {pair}")
    console.print(f"Timeframe: {timeframe}")
    console.print(f"Limit: {limit}")
    console.print()
    
    try:
        with Progress(
            SpinnerColumn(),
            "[progress.description]{task.description}",
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"Fetching {pair} {timeframe}...", total=None)
            
            candles = fetch_ohlcv(pair, timeframe, limit)
            progress.update(task, completed=True)
        
        console.print(f"[green]Fetched {len(candles)} candles[/green]")
        
        if candles:
            first = candles[0]
            last = candles[-1]
            
            console.print(f"\nFirst candle: {datetime.fromtimestamp(first['timestamp']/1000, tz=timezone.utc)}")
            console.print(f"  Open: {first['open']}, Close: {first['close']}")
            console.print(f"  High: {first['high']}, Low: {first['low']}")
            console.print(f"  Volume: {first['volume']}")
            
            console.print(f"\nLast candle: {datetime.fromtimestamp(last['timestamp']/1000, tz=timezone.utc)}")
            console.print(f"  Open: {last['open']}, Close: {last['close']}")
            console.print(f"  High: {last['high']}, Low: {last['low']}")
            console.print(f"  Volume: {last['volume']}")
            
            # Save to database
            with Progress(
                SpinnerColumn(),
                "[progress.description]{task.description}",
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Saving to database...", total=None)
                count = save_to_database(candles, pair, timeframe)
                progress.update(task, completed=True)
            
            console.print(f"\n[bold green]Saved {count} candles to database![/bold green]")
            
            return 0
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
