"""Backtrader data feed from pandas DataFrame.

Provides PandasDataFeed for converting SQLite repository DataFrame output
to Backtrader's data feed format.
"""

import backtrader as bt
import pandas as pd


class PandasDataFeed(bt.feeds.PandasData):
    """Custom Backtrader data feed for our DataFrame format.

    Maps our standard columns (timestamp, open, high, low, close, volume)
    from SQLite repository's load_as_dataframe() output to Backtrader's format.
    """

    params = (
        ("datetime", 0),
        ("open", 1),
        ("high", 2),
        ("low", 3),
        ("close", 4),
        ("volume", 5),
        ("openinterest", -1),
    )

    @classmethod
    def from_dataframe(cls, dataframe: pd.DataFrame) -> "PandasDataFeed":
        """Create PandasDataFeed from a DataFrame.

        Args:
            dataframe: DataFrame with columns: timestamp, open, high, low, close, volume

        Returns:
            PandasDataFeed ready for Backtrader
        """
        processed_df = cls._prepare_dataframe(dataframe)
        return bt.feeds.PandasData(dataname=processed_df)

    @staticmethod
    def _prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """Prepare DataFrame for Backtrader.

        Converts timestamp to datetime and ensures proper column order.
        """
        df = df.copy()

        if "timestamp" in df.columns:
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.set_index("datetime")
        else:
            raise ValueError("DataFrame must have 'timestamp' column")

        required_cols = ["open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"DataFrame missing required column: {col}")

        return df[["open", "high", "low", "close", "volume"]]