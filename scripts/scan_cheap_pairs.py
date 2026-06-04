
"""Scan OKX for cheap USDT pairs suitable for small capital ($10-$100)."""
import ccxt
import sys

exchange = ccxt.okx({'enableRateLimit': True})

# Fetch all USDT spot markets
markets = exchange.load_markets()
usdt_spot = {s: m for s, m in markets.items() 
             if s.endswith('/USDT') and m.get('spot') and m.get('active')}

print(f"Total active USDT spot pairs: {len(usdt_spot)}")

# Fetch tickers
tickers = exchange.fetch_tickers(list(usdt_spot.keys()))

# Find cheap pairs with sufficient volume
cheap_pairs = []
for symbol, ticker in tickers.items():
    if ticker.get('last') is None:
        continue
    price = ticker['last']
    volume = ticker.get('quoteVolume', 0) or 0  # 24h volume in USDT
    spread = (ticker.get('ask', 0) - ticker.get('bid', 0)) / price * 100 if ticker.get('ask') and ticker.get('bid') and price > 0 else 999

    if price < 1.0 and volume > 50000:  # Under $1, >$50K daily volume
        cheap_pairs.append({
            'symbol': symbol,
            'price': price,
            'volume_24h': volume,
            'spread_pct': spread,
            'change_24h': ticker.get('percentage', 0),
            'min_amount': markets[symbol].get('limits', {}).get('amount', {}).get('min', None),
            'min_cost': markets[symbol].get('limits', {}).get('cost', {}).get('min', None),
        })

# Sort by volume
cheap_pairs.sort(key=lambda x: x['volume_24h'], reverse=True)

print(f"\nCheap pairs (<$1, >$50K vol): {len(cheap_pairs)}")
print(f"\n{'Symbol':<16} {'Price':>10} {'24h Vol':>12} {'Spread':>8} {'24h Chg':>8} {'Min Size':>10} {'Min Cost':>10}")
print("-" * 85)

for p in cheap_pairs[:30]:
    min_size = f"{p['min_amount']}" if p['min_amount'] else "N/A"
    min_cost = f"${p['min_cost']}" if p['min_cost'] else "N/A"
    print(f"{p['symbol']:<16} ${p['price']:>9.6f} ${p['volume_24h']:>11,.0f} {p['spread_pct']:>7.2f}% {p['change_24h']:>+7.1f}% {min_size:>10} {min_cost:>10}")

# Top picks for small capital
print("\n=== TOP PICKS FOR $10-$100 CAPITAL ===")
top = [p for p in cheap_pairs if p['volume_24h'] > 200000 and p['price'] < 0.50]
top.sort(key=lambda x: x['volume_24h'], reverse=True)
for p in top[:10]:
    shares_per_10 = 10 / p['price']
    shares_per_100 = 100 / p['price']
    print(f"  {p['symbol']:<16} ${p['price']:<8.4f}  $10={shares_per_10:.0f} shares  $100={shares_per_100:.0f} shares  Vol=${p['volume_24h']:,.0f}")
