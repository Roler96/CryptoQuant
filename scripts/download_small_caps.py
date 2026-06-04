
"""Download historical data for small-cap pairs. Uses correct download() API."""
import sys, os
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

os.environ.setdefault('HTTP_PROXY', 'http://192.168.10.128:10808')
os.environ.setdefault('HTTPS_PROXY', 'http://192.168.10.128:10808')

from data.downloader import download
from data.repository import get_repository
from datetime import datetime, timedelta

SMALL_CAP_PAIRS = ["DOGE/USDT", "XPL/USDT", "WLFI/USDT", "BASED/USDT"]
TIMEFRAME = "1h"

# Date range: 1 year back
start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
end_date = datetime.now().strftime('%Y-%m-%d')

repo = get_repository()

for pair in SMALL_CAP_PAIRS:
    print(f"\n{'='*60}")
    print(f"Downloading {pair} {TIMEFRAME}...")
    
    existing = repo.load_candles(pair, TIMEFRAME, limit=1)
    if existing:
        print(f"  Existing data: {existing[0].iso_time[:10]}")
        result = download(pair=pair, timeframe=TIMEFRAME, update=True)
    else:
        print(f"  No existing data, full download from {start_date}")
        result = download(pair=pair, timeframe=TIMEFRAME, start=start_date, end=end_date)
    
    print(f"  Downloaded: {result.candles_downloaded}, "
          f"Skipped: {result.candles_skipped}, "
          f"Invalid: {result.candles_invalid}")

# Summary
print(f"\n{'='*60}")
print("FINAL DATA INVENTORY")
print(f"{'='*60}")
for pair in ["BTC/USDT", "TON/USDT"] + SMALL_CAP_PAIRS:
    candles = repo.load_candles(pair, TIMEFRAME, limit=99999)
    if candles:
        print(f"  {pair:<16} {len(candles):>6} candles  "
              f"{candles[0].iso_time[:10]} → {candles[-1].iso_time[:10]}")
    else:
        print(f"  {pair:<16} NO DATA")
print("DONE")
