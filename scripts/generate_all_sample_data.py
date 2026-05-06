"""Generate comprehensive sample data for all major trading pairs."""

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

PAIRS_CONFIG = {
    "BTC/USDT": {"start": 45000, "vol": 0.015},
    "ETH/USDT": {"start": 3000, "vol": 0.018},
    "BNB/USDT": {"start": 600, "vol": 0.020},
    "SOL/USDT": {"start": 150, "vol": 0.025},
    "XRP/USDT": {"start": 0.6, "vol": 0.022},
    "DOGE/USDT": {"start": 0.15, "vol": 0.030},
    "TON/USDT": {"start": 5.5, "vol": 0.020},
    "ADA/USDT": {"start": 0.45, "vol": 0.025},
    "AVAX/USDT": {"start": 35, "vol": 0.028},
    "SHIB/USDT": {"start": 0.000025, "vol": 0.035},
}

TIMEFRAME_DAYS = {
    "1m": 7, "5m": 30, "15m": 90, "30m": 180,
    "1h": 365, "2h": 730, "4h": 1460, "6h": 2190,
    "8h": 2920, "12h": 3650, "1d": 3650, "3d": 3650,
    "1w": 3650, "1M": 3650,
}


def generate_candles(pair: str, timeframe: str, days: int, config: dict) -> list[dict]:
    candles = []
    current_price = config["start"]
    volatility = config["vol"]
    minutes = TIMEFRAME_MINUTES[timeframe]
    num_candles = int(days * 24 * 60 / minutes)
    start_time = datetime.now(timezone.utc) - timedelta(days=days)
    
    for i in range(num_candles):
        trend = 0.00005 * current_price
        noise = random.gauss(0, volatility * current_price)
        
        open_p = current_price
        close_p = current_price + trend + noise
        price_range = abs(close_p - open_p)
        high_p = max(open_p, close_p) + random.uniform(0, price_range * 0.5)
        low_p = min(open_p, close_p) - random.uniform(0, price_range * 0.5)
        
        base_vol = 1000.0 if timeframe in ["1m", "5m", "15m"] else 10000.0
        volume = base_vol * random.uniform(0.5, 2.0)
        timestamp = int((start_time + timedelta(minutes=i * minutes)).timestamp() * 1000)
        
        decimals = 8 if current_price < 0.01 else (4 if current_price < 1 else 2)
        
        candles.append({
            "timestamp": timestamp,
            "open": round(open_p, decimals),
            "high": round(high_p, decimals),
            "low": round(low_p, decimals),
            "close": round(close_p, decimals),
            "volume": round(volume, 4),
        })
        
        current_price = close_p
    
    return candles


def save_candles(candles: list[dict], pair: str, timeframe: str, data_dir: Path) -> None:
    pair_norm = pair.replace("/", "_").lower()
    parquet_path = data_dir / f"{pair_norm}_{timeframe}.parquet"
    
    df = pd.DataFrame(candles)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    
    table = pa.Table.from_pandas(df)
    pq.write_table(table, parquet_path, compression="snappy")


def generate_pair_data(pair: str, config: dict, data_dir: Path) -> dict:
    results = {}
    
    for timeframe, days in TIMEFRAME_DAYS.items():
        candles = generate_candles(pair, timeframe, days, config)
        save_candles(candles, pair, timeframe, data_dir)
        results[timeframe] = len(candles)
    
    return results


def main():
    print("=" * 70)
    print("Generating Comprehensive Sample Data")
    print("=" * 70)
    
    data_dir = Path("data/historical")
    data_dir.mkdir(parents=True, exist_ok=True)
    
    total_candles = 0
    all_results = {}
    
    for pair, config in PAIRS_CONFIG.items():
        print(f"\nGenerating {pair}...")
        results = generate_pair_data(pair, config, data_dir)
        all_results[pair] = results
        pair_total = sum(results.values())
        total_candles += pair_total
        print(f"  Total: {pair_total:,} candles")
        for tf, count in results.items():
            print(f"    {tf}: {count:,}")
    
    # Save metadata
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pairs": list(PAIRS_CONFIG.keys()),
        "timeframes": list(TIMEFRAME_DAYS.keys()),
        "results": all_results,
        "total_candles": total_candles,
    }
    
    with open(data_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    
    print("\n" + "=" * 70)
    print("✓ Generation Complete!")
    print("=" * 70)
    print(f"\nTotal Candles: {total_candles:,}")
    print(f"Pairs: {len(PAIRS_CONFIG)}")
    print(f"Timeframes: {len(TIMEFRAME_DAYS)}")
    print(f"\nStorage: {data_dir}")
    print("\nSample commands:")
    print("  python -m cli.main backtest --strategy cta --pair BTC/USDT --timeframe 1h")
    print("  python -m cli.main backtest --strategy cta --pair ETH/USDT --timeframe 15m")


if __name__ == "__main__":
    main()
