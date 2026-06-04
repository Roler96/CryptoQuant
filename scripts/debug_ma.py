
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from data.repository import get_repository

repo = get_repository()
df = repo.load_as_dataframe('BTC/USDT', '1h')
closes = df['close'].tolist()
print(f"Total bars: {len(closes)}")
print(f"First close: {closes[0]:.1f}")
print(f"Last close: {closes[-1]:.1f}")

# Calculate MA50 and MA200
def sma(data, period):
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(data[i-period+1:i+1]) / period)
    return result

ma50 = sma(closes, 50)
ma200 = sma(closes, 200)

# Find first valid point
first_valid = 199  # MA200 needs 200 bars
print(f"\nAt bar {first_valid} (first valid MA200):")
print(f"  Close: {closes[first_valid]:.1f}")
print(f"  MA50: {ma50[first_valid]:.1f}")
print(f"  MA200: {ma200[first_valid]:.1f}")
print(f"  MA50 > MA200: {ma50[first_valid] > ma200[first_valid]}")

# Count how many bars have MA50 > MA200
above_count = sum(1 for i in range(first_valid, len(closes)) if ma50[i] is not None and ma200[i] is not None and ma50[i] > ma200[i])
below_count = sum(1 for i in range(first_valid, len(closes)) if ma50[i] is not None and ma200[i] is not None and ma50[i] < ma200[i])
print(f"\nMA50 > MA200: {above_count} bars")
print(f"MA50 < MA200: {below_count} bars")

# Check when crossovers happen
crossovers = []
for i in range(first_valid + 1, len(closes)):
    if ma50[i] is None or ma200[i] is None or ma50[i-1] is None or ma200[i-1] is None:
        continue
    prev_above = ma50[i-1] > ma200[i-1]
    curr_above = ma50[i] > ma200[i]
    if prev_above != curr_above:
        crossovers.append((i, 'golden' if curr_above else 'death', closes[i]))

print(f"\nCrossovers: {len(crossovers)}")
for idx, ctype, price in crossovers[:10]:
    print(f"  Bar {idx}: {ctype} at price {price:.1f}")
