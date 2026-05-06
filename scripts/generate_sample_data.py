"""Generate sample historical data for backtesting."""

import json
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

TIMEFRAME_MINUTES = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360,
    "8h": 480, "12h": 720, "1d": 1440, "3d": 4320,
    "1w": 10080, "1M": 43200,
}


def generate_candles(
    start_price: float = 50000.0,
    days: int = 365,
    volatility: float = 0.02,
    trend: float = 0.0001,
    timeframe: str = "1h",
) -> list[dict]:
    candles = []
    current_price = start_price
    minutes = TIMEFRAME_MINUTES.get(timeframe, 60)
    num_candles = int(days * 24 * 60 / minutes)
    start_time = datetime.now(timezone.utc) - timedelta(days=days)
    
    for i in range(num_candles):
        trend_component = trend * current_price
        random_component = random.gauss(0, volatility * current_price)
        
        open_price = current_price
        close_price = current_price + trend_component + random_component
        price_range = abs(close_price - open_price)
        high_price = max(open_price, close_price) + random.uniform(0, price_range * 0.5)
        low_price = min(open_price, close_price) - random.uniform(0, price_range * 0.5)
        
        base_volume = 100.0 if timeframe in ["1m", "5m", "15m"] else 1000.0
        volume = base_volume * random.uniform(0.5, 2.0)
        timestamp = int((start_time + timedelta(minutes=i * minutes)).timestamp() * 1000)
        
        candles.append({
            "timestamp": timestamp,
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": round(volume, 4),
        })
        
        current_price = close_price
    
    return candles


def save_to_parquet(candles: list[dict], pair: str, timeframe: str, data_dir: Path) -> None:
    pair_normalized = pair.replace("/", "_")
    parquet_path = data_dir / f"{pair_normalized}_{timeframe}.parquet"
    
    df = pd.DataFrame(candles)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    
    table = pa.Table.from_pandas(df)
    pq.write_table(table, parquet_path, compression="snappy")
    
    metadata_path = data_dir / "metadata.json"
    metadata = {}
    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)
    
    key = f"{pair_normalized}_{timeframe}"
    metadata["files"] = metadata.get("files", {})
    metadata["files"][key] = {
        "pair": pair,
        "timeframe": timeframe,
        "last_update_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "SAMPLE",
        "rows_count": len(candles),
        "file_path": str(parquet_path),
    }
    
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    
    print(f"  ✓ Saved {len(candles)} candles to {parquet_path}")


def generate_pair_data(pair: str, start_price: float, days: int = 365) -> None:
    data_dir = Path("data/historical")
    data_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\nGenerating {pair} data:")
    
    for timeframe in ["15m", "1h", "4h", "1d"]:
        candles = generate_candles(
            start_price=start_price,
            days=days,
            volatility=0.015,
            trend=0.00005,
            timeframe=timeframe,
        )
        save_to_parquet(candles, pair, timeframe, data_dir)


if __name__ == "__main__":
    print("=" * 60)
    print("Generating Sample Historical Data")
    print("=" * 60)
    
    generate_pair_data("BTC/USDT", start_price=45000.0, days=365)
    generate_pair_data("ETH/USDT", start_price=3000.0, days=365)
    
    print("\n" + "=" * 60)
    print("✓ Sample data generation complete!")
    print("=" * 60)
    print("\nGenerated data:")
    print("  - BTC/USDT: 15m, 1h, 4h, 1d (365 days)")
    print("  - ETH/USDT: 15m, 1h, 4h, 1d (365 days)")
    print("\nYou can now run backtests with:")
    print("  python -m cli.main backtest --strategy cta --pair BTC/USDT --timeframe 1h")
