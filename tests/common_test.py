from cryptoquant.data.fetcher import OHLCVFetcher, validate_ohlcv
from cryptoquant.exceptions import DataFetchError, DataValidationError

def main():
    fetcher = OHLCVFetcher()
    df = fetcher.fetch("BTC/USDT", limit=10)


if __name__ == '__main__':
    main()