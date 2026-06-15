"""
Analyze real OKX trade costs from your account history.

Outputs:
  - Effective maker/taker commission rate (per side)
  - Fee statistics per symbol
  - Recommended BacktestEngine commission parameter (round-trip)

Usage:
  uv run python research/analyze_okx_trade_costs.py --mode demo --symbols BTC/USDT ETH/USDT --days 90

Prerequisites:
  - Set env vars in ~/VibeCoding/.env or export them:
    OKX_API_KEY / OKX_API_SECRET / OKX_PASSPHRASE  (live)
    OKX_SANDBOX_API_KEY / OKX_SANDBOX_API_SECRET / OKX_SANDBOX_PASSPHRASE  (demo)
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from statistics import mean, median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

_ENV_PATHS = [
    os.path.join(os.path.expanduser("~"), "Code", "VibeCoding", ".env"),
    os.path.join(os.path.expanduser("~"), "VibeCoding", ".env"),
]
_ENV_PATH = None
for _ep in _ENV_PATHS:
    if os.path.exists(_ep):
        _ENV_PATH = _ep
        break

if _ENV_PATH is None:
    print("No .env found. Tried: " + ", ".join(_ENV_PATHS), file=sys.stderr)
    sys.exit(1)

load_dotenv(_ENV_PATH)

# okx_helper lives outside this repo (VibeCoding dir or ~/.hermes/scripts)
_OKX_HELPER_PATHS = [
    os.path.join(os.path.expanduser("~"), "VibeCoding"),
    os.path.join(os.path.expanduser("~"), ".hermes", "scripts"),
]
for _p in _OKX_HELPER_PATHS:
    if _p not in sys.path and os.path.exists(os.path.join(_p, "okx_helper.py")):
        sys.path.insert(0, _p)
        break

from okx_helper import LiteOKX, get_okx, TRADING_PAIRS


def fetch_trades(ex: LiteOKX, symbol: str, since_ms: int) -> list[dict]:
    """Fetch all my trades since timestamp, paginating if needed."""
    trades = []
    while True:
        batch = ex.fetch_my_trades(symbol, since=since_ms, limit=100)
        if not batch:
            break
        trades.extend(batch)
        since_ms = batch[-1]["timestamp"] + 1
        if len(batch) < 100:
            break
    return trades


def analyze_trades(trades: list[dict], symbol: str) -> dict:
    """Compute commission stats from ccxt trade objects."""
    if not trades:
        return {"symbol": symbol, "count": 0}

    maker_rates = []
    taker_rates = []
    all_rates = []

    for t in trades:
        price = float(t["price"])
        amount = float(t["amount"])
        fee = t.get("fee", {})
        fee_cost = float(fee.get("cost", 0.0)) if fee else 0.0
        notional = price * amount

        if notional <= 0:
            continue

        rate = fee_cost / notional
        all_rates.append(rate)

        taker_or_maker = t.get("takerOrMaker")
        if taker_or_maker == "maker":
            maker_rates.append(rate)
        elif taker_or_maker == "taker":
            taker_rates.append(rate)

    def _stats(rates):
        if not rates:
            return None
        return {
            "count": len(rates),
            "mean_bps": round(mean(rates) * 10000, 3),
            "median_bps": round(median(rates) * 10000, 3),
            "min_bps": round(min(rates) * 10000, 3),
            "max_bps": round(max(rates) * 10000, 3),
        }

    return {
        "symbol": symbol,
        "count": len(trades),
        "all": _stats(all_rates),
        "maker": _stats(maker_rates),
        "taker": _stats(taker_rates),
    }


def print_report(results: list[dict], mode: str):
    print(f"\n{'=' * 70}")
    print(f"  OKX Trade Cost Analysis — mode={mode}")
    print(f"{'=' * 70}")

    for r in results:
        print(f"\n{r['symbol']} — {r['count']} trades")
        if r["count"] == 0:
            print("  No trades found.")
            continue

        for label in ("all", "maker", "taker"):
            stats = r[label]
            if stats is None:
                continue
            print(
                f"  {label:6s}: n={stats['count']:>4}  "
                f"mean={stats['mean_bps']:>7.3f} bps  "
                f"median={stats['median_bps']:>7.3f} bps  "
                f"min={stats['min_bps']:>7.3f} bps  "
                f"max={stats['max_bps']:>7.3f} bps"
            )

        if r["maker"] and r["taker"]:
            maker_mean = r["maker"]["mean_bps"] / 10000
            taker_mean = r["taker"]["mean_bps"] / 10000
            print(
                f"\n  Recommended BacktestEngine params for {r['symbol']}:\n"
                f"    If using maker orders:  commission={maker_mean * 2:.4f}  (round-trip)  slippage=0.0002~0.0005\n"
                f"    If using taker orders:  commission={taker_mean * 2:.4f}  (round-trip)  slippage=0.0005~0.0010"
            )

    print(f"\n{'=' * 70}")
    print("  Note: commission above is per side; round-trip = 2 × per side.")
    print("  Slippage must be estimated separately from fill vs expected price.")
    print(f"{'=' * 70}\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze OKX trade costs")
    parser.add_argument(
        "--mode",
        choices=["demo", "live"],
        default="demo",
        help="OKX account mode",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTC/USDT"],
        help="Symbols to analyze",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="How many days of trade history to fetch",
    )
    args = parser.parse_args()

    for sym in args.symbols:
        if sym not in TRADING_PAIRS:
            print(
                f"Warning: {sym} not in okx_helper.TRADING_PAIRS. "
                f"Add it there first or fetch may fail."
            )

    ex = get_okx(args.mode)
    ex.load_markets()

    since_ms = int(
        (datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp() * 1000
    )

    results = []
    for sym in args.symbols:
        try:
            trades = fetch_trades(ex, sym, since_ms)
            results.append(analyze_trades(trades, sym))
        except Exception as e:
            print(f"Error fetching {sym}: {e}", file=sys.stderr)
            results.append({"symbol": sym, "count": 0, "error": str(e)})

    print_report(results, args.mode)


if __name__ == "__main__":
    main()
