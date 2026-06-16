"""Demo backtest using ATRSizer as default position sizer."""
import numpy as np
import pandas as pd

from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.risk.sizer import ATRSizer
from cryptoquant.strategy.base import Strategy


class DemoStrategy(Strategy):
    """Simple demo strategy: buy when price is above SMA20."""

    timeframe = "1h"
    min_bars = 50
    version = "1.0.0"
    DEFAULT_PARAMS = {"sma_period": 20}

    @property
    def name(self) -> str:
        return "DemoStrategy"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        sma = df["close"].rolling(window=self.params["sma_period"]).mean()
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[df["close"] > sma] = 1
        return signal


def main():
    # Generate synthetic OHLCV data
    n = 500
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.linspace(100, 150, n) + np.random.normal(0, 2, n)
    df = pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )

    # Create ATRSizer with default config
    sizer = ATRSizer(
        base_risk_pct=10.0,
        atr_period=14,
        multiplier=1.0,
        min_order=10.0,
        max_pct=100.0,
    )

    # Run backtest with ATRSizer
    engine = BacktestEngine(
        initial_capital=10_000,
        commission=0.001,
        slippage=0.0005,
        sizer=sizer,
    )

    strategy = DemoStrategy()
    result = engine.run(df, strategy, symbol="BTC/USDT")

    print(f"Strategy: {result.strategy_name}")
    print(f"Symbol: {result.symbol}")
    print(f"Total Return: {result.metrics.total_return_pct:+.2f}%")
    print(f"Total Trades: {result.metrics.total_trades}")
    print(f"Win Rate: {result.metrics.win_rate_pct:.1f}%")
    print(f"Max Drawdown: {result.metrics.max_drawdown_pct:.2f}%")
    print(f"Sharpe Ratio: {result.metrics.sharpe_ratio:.2f}")
    print(f"Final Equity: {result.final_equity:.2f}")


if __name__ == "__main__":
    main()
