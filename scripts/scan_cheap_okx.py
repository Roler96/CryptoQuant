
"""Scan cheap pairs using OKXClient (with proxy support)."""
import sys, os
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

# Ensure proxy env vars are set for subprocess
os.environ.setdefault('HTTP_PROXY', 'http://192.168.10.128:10808')
os.environ.setdefault('HTTPS_PROXY', 'http://192.168.10.128:10808')

from data.manager import OKXClient

# Use OKXClient with sandbox=False for public data
client = OKXClient(sandbox=False)

# Fetch tickers for spot USDT pairs
tickers = client.exchange.fetch_tickers()
usdt_tickers = {s: t for s, t in tickers.items() if s.endswith('/USDT') and t.get('last')}

print(f"Total USDT tickers: {len(usdt_tickers)}")

# Find cheap pairs
cheap = []
for sym, t in usdt_tickers.items():
    price = t['last']
    vol = t.get('quoteVolume') or 0
    if price < 1.0 and vol > 50000:
        cheap.append((sym, price, vol, t.get('percentage', 0)))

cheap.sort(key=lambda x: x[2], reverse=True)

print(f"\nCheap (<$1, >$50K vol): {len(cheap)}")
print(f"{'Symbol':<18} {'Price':>10} {'24h Vol':>12} {'24hChg':>8} {'$10 Buys':>10} {'$100 Buys':>10}")
print("-" * 75)
for sym, price, vol, chg in cheap[:25]:
    print(f"{sym:<18} ${price:>9.6f} ${vol:>11,.0f} {chg:>+7.1f}% {10/price:>9.0f} {100/price:>9.0f}")

# Top small-cap picks
print(f"\n=== BEST FOR $10-$100 (Vol>$200K, <$0.10) ===")
top = [(s, p, v) for s, p, v, _ in cheap if v > 200000 and p < 0.10]
top.sort(key=lambda x: x[2], reverse=True)
for sym, price, vol in top[:10]:
    commission_impact = 0.002 / price * 100  # 0.1% buy + 0.1% sell
    print(f"  {sym:<18} ${price:<8.6f}  Vol=${vol:>10,.0f}  "
          f"$10→{10/price:.0f} tokens  $100→{100/price:.0f} tokens  CommImpact={commission_impact:.3f}%")
