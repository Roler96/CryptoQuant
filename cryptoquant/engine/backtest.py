"""Vectorized backtesting engine."""

from collections import Counter
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd
from loguru import logger

from cryptoquant.engine.commission import CommissionModel, FlatCommission
from cryptoquant.engine.exit_logic import (
    check_signal_reverse,
    check_stop_loss,
    check_take_profit,
    check_time_exit,
    determine_exit,
)
from cryptoquant.engine.latency import LatencyModel, ZeroLatency
from cryptoquant.engine.slippage import FixedSlippage, SlippageModel
from cryptoquant.engine.types import BacktestResult, PerformanceMetrics, Trade
from cryptoquant.strategy.base import Strategy

PERIODS_PER_YEAR = {
    "1m": 365 * 24 * 60,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
    "1w": 52,
}

BAR_HOURS = {tf: (365 * 24) / p for tf, p in PERIODS_PER_YEAR.items()}

_HOURS_TO_TIMEFRAME = {hours: tf for tf, hours in BAR_HOURS.items()}


def _format_bar_hours(bar_hours: float) -> str:
    """Name a bar spacing the way an exchange would ('5m', '4h')."""
    for hours, tf in _HOURS_TO_TIMEFRAME.items():
        if np.isclose(bar_hours, hours, rtol=0.01):
            return tf
    minutes = round(bar_hours * 60)
    return f"{minutes}m" if minutes < 60 else f"{bar_hours:g}h"

# Bars of history handed to the sizer at each entry — mirrors the live feed
# window (OHLCVFetcher max_candles=300) so backtest sizing sees the same
# history depth as live trading.
SIZER_LOOKBACK_BARS = 300

# Deepest drawdowns listed in the report — the tail is noise once the worst
# few are known.
TOP_DRAWDOWN_PERIODS = 5


def _index_to_ms(index: pd.Index) -> np.ndarray:
    """Convert a DatetimeIndex to Unix-ms int64, handling ms/us/ns dtypes."""
    dtype_unit = str(index.dtype)
    if dtype_unit == "datetime64[ms]":
        return index.astype("int64").to_numpy(dtype=np.int64)
    if dtype_unit == "datetime64[us]":
        return index.astype("int64").to_numpy(dtype=np.int64) // 1_000
    return index.astype("int64").to_numpy(dtype=np.int64) // 1_000_000


@dataclass
class _Position:
    side: str
    entry_time: int
    entry_price: float
    entry_signal: int
    entry_idx: int
    stop_loss_price: float | None
    take_profit_price: float | None
    max_hold_bars: int | None
    high_since_entry: float
    low_since_entry: float


class BacktestEngine:
    """Vectorized backtesting engine.

    Entry: next bar open after signal (no look-ahead bias).
    Stop loss: checked against bar low/high (not close).
    Stop priority: stop_loss > take_profit > time_exit > signal_reverse.
    Compound returns model.

    Cost semantics (matches PaperBroker): ``commission`` and ``slippage``
    are PER-SIDE fractions — both are applied to the entry fill and again
    to the exit fill, so a round trip pays ~2x each.
    """

    def __init__(
        self,
        initial_capital: float = 10_000,
        commission: float = 0.001,
        slippage: float = 0.0005,
        use_lows_for_stops: bool = True,
        sizer=None,
        slippage_model: SlippageModel | None = None,
        latency_model: LatencyModel | None = None,
        commission_model: CommissionModel | None = None,
    ):
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.use_lows_for_stops = use_lows_for_stops
        self.sizer = sizer
        self.slippage_model = slippage_model or FixedSlippage(slippage)
        self.latency_model = latency_model or ZeroLatency()
        self.commission_model = commission_model or FlatCommission(commission)
        self._bars_to_hours: float = 1.0
        self._periods_per_year: float = 365 * 24

    @staticmethod
    def _resolve_bar_spacing(df: pd.DataFrame, strategy: Strategy) -> tuple[float, float]:
        """Return (hours per bar, bars per year) measured from the data.

        Taking these from strategy.timeframe instead trusts a declaration
        over the bars actually handed in. Feed a strategy declaring 4h a
        year of 5m bars and the engine reads len(df) / 2190 as 48 years,
        so a -92% loss reports as -5% annualized and holds inflate 48x.
        The metrics have to describe what was simulated.
        """
        declared = getattr(strategy, "timeframe", "1h")
        fallback = (BAR_HOURS.get(declared, 1.0), float(PERIODS_PER_YEAR.get(declared, 365 * 24)))

        if not isinstance(df.index, pd.DatetimeIndex) or len(df) < 3:
            return fallback

        # Median, not mean: gaps and DST steps must not drag the spacing.
        gaps = pd.Series(df.index).diff().dropna()
        if gaps.empty:
            return fallback
        spacing_seconds = float(gaps.dt.total_seconds().median())
        if not np.isfinite(spacing_seconds) or spacing_seconds <= 0:
            return fallback

        bar_hours = spacing_seconds / 3600
        declared_hours = BAR_HOURS.get(declared)
        if declared_hours is not None and not np.isclose(
            bar_hours, declared_hours, rtol=0.01
        ):
            logger.warning(
                f"{strategy.name} declares timeframe={declared} "
                f"({declared_hours:g}h/bar) but the data is spaced "
                f"{bar_hours:g}h/bar. Reporting against the data. If this is "
                f"not deliberate, the strategy is running on bars it was not "
                f"designed for."
            )
        return bar_hours, (365 * 24) / bar_hours

    def run(
        self,
        df: pd.DataFrame,
        strategy: Strategy,
        symbol: str = "",
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        max_hold_bars: int | None = None,
    ) -> BacktestResult:
        self._bars_to_hours, self._periods_per_year = self._resolve_bar_spacing(
            df, strategy
        )

        signals = strategy.generate_signal(df)
        trades = self._simulate_positions(
            df,
            signals,
            stop_loss_pct,
            take_profit_pct,
            max_hold_bars,
            signal_is_position=bool(
                getattr(strategy, "signal_is_position", False)
            ),
        )

        current_equity = self.initial_capital
        timestamps_ms = _index_to_ms(df.index)
        for trade in trades:
            trade.symbol = symbol
            if self.sizer is not None:
                # History up to (not including) the entry bar — the entry
                # fills at that bar's open, so only prior bars are known.
                entry_pos = int(timestamps_ms.searchsorted(trade.entry_time))
                history = df.iloc[max(0, entry_pos - SIZER_LOOKBACK_BARS) : entry_pos]
                position_size = self.sizer.calculate(
                    current_equity,
                    trade.entry_price,
                    df=history if not history.empty else None,
                )
                trade.pnl_abs = position_size * trade.pnl_pct / 100
            else:
                position_size = current_equity
                trade.pnl_abs = position_size * trade.pnl_pct / 100
            trade.position_size = position_size
            current_equity += trade.pnl_abs

        equity_curve = self._compute_equity_curve(trades, df)
        metrics = self._calculate_metrics(trades, equity_curve, df)
        drawdown_curve = _compute_drawdown_curve(equity_curve)

        return BacktestResult(
            strategy_name=strategy.name,
            strategy_version=getattr(strategy, "version", "unknown"),
            symbol=symbol,
            # The bars simulated, not the ones the strategy asked for — the
            # report must not name a timeframe the run never used.
            timeframe=_format_bar_hours(self._bars_to_hours),
            start_time=int(timestamps_ms[0]),
            end_time=int(timestamps_ms[-1]),
            initial_capital=self.initial_capital,
            final_equity=equity_curve.iloc[-1],
            trades=trades,
            metrics=metrics,
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            config={
                "commission": self.commission,
                "slippage": self.slippage,
                "initial_capital": self.initial_capital,
                "use_lows_for_stops": self.use_lows_for_stops,
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
                "max_hold_bars": max_hold_bars,
                "slippage_model": self.slippage_model.__class__.__name__,
                "latency_model": self.latency_model.__class__.__name__,
                "commission_model": self.commission_model.__class__.__name__,
            },
        )

    def _simulate_positions(
        self,
        df: pd.DataFrame,
        signals: pd.Series,
        stop_loss_pct: float | None,
        take_profit_pct: float | None,
        max_hold_bars: int | None,
        signal_is_position: bool = False,
    ) -> list[Trade]:
        trades: list[Trade] = []
        position: _Position | None = None
        trade_id = 0
        pending_signal: int = 0
        pending_delay: int = 0
        pending_exit_reason: str = ""

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        timestamps_ms = _index_to_ms(df.index)

        n = len(df)

        for i in range(n):
            # Fill a signal-based exit queued on the previous bar at this
            # bar's open. The signal needs that bar's close, so the fill
            # cannot happen earlier (matches live: order placed after the
            # closed bar, filled at the next bar).
            if position is not None and pending_exit_reason:
                trade_id += 1
                bar = pd.Series({
                    "open": opens[i],
                    "high": highs[i],
                    "low": lows[i],
                    "close": closes[i],
                })
                exit_price = self._get_exit_price(
                    bar, pending_exit_reason, position
                )
                trade = self._create_trade(
                    trade_id,
                    position,
                    i,
                    timestamps_ms[i],
                    exit_price,
                    pending_exit_reason,
                    highs,
                    lows,
                )
                trades.append(trade)
                position = None
                pending_exit_reason = ""

            if position is None and pending_signal != 0:
                if pending_delay > 0:
                    pending_delay -= 1
                else:
                    is_long = pending_signal == 1
                    entry_slip = self.slippage_model.calculate(
                        df.iloc[i], "long" if is_long else "short"
                    )
                    # Entry fills against you: longs pay up, shorts sell down.
                    entry_price = opens[i] * (
                        (1 + entry_slip) if is_long else (1 - entry_slip)
                    )
                    sl_price = None
                    tp_price = None
                    if stop_loss_pct:
                        if is_long:
                            sl_price = entry_price * (1 - stop_loss_pct / 100)
                        else:
                            sl_price = entry_price * (1 + stop_loss_pct / 100)
                    if take_profit_pct:
                        if is_long:
                            tp_price = entry_price * (1 + take_profit_pct / 100)
                        else:
                            tp_price = entry_price * (1 - take_profit_pct / 100)
                    position = _Position(
                        side="long" if pending_signal == 1 else "short",
                        entry_time=int(timestamps_ms[i]),
                        entry_price=entry_price,
                        entry_signal=pending_signal,
                        entry_idx=i,
                        stop_loss_price=sl_price,
                        take_profit_price=tp_price,
                        max_hold_bars=max_hold_bars,
                        high_since_entry=highs[i],
                        low_since_entry=lows[i],
                    )
                    pending_signal = 0

            if position is not None and not pending_exit_reason:
                sl_check = check_stop_loss(
                    position.side,
                    highs[i],
                    lows[i],
                    position.stop_loss_price,
                    self.use_lows_for_stops,
                )
                tp_check = check_take_profit(
                    position.side,
                    highs[i],
                    lows[i],
                    position.take_profit_price,
                )
                time_check = check_time_exit(
                    position.entry_idx, i, max_hold_bars
                )
                signal_check = check_signal_reverse(
                    int(signals.iloc[i]), position.entry_signal
                )
                exit_check = determine_exit(
                    sl_check, tp_check, time_check, signal_check
                )
                # Position-style strategies (signal = target position) close
                # when the signal returns to 0; pulse-style strategies emit 0
                # constantly, so this only applies when opted in.
                signal_flat = (
                    signal_is_position and int(signals.iloc[i]) == 0
                )

                if exit_check.should_exit and exit_check.reason != "signal_reverse":
                    # Price-triggered exits (stop/TP) fill intrabar; time
                    # exits need no bar-close information. Same-bar fill.
                    trade_id += 1
                    bar = pd.Series({
                        "open": opens[i],
                        "high": highs[i],
                        "low": lows[i],
                        "close": closes[i],
                    })
                    exit_price = self._get_exit_price(
                        bar, exit_check.reason, position
                    )
                    trade = self._create_trade(
                        trade_id,
                        position,
                        i,
                        timestamps_ms[i],
                        exit_price,
                        exit_check.reason,
                        highs,
                        lows,
                    )
                    trades.append(trade)
                    position = None
                elif exit_check.should_exit or signal_flat:
                    # Signal-based exits use this bar's close: queue the fill
                    # for the next bar's open.
                    pending_exit_reason = (
                        "signal_reverse"
                        if exit_check.should_exit
                        else "signal_exit"
                    )
                    if exit_check.should_exit:
                        pending_signal = int(signals.iloc[i])
                        pending_delay = self.latency_model.bars_delay()

            if position is None and pending_signal == 0:
                sig = int(signals.iloc[i])
                if sig in (1, -1):
                    pending_signal = sig
                    pending_delay = self.latency_model.bars_delay()

            if position is not None:
                position.high_since_entry = max(
                    position.high_since_entry, highs[i]
                )
                position.low_since_entry = min(
                    position.low_since_entry, lows[i]
                )

        if position is not None:
            trade_id += 1
            bar = pd.Series({
                "open": opens[n - 1],
                "high": highs[n - 1],
                "low": lows[n - 1],
                "close": closes[n - 1],
            })
            exit_price = self._get_exit_price(bar, "end_of_data", position)
            trade = self._create_trade(
                trade_id,
                position,
                n - 1,
                timestamps_ms[n - 1],
                exit_price,
                "end_of_data",
                highs,
                lows,
            )
            trades.append(trade)

        return trades

    def _get_exit_price(
        self,
        bar: pd.Series,
        exit_reason: str,
        position: _Position,
    ) -> float:
        slippage = self.slippage_model.calculate(bar, position.side)

        if exit_reason == "end_of_data":
            # The final close is the first executable price after the sample
            # outcome is known. Filling at that bar's open would travel back
            # in time after observing its close.
            price = float(bar["close"])
            return (
                price * (1 - slippage)
                if position.side == "long"
                else price * (1 + slippage)
            )

        if exit_reason == "stop_loss":
            price = position.stop_loss_price
            if price is None:
                return float(bar["open"])
            bar_open = float(bar["open"])
            # A stop becomes a market order once triggered. If the market
            # opens beyond it, the unavailable stop price cannot be filled.
            price = (
                min(price, bar_open)
                if position.side == "long"
                else max(price, bar_open)
            )
            if position.side == "long":
                price *= 1 - slippage
            else:
                price *= 1 + slippage
            return price

        if exit_reason == "take_profit":
            price = position.take_profit_price
            if price is None:
                return float(bar["open"])
            bar_open = float(bar["open"])
            # A favorable opening gap receives the opening price rather than
            # being artificially capped at the take-profit trigger.
            price = (
                max(price, bar_open)
                if position.side == "long"
                else min(price, bar_open)
            )
            if position.side == "long":
                price *= 1 - slippage
            else:
                price *= 1 + slippage
            return price

        if position.side == "long":
            return float(bar["open"]) * (1 - slippage)
        else:
            return float(bar["open"]) * (1 + slippage)

    def _create_trade(
        self,
        trade_id: int,
        position: _Position,
        exit_idx: int,
        exit_time_ms: int,
        exit_price: float,
        exit_reason: str,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> Trade:
        hold_bars = exit_idx - position.entry_idx
        hold_hours = hold_bars * self._bars_to_hours

        if position.side == "long":
            pnl_pct = (exit_price / position.entry_price - 1) * 100
            mae_pct = (
                min(lows[position.entry_idx : exit_idx + 1])
                / position.entry_price
                - 1
            ) * 100
            mfe_pct = (
                max(highs[position.entry_idx : exit_idx + 1])
                / position.entry_price
                - 1
            ) * 100
        else:
            pnl_pct = (1 - exit_price / position.entry_price) * 100
            mae_pct = (
                1
                - max(highs[position.entry_idx : exit_idx + 1])
                / position.entry_price
            ) * 100
            mfe_pct = (
                1
                - min(lows[position.entry_idx : exit_idx + 1])
                / position.entry_price
            ) * 100

        # Commission is charged per side (entry fill + exit fill), matching
        # PaperBroker and real exchange fee schedules.
        entry_commission = self.commission_model.calculate(
            position.entry_price, 1.0, position.side, is_maker=False
        )
        exit_commission = self.commission_model.calculate(
            exit_price, 1.0, position.side, is_maker=False
        )
        commission_pct = (
            (entry_commission + exit_commission) / position.entry_price * 100
        )
        pnl_pct -= commission_pct

        return Trade(
            id=trade_id,
            symbol="",
            side=position.side,
            entry_time=position.entry_time,
            entry_price=position.entry_price,
            entry_signal=position.entry_signal,
            exit_time=exit_time_ms,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl_pct=round(pnl_pct, 4),
            pnl_abs=0.0,
            hold_bars=hold_bars,
            hold_hours=round(hold_hours, 2),
            mae_pct=round(mae_pct, 4),
            mfe_pct=round(mfe_pct, 4),
        )

    def _compute_equity_curve(
        self,
        trades: list[Trade],
        df: pd.DataFrame,
    ) -> pd.Series:
        if not trades:
            return pd.Series(self.initial_capital, index=df.index, dtype=float)

        index_ms = _index_to_ms(df.index)
        closes = df["close"].to_numpy(dtype=float)
        curve_values = np.full(len(df), self.initial_capital, dtype=float)
        realized_equity = self.initial_capital

        for trade in trades:
            active = (index_ms >= trade.entry_time) & (index_ms < trade.exit_time)
            position_size = trade.position_size or realized_equity

            if active.any() and trade.entry_price > 0:
                if trade.side == "long":
                    gross_returns = closes[active] / trade.entry_price - 1
                else:
                    gross_returns = 1 - closes[active] / trade.entry_price

                entry_fee = self.commission_model.calculate(
                    trade.entry_price, 1.0, trade.side, is_maker=False
                )
                entry_fee_pct = entry_fee / trade.entry_price
                curve_values[active] = (
                    realized_equity
                    + position_size * (gross_returns - entry_fee_pct)
                )

            realized_equity += trade.pnl_abs
            curve_values[index_ms >= trade.exit_time] = realized_equity

        return pd.Series(curve_values, index=df.index, dtype=float)

    def _calculate_metrics(
        self,
        trades: list[Trade],
        equity_curve: pd.Series,
        df: pd.DataFrame,
    ) -> PerformanceMetrics:
        if not trades:
            return PerformanceMetrics(
                total_return_pct=0.0,
                annualized_return_pct=0.0,
                monthly_returns=pd.Series(dtype=float),
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                max_drawdown_pct=0.0,
                max_drawdown_days=0,
                volatility_annual_pct=0.0,
                var_95_pct=0.0,
                cvar_95_pct=0.0,
                total_trades=0,
                win_rate_pct=0.0,
                profit_factor=0.0,
                avg_win_pct=0.0,
                avg_loss_pct=0.0,
                avg_hold_hours=0.0,
                drawdown_periods=[],
            )

        total_return_pct = (
            equity_curve.iloc[-1] / self.initial_capital - 1
        ) * 100

        total_years = len(df) / self._periods_per_year
        if total_years <= 0:
            annualized_return_pct = 0.0
        elif total_return_pct <= -100:
            # Equity hit zero or went negative (possible for shorts). A
            # negative base to a fractional power has no real value, and
            # numpy would hand back a bare NaN that flows on into the
            # report. The account is wiped out — say so.
            annualized_return_pct = -100.0
        else:
            annualized_return_pct = (
                (1 + total_return_pct / 100) ** (1 / total_years) - 1
            ) * 100

        daily_returns = (
            equity_curve.resample("1D").last().pct_change().dropna()
        )

        if daily_returns.std() > 0:
            sharpe_ratio = (
                daily_returns.mean() / daily_returns.std() * np.sqrt(365)
            )
        else:
            sharpe_ratio = 0.0

        downside = daily_returns[daily_returns < 0]
        if len(downside) > 0 and downside.std() > 0:
            sortino_ratio = (
                daily_returns.mean() / downside.std() * np.sqrt(365)
            )
        else:
            sortino_ratio = 0.0

        drawdown_curve = _compute_drawdown_curve(equity_curve)
        max_drawdown_pct = abs(drawdown_curve.min())

        wins = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct <= 0]

        win_rate_pct = len(wins) / len(trades) * 100
        avg_win_pct = (
            float(np.mean([t.pnl_pct for t in wins])) if wins else 0
        )
        avg_loss_pct = (
            float(np.mean([t.pnl_pct for t in losses])) if losses else 0
        )

        total_wins = sum(t.pnl_pct for t in wins)
        total_losses = abs(sum(t.pnl_pct for t in losses))
        profit_factor = (
            total_wins / total_losses if total_losses > 0 else float("inf")
        )

        avg_hold_hours = float(np.mean([t.hold_hours for t in trades]))

        if len(daily_returns) > 0:
            var_95_pct = float(np.percentile(daily_returns, 5)) * 100
            cvar_95_pct = float(
                daily_returns[
                    daily_returns <= np.percentile(daily_returns, 5)
                ].mean()
            ) * 100
        else:
            var_95_pct = 0.0
            cvar_95_pct = 0.0

        volatility_annual_pct = (
            float(daily_returns.std() * np.sqrt(365) * 100)
            if len(daily_returns) > 0
            else 0.0
        )

        drawdown_periods = _find_drawdown_periods(drawdown_curve, df.index)
        max_drawdown_days = max(
            (dd["days"] for dd in drawdown_periods), default=0
        )

        monthly_returns = (
            equity_curve.resample("ME").last().pct_change().dropna() * 100
        )

        return PerformanceMetrics(
            total_return_pct=round(total_return_pct, 4),
            annualized_return_pct=round(annualized_return_pct, 4),
            monthly_returns=monthly_returns,
            sharpe_ratio=round(sharpe_ratio, 4),
            sortino_ratio=round(sortino_ratio, 4),
            max_drawdown_pct=round(max_drawdown_pct, 4),
            max_drawdown_days=max_drawdown_days,
            volatility_annual_pct=round(volatility_annual_pct, 4),
            var_95_pct=round(var_95_pct, 4),
            cvar_95_pct=round(cvar_95_pct, 4),
            total_trades=len(trades),
            win_rate_pct=round(win_rate_pct, 2),
            profit_factor=round(profit_factor, 4),
            avg_win_pct=round(avg_win_pct, 4),
            avg_loss_pct=round(avg_loss_pct, 4),
            avg_hold_hours=round(avg_hold_hours, 2),
            drawdown_periods=drawdown_periods,
        )


def _compute_drawdown_curve(equity_curve: pd.Series) -> pd.Series:
    running_max = equity_curve.cummax()
    return (equity_curve / running_max - 1) * 100


def _find_drawdown_periods(
    drawdown_curve: pd.Series, index: pd.Index
) -> list[dict]:
    periods = []
    in_drawdown = False
    start_idx = 0
    timestamps_ms = _index_to_ms(index)

    for i in range(len(drawdown_curve)):
        if drawdown_curve.iloc[i] < 0 and not in_drawdown:
            in_drawdown = True
            start_idx = i
        elif drawdown_curve.iloc[i] >= 0 and in_drawdown:
            in_drawdown = False
            dd_slice = drawdown_curve.iloc[start_idx:i]
            periods.append({
                "start": int(timestamps_ms[start_idx]),
                "end": int(timestamps_ms[i - 1]),
                "depth_pct": round(float(abs(dd_slice.min())), 4),
                "days": max(
                    1,
                    int(
                        (timestamps_ms[i - 1] - timestamps_ms[start_idx])
                        / 86_400_000
                    ),
                ),
            })

    if in_drawdown:
        dd_slice = drawdown_curve.iloc[start_idx:]
        periods.append({
            "start": int(timestamps_ms[start_idx]),
            "end": int(timestamps_ms[-1]),
            "depth_pct": round(float(abs(dd_slice.min())), 4),
            "days": max(
                1,
                int(
                    (timestamps_ms[-1] - timestamps_ms[start_idx])
                    / 86_400_000
                ),
            ),
        })

    return sorted(periods, key=lambda x: x["depth_pct"], reverse=True)


def _fmt_time(ts_ms: int) -> str:
    timestamp = cast(pd.Timestamp, pd.Timestamp(ts_ms, unit="ms"))
    return timestamp.strftime("%Y-%m-%d %H:%M")


def _price_decimals(trades: list[Trade]) -> int:
    """Decimals that keep ~5 significant digits at the trades' price scale.

    A DOGE fill near 0.08 needs 5; giving a BTC fill near 60,000 the same
    would pad the column with three meaningless zeros.
    """
    largest = max(max(abs(t.entry_price), abs(t.exit_price)) for t in trades)
    for threshold, decimals in ((1000, 2), (100, 3), (1, 4), (0.01, 5)):
        if largest >= threshold:
            return decimals
    return 8


_TRADE_COLUMNS = (
    "ID", "Side", "Entry Time", "Entry", "Exit Time", "Exit",
    "PnL%", "PnL", "Hold", "MAE%", "MFE%", "Exit Reason",
)


def _render_trade_log(trades: list[Trade]) -> list[str]:
    """Render one row per trade, with each column fitted to its widest value."""
    dp = _price_decimals(trades)
    rows = [
        (
            str(t.id),
            t.side,
            _fmt_time(t.entry_time),
            f"{t.entry_price:.{dp}f}",
            _fmt_time(t.exit_time),
            f"{t.exit_price:.{dp}f}",
            f"{t.pnl_pct:+.2f}",
            f"{t.pnl_abs:+,.2f}",
            f"{t.hold_hours:,.1f}h",
            f"{t.mae_pct:+.2f}",
            f"{t.mfe_pct:+.2f}",
            t.exit_reason,
        )
        for t in trades
    ]
    widths = [max(len(c) for c in col) for col in zip(_TRADE_COLUMNS, *rows)]

    def _line(cells: tuple[str, ...]) -> str:
        # Exit reason trails left-aligned: it is the one free-text column, and
        # padding it would leave every short reason on a ragged right edge.
        fixed = "   ".join(c.rjust(w) for c, w in zip(cells[:-1], widths[:-1]))
        return f"  {fixed}   {cells[-1]}"

    return [_line(_TRADE_COLUMNS), *(_line(r) for r in rows)]


def generate_report(result: BacktestResult, include_trades: bool = False) -> str:
    """Render a backtest result as a plain-text report.

    Args:
        result: The backtest to render.
        include_trades: Append a row per trade. Off by default because callers
            that already surface trades separately (see trades_to_dataframe)
            don't want hundreds of rows in the text report.
    """
    m = result.metrics

    lines = [
        f"{'=' * 60}",
        f"  Backtest Report: {result.strategy_name} v{result.strategy_version}",
        f"  Symbol: {result.symbol}",
        f"  Period: {_fmt_time(result.start_time)} -> {_fmt_time(result.end_time)}",
        f"  Timeframe: {result.timeframe}",
        f"{'=' * 60}",
        "",
        "-- PERFORMANCE --",
        f"  Total Return:       {m.total_return_pct:+.2f}%",
        f"  Annualized Return:  {m.annualized_return_pct:+.2f}%",
        f"  Final Equity:       {result.final_equity:,.2f} "
        f"(from {result.initial_capital:,.2f})",
        f"  Sharpe Ratio:       {m.sharpe_ratio:.2f}",
        f"  Sortino Ratio:      {m.sortino_ratio:.2f}",
        f"  Max Drawdown:       {m.max_drawdown_pct:.2f}%",
        f"  Max DD Days:        {m.max_drawdown_days}",
        f"  Volatility (ann):   {m.volatility_annual_pct:.2f}%",
        f"  VaR 95%:            {m.var_95_pct:.2f}%",
        f"  CVaR 95%:           {m.cvar_95_pct:.2f}%",
        "",
        "-- TRADES --",
        f"  Total Trades:       {m.total_trades}",
        f"  Win Rate:           {m.win_rate_pct:.1f}%",
        f"  Profit Factor:      {m.profit_factor:.2f}",
        f"  Avg Win:            {m.avg_win_pct:+.2f}%",
        f"  Avg Loss:           {m.avg_loss_pct:+.2f}%",
        f"  Avg Hold:           {m.avg_hold_hours:.1f}h",
    ]

    # Every section below is conditional: a run with no trades or no drawdown
    # would otherwise print a header with nothing under it.
    exit_counts = Counter(t.exit_reason for t in result.trades)
    if exit_counts:
        lines.append("")
        lines.append("-- EXIT BREAKDOWN --")
        for reason, count in exit_counts.most_common():
            pct = count / m.total_trades * 100
            lines.append(f"  {reason:20s}: {count:4d} ({pct:.0f}%)")

    if m.drawdown_periods:
        lines.append("")
        lines.append("-- DRAWDOWN PERIODS --")
        for dd in m.drawdown_periods[:TOP_DRAWDOWN_PERIODS]:
            lines.append(
                f"  {_fmt_time(dd['start'])} -> {_fmt_time(dd['end'])}: "
                f"{dd['depth_pct']:.1f}% ({dd['days']}d)"
            )

    if not m.monthly_returns.empty:
        lines.append("")
        lines.append("-- MONTHLY RETURNS --")
        for ts, ret in m.monthly_returns.items():
            timestamp = cast(pd.Timestamp, ts)
            lines.append(f"  {timestamp.strftime('%Y-%m')}: {ret:>+8.2f}%")

    if include_trades and result.trades:
        lines.append("")
        lines.append(f"-- TRADE LOG ({len(result.trades)} trades) --")
        lines.extend(_render_trade_log(result.trades))

    return "\n".join(lines)


def trades_to_dataframe(trades: list[Trade]) -> pd.DataFrame:
    records = []
    for t in trades:
        records.append({
            "id": t.id,
            "side": t.side,
            "entry_time": pd.to_datetime(t.entry_time, unit="ms"),
            "entry_price": t.entry_price,
            "exit_time": pd.to_datetime(t.exit_time, unit="ms"),
            "exit_price": t.exit_price,
            "exit_reason": t.exit_reason,
            "pnl_pct": t.pnl_pct,
            "hold_hours": t.hold_hours,
            "mae_pct": t.mae_pct,
            "mfe_pct": t.mfe_pct,
        })
    return pd.DataFrame(records)
