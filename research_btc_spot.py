"""Reproducible research harness for the BTC/USDT four-hour spot strategy.

Development and historical-holdout phases are deliberately separate.  Run
``development`` first, freeze one parameter set, then pass it explicitly to
``holdout``.  The holdout command never searches or ranks parameters.
"""

import argparse
import sqlite3
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from cryptoquant.data.fetcher import validate_ohlcv
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.base import Strategy
from cryptoquant.utils import dataframe_fingerprint

DATA_START = pd.Timestamp("2019-01-01 00:00:00")
HOLDOUT_START = pd.Timestamp("2025-01-01 00:00:00")
# Binance, the primary source, ends at 2026-05-31 16:00.  Keep the bound
# exclusive so the final aggregate is a complete primary-source 4h bucket;
# secondary OKX data fills internal gaps only, never extends the snapshot.
DATA_END = pd.Timestamp("2026-05-31 16:00:00")
CAPITAL = 10_000.0
COMMISSION = 0.001
BASE_SLIPPAGE = 0.0005
DEPLOY_POSITION_PCT = 25.0

DEVELOPMENT_YEARS = range(2020, 2025)
ENTRY_GRID = (60, 120, 180)
EXIT_GRID = (30, 60, 90)
TREND_GRID = (300, 600, 1200)


@dataclass(frozen=True)
class Evaluation:
    label: str
    return_pct: float
    sharpe: float
    max_drawdown_pct: float
    trades: int
    profit_factor: float
    exposure_pct: float


class BtcSpotTrend(Strategy):
    """Research-only long-or-flat Donchian trend candidate."""

    timeframe = "4h"
    min_bars = 1201
    version = "1.0.0-rejected"
    signal_is_position = True
    DEFAULT_PARAMS = {
        "entry_bars": 120,
        "exit_bars": 90,
        "trend_bars": 600,
    }

    @property
    def name(self) -> str:
        return "BtcSpotTrendResearchCandidate"

    def validate_params(self) -> bool:
        entry = self.params["entry_bars"]
        exit_ = self.params["exit_bars"]
        trend = self.params["trend_bars"]
        for name, value in (
            ("entry_bars", entry),
            ("exit_bars", exit_),
            ("trend_bars", trend),
        ):
            if not isinstance(value, int) or value < 2:
                raise StrategyError(f"{name} must be an integer >= 2")
        if exit_ >= entry:
            raise StrategyError("exit_bars must be smaller than entry_bars")
        if trend < entry:
            raise StrategyError("trend_bars must be >= entry_bars")
        return True

    def _features(
        self, df: pd.DataFrame
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        entry_high = (
            df["high"].rolling(self.params["entry_bars"]).max().shift(1)
        )
        exit_low = (
            df["low"].rolling(self.params["exit_bars"]).min().shift(1)
        )
        trend = (
            df["close"].rolling(self.params["trend_bars"]).mean().shift(1)
        )
        return entry_high, exit_low, trend

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        entry_high, exit_low, trend = self._features(df)
        close = df["close"]
        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0
        for i in range(len(df)):
            if (
                pd.isna(entry_high.iloc[i])
                or pd.isna(exit_low.iloc[i])
                or pd.isna(trend.iloc[i])
            ):
                continue
            if position == 1:
                if close.iloc[i] < exit_low.iloc[i] or close.iloc[i] < trend.iloc[i]:
                    position = 0
            elif close.iloc[i] > entry_high.iloc[i] and close.iloc[i] > trend.iloc[i]:
                position = 1
            signal.iloc[i] = position
        return signal

    def generate_signal_for_position(
        self, df: pd.DataFrame, position_side: str | None
    ) -> pd.Series:
        if position_side not in (None, "long"):
            raise StrategyError(f"Unsupported spot position side: {position_side}")
        signal = self.generate_signal(df)
        if position_side == "long":
            _, exit_low, trend = self._features(df)
            close = df["close"].iloc[-1]
            signal.iloc[-1] = int(
                close >= exit_low.iloc[-1] and close >= trend.iloc[-1]
            )
        return signal


class ActiveFromStrategy(Strategy):
    """Mask pre-evaluation signals while retaining indicator warm-up bars."""

    timeframe = "4h"
    signal_is_position = True

    def __init__(self, inner: BtcSpotTrend, active_from: pd.Timestamp):
        self.inner = inner
        self.active_from = active_from
        self.min_bars = inner.min_bars
        super().__init__()

    @property
    def name(self) -> str:
        return f"ActiveFrom{self.inner.name}"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        signal = self.inner.generate_signal(df).copy()
        signal.loc[signal.index < self.active_from] = 0
        return signal


def load_hourly_snapshot() -> tuple[pd.DataFrame, int]:
    """Load a continuous, read-only hourly snapshot without network access."""
    db_path = Path(__file__).resolve().parent / "data" / "cryptoquant.db"
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    def load_table(table: str) -> pd.DataFrame:
        frame = pd.read_sql_query(
            f"SELECT timestamp, open, high, low, close, volume "
            f"FROM {table} ORDER BY timestamp",
            connection,
        )
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms")
        return frame.set_index("timestamp")

    try:
        binance = load_table("ohlcv_binance_BTC_USDT_1h")
        okx = load_table("ohlcv_okx_BTC_USDT_1h")
    finally:
        connection.close()

    index = pd.date_range(
        DATA_START,
        DATA_END - pd.Timedelta(hours=1),
        freq="1h",
    )
    primary = binance.reindex(index)
    missing_before = int(primary["close"].isna().sum())
    hourly = primary.combine_first(okx.reindex(index))
    if hourly.isna().any().any():
        missing = hourly.index[hourly.isna().any(axis=1)]
        raise RuntimeError(f"Unfilled hourly gaps: {list(missing[:10])}")
    validate_ohlcv(hourly, strict=True)
    return hourly, missing_before


def resample_complete_4h(hourly: pd.DataFrame, offset_hours: int = 0) -> pd.DataFrame:
    """Aggregate only buckets containing exactly four one-hour observations."""
    rule = "4h"
    offset = pd.Timedelta(hours=offset_hours)
    resampler = hourly.resample(rule, origin="start_day", offset=offset)
    counts = resampler["close"].count()
    bars = resampler.agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    bars = bars.loc[counts == 4].dropna()
    validate_ohlcv(bars, strict=True)
    return bars


def _profit_factor(pnls: list[float]) -> float:
    gains = sum(value for value in pnls if value > 0)
    losses = abs(sum(value for value in pnls if value < 0))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def evaluate(
    bars: pd.DataFrame,
    params: dict[str, int],
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    label: str,
    slippage: float = BASE_SLIPPAGE,
    delay_bars: int = 0,
    position_pct: float = 100.0,
) -> Evaluation:
    warmup_bars = max(BtcSpotTrend.min_bars, params["trend_bars"] + 1)
    warmup_start = start - pd.Timedelta(hours=4 * warmup_bars)
    sample = bars.loc[(bars.index >= warmup_start) & (bars.index < end)]
    if len(sample) <= warmup_bars:
        raise RuntimeError(f"Insufficient warm-up data for {label}")

    inner = BtcSpotTrend(params)
    strategy = ActiveFromStrategy(inner, start)
    sizer = None
    if position_pct < 100:
        from cryptoquant.risk.sizer import FixedSizer

        sizer = FixedSizer(risk_pct=position_pct)
    engine = BacktestEngine(
        initial_capital=CAPITAL,
        commission=COMMISSION,
        slippage=slippage,
        sizer=sizer,
    )
    if delay_bars:
        from cryptoquant.engine.latency import RandomLatency

        engine.latency_model = RandomLatency(
            min_bars=delay_bars,
            max_bars=delay_bars,
            seed=0,
        )
    result = engine.run(sample, strategy, symbol="BTC/USDT")
    curve = result.equity_curve.loc[
        (result.equity_curve.index >= start)
        & (result.equity_curve.index < end)
    ]
    if curve.empty:
        raise RuntimeError(f"Empty evaluation curve for {label}")

    daily = curve.resample("1D").last().pct_change().dropna()
    sharpe = (
        float(daily.mean() / daily.std() * np.sqrt(365))
        if len(daily) > 1 and daily.std() > 0
        else 0.0
    )
    drawdown = (curve / curve.cummax() - 1) * 100
    start_ms = int(start.value // 1_000_000)
    end_ms = int(end.value // 1_000_000)
    trades = [
        trade
        for trade in result.trades
        if start_ms <= trade.entry_time < end_ms
    ]
    exposure_hours = sum(
        max(
            0.0,
            (
                min(trade.exit_time, end_ms)
                - max(trade.entry_time, start_ms)
            )
            / 3_600_000,
        )
        for trade in trades
    )
    period_hours = (end - start).total_seconds() / 3600

    return Evaluation(
        label=label,
        return_pct=float((curve.iloc[-1] / CAPITAL - 1) * 100),
        sharpe=sharpe,
        max_drawdown_pct=float(drawdown.min()),
        trades=len(trades),
        profit_factor=_profit_factor([trade.pnl_abs for trade in trades]),
        exposure_pct=exposure_hours / period_hours * 100,
    )


def _parameter_grid() -> list[dict[str, int]]:
    return [
        {"entry_bars": entry, "exit_bars": exit_, "trend_bars": trend}
        for entry, exit_, trend in product(ENTRY_GRID, EXIT_GRID, TREND_GRID)
        if exit_ < entry and trend >= entry
    ]


def run_development(bars: pd.DataFrame) -> None:
    rows = []
    for params in _parameter_grid():
        folds = [
            evaluate(
                bars,
                params,
                pd.Timestamp(f"{year}-01-01"),
                pd.Timestamp(f"{year + 1}-01-01"),
                label=str(year),
            )
            for year in DEVELOPMENT_YEARS
        ]
        sharpes = np.array([fold.sharpe for fold in folds])
        returns = np.array([fold.return_pct for fold in folds])
        rows.append(
            {
                **params,
                "positive_years": int((returns > 0).sum()),
                "median_sharpe": float(np.median(sharpes)),
                "worst_sharpe": float(sharpes.min()),
                "worst_return_pct": float(returns.min()),
                "median_return_pct": float(np.median(returns)),
                "max_drawdown_pct": min(fold.max_drawdown_pct for fold in folds),
                "trades": sum(fold.trades for fold in folds),
                "score": float(np.median(sharpes) + 0.25 * sharpes.min()),
            }
        )

    frame = pd.DataFrame(rows).sort_values(
        ["positive_years", "score", "worst_return_pct"],
        ascending=[False, False, False],
    )
    print(f"Development trials: {len(frame)}")
    print(frame.to_string(index=False, float_format=lambda value: f"{value:.3f}"))


def _print_evaluations(evaluations: list[Evaluation]) -> None:
    frame = pd.DataFrame([evaluation.__dict__ for evaluation in evaluations])
    print(frame.to_string(index=False, float_format=lambda value: f"{value:.3f}"))


def run_holdout(bars: pd.DataFrame, params: dict[str, int]) -> None:
    evaluations = [
        evaluate(
            bars,
            params,
            HOLDOUT_START,
            DATA_END,
            label="holdout_signal_1x_15bps",
        ),
        evaluate(
            bars,
            params,
            HOLDOUT_START,
            DATA_END,
            label="holdout_deploy_25pct_15bps",
            position_pct=DEPLOY_POSITION_PCT,
        ),
        evaluate(
            bars,
            params,
            HOLDOUT_START,
            DATA_END,
            label="holdout_deploy_25pct_cost25bps",
            slippage=0.0015,
            position_pct=DEPLOY_POSITION_PCT,
        ),
        evaluate(
            bars,
            params,
            HOLDOUT_START,
            DATA_END,
            label="holdout_deploy_25pct_cost50bps",
            slippage=0.004,
            position_pct=DEPLOY_POSITION_PCT,
        ),
        evaluate(
            bars,
            params,
            HOLDOUT_START,
            DATA_END,
            label="holdout_deploy_25pct_delay1bar",
            delay_bars=1,
            position_pct=DEPLOY_POSITION_PCT,
        ),
    ]
    for year in (2025, 2026):
        start = max(HOLDOUT_START, pd.Timestamp(f"{year}-01-01"))
        end = min(DATA_END, pd.Timestamp(f"{year + 1}-01-01"))
        if start < end:
            evaluations.append(
                evaluate(
                    bars,
                    params,
                    start,
                    end,
                    label=f"holdout_deploy_{year}",
                    position_pct=DEPLOY_POSITION_PCT,
                )
            )

    for offset in (1, 2, 3):
        hourly, _ = load_hourly_snapshot()
        shifted = resample_complete_4h(hourly, offset_hours=offset)
        evaluations.append(
            evaluate(
                shifted,
                params,
                HOLDOUT_START,
                DATA_END,
                label=f"holdout_deploy_anchor_{offset}h",
                position_pct=DEPLOY_POSITION_PCT,
            )
        )
    _print_evaluations(evaluations)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("development", "holdout"))
    parser.add_argument("--entry-bars", type=int)
    parser.add_argument("--exit-bars", type=int)
    parser.add_argument("--trend-bars", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    hourly, filled = load_hourly_snapshot()
    bars = resample_complete_4h(hourly)
    print(
        f"Hourly rows={len(hourly)}, filled_from_OKX={filled}, "
        f"4h rows={len(bars)}, range={bars.index[0]}..{bars.index[-1]}, "
        f"sha256={dataframe_fingerprint(hourly)}"
    )

    if args.phase == "development":
        run_development(bars)
        return

    values = (args.entry_bars, args.exit_bars, args.trend_bars)
    if any(value is None for value in values):
        raise SystemExit(
            "holdout requires --entry-bars, --exit-bars and --trend-bars"
        )
    params = {
        "entry_bars": int(args.entry_bars),
        "exit_bars": int(args.exit_bars),
        "trend_bars": int(args.trend_bars),
    }
    print(f"Frozen holdout parameters: {params}")
    run_holdout(bars, params)


if __name__ == "__main__":
    main()
