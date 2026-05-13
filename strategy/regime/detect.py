"""Market regime detection runner.

Usage:
    python -m strategy.regime.detect
    python strategy/regime/detect.py --pair BTC/USDT --timeframe 1h --lookback 200
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from data.repository import get_repository
from strategy.regime import RegimeDetector


def main():
    parser = argparse.ArgumentParser(description="Market Regime Detection")
    parser.add_argument("--pair", "-p", default="BTC/USDT", help="Trading pair (default: BTC/USDT)")
    parser.add_argument("--timeframe", "-t", default="1h", help="Candle timeframe (default: 1h)")
    parser.add_argument("--lookback", "-l", type=int, default=200, help="Candles to analyze (default: 200)")
    args = parser.parse_args()

    repo = get_repository()
    candles = repo.load_candles(args.pair, args.timeframe, limit=args.lookback)

    if not candles:
        print(f"No data found for {args.pair} {args.timeframe}")
        print(f"Run: python -m data.downloader --pair {args.pair} --timeframe {args.timeframe}")
        sys.exit(1)

    detector = RegimeDetector()
    print(detector.summary(candles))


if __name__ == "__main__":
    main()
