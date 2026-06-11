"""Demo: Backtest MACrossover strategy on BTC/USDT using OKX real data."""
import json
import subprocess

import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine, generate_report
from strategies.example.ma_cross import MACrossover


def fetch_ohlcv_okx(symbol: str = "BTC-USDT", bar: str = "1H", limit: int = 300) -> pd.DataFrame:
    """Fetch OHLCV from OKX public API via curl (bypasses ccxt SSL issues)."""
    url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar={bar}&limit={limit}"
    result = subprocess.run(
        ["curl", "-s", url],
        capture_output=True, text=True, timeout=30
    )
    data = json.loads(result.stdout)
    if data.get("code") != "0":
        raise RuntimeError(f"OKX API error: {data.get('msg', 'unknown')}")

    candles = data["data"]
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "volCcy", "volCcyQuote", "confirm"])
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
    df.set_index("timestamp", inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df = df[["open", "high", "low", "close", "volume"]].sort_index()
    return df


def run_backtest():
    print("=" * 60)
    print("  CryptoQuant v1 — Backtest Demo (OKX Live Data + SQLite)")
    print("=" * 60)
    print()

    store = OHLCVStore(db_path="data/cryptoquant.db")

    print("[1/5] Fetching BTC/USDT 1h data from OKX...")
    df = fetch_ohlcv_okx(limit=300)
    print(f"  Fetched {len(df)} candles: {df.index[0]} -> {df.index[-1]}")

    print("[2/5] Saving to SQLite database...")
    rows = store.save(df, exchange="okx", symbol="BTC/USDT", timeframe="1h")
    print(f"  Saved {rows} rows to data/cryptoquant.db")

    print("[3/5] Loading from SQLite for backtest...")
    df_loaded = store.load(exchange="okx", symbol="BTC/USDT", timeframe="1h")
    print(f"  Loaded {len(df_loaded)} rows from database")

    print()

    # 2. Create strategy
    print("[4/5] Running backtest...")
    strategy = MACrossover({"fast": 12, "slow": 26, "signal_type": "long_only"})
    engine = BacktestEngine(
        initial_capital=10_000,
        commission=0.001,
        slippage=0.0005,
        use_lows_for_stops=True,
    )
    result = engine.run(
        df_loaded, strategy, symbol="BTC/USDT",
        stop_loss_pct=3.0,
        take_profit_pct=5.0,
        max_hold_bars=48,
    )
    print(f"  Done. {result.metrics.total_trades} trades simulated.")

    print("[5/5] Database status:")
    tables = store.list_tables()
    print(f"  Tables: {tables}")
    for table in tables:
        range_ = store.get_range("okx", "BTC/USDT", "1h")
        if range_:
            start = pd.Timestamp(range_[0], unit="ms", tz="UTC")
            end = pd.Timestamp(range_[1], unit="ms", tz="UTC")
            print(f"  {table}: {start} -> {end}")

    print()
    print(generate_report(result))


if __name__ == "__main__":
    run_backtest()
