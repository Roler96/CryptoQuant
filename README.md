# Crypto Quant Trading Platform

A Python-based quantitative trading platform for cryptocurrency markets using the OKX exchange.

## Features

- **Multi-strategy support**: Modular strategy framework for easy backtesting and deployment
- **Live trading**: Execute strategies with risk management controls
- **Backtesting engine**: Historical data analysis with realistic commission/slippage modeling
- **Risk management**: Position sizing, drawdown limits, and circuit breakers
- **Data collection**: Automated OHLCV data fetching and storage
- **CLI interface**: Command-line tools for strategy management and execution

## Quick Start

```bash
# Clone the repository
git clone <repo-url>
cd crypto-quant

# Set up environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your OKX API credentials

# Review config
cat config/config.yaml
```

## Project Structure

```
.
├── cli/              # Command-line interface tools
├── config/           # Configuration files
│   └── config.yaml   # Main configuration
├── data/             # Data storage
│   └── historical/   # Historical OHLCV data
├── backtest/         # Backtesting engine
├── live/             # Live trading execution
├── logs/             # Application logs
├── risk/             # Risk management module
├── strategy/         # Trading strategies
├── tests/            # Test suite
├── .env.example      # Environment template
├── requirements.txt  # Python dependencies
└── README.md         # This file
```

## Configuration

1. **Environment variables**: Copy `.env.example` to `.env` and add your OKX API credentials
2. **Platform config**: Edit `config/config.yaml` for trading parameters, risk limits, and strategy settings

**Security note**: API keys are never hardcoded. They are loaded from environment variables via `.env` (which is gitignored).

## Usage

```bash
# Run backtest
python -m cli.backtest --strategy sma --symbol BTC/USDT

# Start live trading (with dry-run first)
python -m cli.live --strategy sma --dry-run

# Fetch historical data
python -m cli.data --symbol BTC/USDT --timeframe 1h
```

## Development

```bash
# Run tests
pytest tests/ -v

# Format code
black .
ruff check . --fix

# Type check
mypy .
```

## Risk Disclaimer

Cryptocurrency trading carries substantial risk of loss. This platform is for educational and research purposes. Never trade with funds you cannot afford to lose. Always test strategies thoroughly in backtest and paper trading before live deployment.

## License

MIT
