from cryptoquant.data.fetcher import OHLCVFetcher

def main():
    fetcher = OHLCVFetcher()
    fetcher.fetch("BTC/USDT", limit=10)


if __name__ == '__main__':
    main()