
"""Download remaining small-cap pairs."""
import sys, os
sys.path.insert(0, '/home/roler/Code/CryptoQuant')
os.environ.setdefault('HTTP_PROXY', 'http://192.168.10.128:10808')
os.environ.setdefault('HTTPS_PROXY', 'http://192.168.10.128:10808')

from data.downloader import download
from data.repository import get_repository

PAIRS = ["XPL/USDT", "WLFI/USDT", "BASED/USDT", "CHZ/USDT"]
TIMEFRAME = "1h"
START = "2025-06-04"
END = "2026-06-04"

repo = get_repository()

for pair in PAIRS:
    existing = repo.load_candles(pair, TIMEFRAME, limit=1)
    print(f"\n{pair}: ", end="")
    if existing:
        print(f"updating from {existing[0].iso_time[:10]}")
        r = download(pair=pair, timeframe=TIMEFRAME, update=True)
    else:
        print(f"full download {START} -> {END}")
        r = download(pair=pair, timeframe=TIMEFRAME, start=START, end=END)
    print(f"  fetched={r.total_fetched} valid={r.valid_count} rejected={r.rejected_count}")

# Final inventory
print(f"\n=== DATA INVENTORY ===")
for pair in ["BTC/USDT", "TON/USDT", "DOGE/USDT"] + PAIRS:
    candles = repo.load_candles(pair, TIMEFRAME, limit=99999)
    if candles:
        print(f"  {pair:<16} {len(candles):>6} candles  {candles[0].iso_time[:10]} -> {candles[-1].iso_time[:10]}")
    else:
        print(f"  {pair:<16} EMPTY")
print("DONE")
