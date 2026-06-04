
import sqlite3
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

conn = sqlite3.connect('/home/roler/Code/CryptoQuant/db/cryptoquant.db')
cursor = conn.cursor()
cursor.execute("SELECT pair, timeframe, COUNT(*) as cnt FROM candles GROUP BY pair, timeframe ORDER BY pair, timeframe")
rows = cursor.fetchall()
for row in rows:
    print(f'{row[0]:15s} {row[1]:5s} count={row[2]:6d}')
conn.close()
