"""Performance metrics.

Two decisions here exist because of specific past failures:

* **Annualisation is measured, never declared.** A previous study annualised
  4h results with the hourly factor sqrt(8760) and every Sharpe in the table
  came out exactly twice too large. The factor is derived from the median
  spacing of the equity curve's own timestamps, so a mislabelled timeframe
  cannot inflate it.
* **The best trade's P&L is reported separately.** The one surviving candidate
  went from +1,756% to +330% when its single best trade's profit was subtracted.
  A headline return that rests on one trade is a different claim from one that
  does not, and it should not take a follow-up question to find out which it is.
  This is a *static deduction* — the best trade's realised P&L taken off the
  final equity — and nothing more. It is deliberately not called a
  counterfactual: it does not re-run the strategy with that trade forbidden, so
  it ignores that later sizing, funding and drawdown all depend on the path the
  removed trade was part of. The honest name is "return less that P&L", and the
  field says exactly that.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

# The flat threshold has a single home in cq.core.types; the fill-pairing here
# routes every "position closed?" test through `is_flat` so a float crumb left
# by rounding or a flip is never read as a live reverse position.
from cq.core.types import Fill, is_flat

YEAR_MS = 365.25 * 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class Trade:
    """One round trip, from opening a position to closing it."""

    entry_ts: int
    exit_ts: int
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    pnl: float
    fees: float

    @property
    def net_pnl(self) -> float:
        return self.pnl - self.fees

    @property
    def return_pct(self) -> float:
        cost = abs(self.quantity * self.entry_price)
        return self.net_pnl / cost if cost else 0.0

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0

    @property
    def holding_ms(self) -> int:
        return self.exit_ts - self.entry_ts


@dataclass(frozen=True)
class Metrics:
    """Summary of one run. Every field is derived, none is assumed."""

    bars: int
    bars_per_year: float
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float
    longest_drawdown_days: float
    trades: int
    win_rate: float
    profit_factor: float
    # The final return with the single best trade's realised P&L subtracted from
    # equity. A static deduction, not a counterfactual re-run — see the module
    # docstring — so it is named for what it computes rather than what it might
    # be mistaken for.
    return_less_best_trade_pnl: float
    best_trade_pnl: float

    def summary(self) -> str:
        return (
            f"  return {self.total_return * 100:+.2f}%  CAGR {self.cagr * 100:+.2f}%  "
            f"Sharpe {self.sharpe:.2f}\n"
            f"  maxDD {self.max_drawdown * 100:.1f}%  longest underwater "
            f"{self.longest_drawdown_days:.0f}d\n"
            f"  trades {self.trades}  win rate {self.win_rate * 100:.1f}%  "
            f"profit factor {self.profit_factor:.2f}\n"
            f"  less the best trade's P&L (static deduction, not a re-run): "
            f"{self.return_less_best_trade_pnl * 100:+.2f}%"
        )


def bars_per_year(timestamps: Sequence[int] | np.ndarray) -> float:
    """Annualisation factor from the data's own spacing.

    Uses the median gap so a single missing bar cannot distort it.
    """
    stamps = np.asarray(timestamps, dtype=np.float64)
    if len(stamps) < 2:
        return 0.0
    spacing = float(np.median(np.diff(stamps)))
    if spacing <= 0:
        return 0.0
    return YEAR_MS / spacing


def max_drawdown(equity: Sequence[float] | np.ndarray) -> float:
    """Deepest peak-to-trough fall, as a positive fraction."""
    values = np.asarray(equity, dtype=np.float64)
    if len(values) == 0:
        return 0.0
    peaks = np.maximum.accumulate(values)
    drawdowns = np.where(peaks > 0, (peaks - values) / peaks, 0.0)
    return float(np.max(drawdowns))


def longest_drawdown_ms(
    timestamps: Sequence[int] | np.ndarray, equity: Sequence[float] | np.ndarray
) -> float:
    """Longest stretch spent below a previous peak.

    Reported because a strategy can be profitable and still be unholdable:
    the surviving spot candidate sat underwater for 457 days.
    """
    stamps = np.asarray(timestamps, dtype=np.float64)
    values = np.asarray(equity, dtype=np.float64)
    if len(values) < 2:
        return 0.0

    longest = 0.0
    peak = values[0]
    peak_ts = stamps[0]
    underwater = False

    for ts, value in zip(stamps, values, strict=True):
        if value < peak:
            underwater = True
            continue
        if underwater:
            # Measured to the moment of recovery, not to the last bar still
            # down, or every stretch comes out one bar short. Only counted
            # when the curve actually fell: a run of fresh highs is not a
            # sequence of one-bar drawdowns.
            longest = max(longest, ts - peak_ts)
            underwater = False
        peak = value
        peak_ts = ts

    if underwater:
        # Still below the peak when the test ended — the worst case of all,
        # and it must not be reported as shorter than one that recovered.
        longest = max(longest, stamps[-1] - peak_ts)
    return float(longest)


def sharpe_ratio(returns: np.ndarray, periods_per_year: float) -> float:
    """Annualised Sharpe of per-bar simple returns, zero risk-free rate."""
    if len(returns) < 2 or periods_per_year <= 0:
        return 0.0
    deviation = float(np.std(returns, ddof=1))
    if deviation == 0:
        return 0.0
    return float(np.mean(returns)) / deviation * math.sqrt(periods_per_year)


def per_bar_returns(equity: Sequence[float] | np.ndarray) -> np.ndarray:
    values = np.asarray(equity, dtype=np.float64)
    if len(values) < 2:
        return np.zeros(0)
    previous = values[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(previous != 0, (values[1:] - previous) / previous, 0.0)
    return np.asarray(out, dtype=np.float64)


def trades_from_fills(fills: Sequence[Fill]) -> list[Trade]:
    """Pair fills into round trips.

    A fill that flips the position closes one trade and opens another, which
    is what "reverse" means in target terms.
    """
    trades: list[Trade] = []
    quantity = 0.0
    entry_price = 0.0
    entry_ts = 0
    entry_fees = 0.0

    for fill in fills:
        delta = fill.signed_quantity
        if is_flat(quantity):
            quantity, entry_price, entry_ts, entry_fees = delta, fill.price, fill.ts, fill.fee
            continue

        if (quantity > 0) == (delta > 0):
            # Adding: move the basis, carry the fees.
            total = quantity + delta
            entry_price = (entry_price * quantity + fill.price * delta) / total
            quantity = total
            entry_fees += fill.fee
            continue

        closed = min(abs(delta), abs(quantity))
        direction = 1.0 if quantity > 0 else -1.0
        share = closed / abs(quantity)
        trades.append(
            Trade(
                entry_ts=entry_ts,
                exit_ts=fill.ts,
                side="long" if direction > 0 else "short",
                quantity=closed,
                entry_price=entry_price,
                exit_price=fill.price,
                pnl=direction * closed * (fill.price - entry_price),
                fees=entry_fees * share + fill.fee * (closed / abs(delta)),
            )
        )
        entry_fees *= 1 - share
        quantity += delta
        if is_flat(quantity):
            # Fully closed. Snap to exactly zero so the residual crumb left by
            # `quantity += delta` cannot survive to the next fill and be read as
            # a live position that opens a phantom trade.
            quantity = 0.0
            entry_price, entry_ts, entry_fees = 0.0, 0, 0.0
        elif (quantity > 0) != (direction > 0):
            # Flipped through zero: the remainder opens a fresh trade.
            entry_price = fill.price
            entry_ts = fill.ts
            entry_fees = fill.fee * (abs(quantity) / abs(delta))

    return trades


def _cagr(final: float, initial: float, years: float) -> float:
    """Annualised growth rate, or infinity where annualising is meaningless.

    A few hours of a good run compounds to something no float can hold — a
    +50% afternoon is 1.5 ** 1753 annualised — and raising OverflowError out
    of a metrics call kills the report that was about to disclose exactly how
    short the run was.
    """
    if years <= 0 or final <= 0 or initial <= 0:
        return 0.0
    try:
        return (final / initial) ** (1 / years) - 1.0
    except OverflowError:
        return math.inf


def position_spans(fills: Sequence[Fill]) -> list[tuple[int, int | None]]:
    """When the account was in a position: (entry_ts, exit_ts or None).

    A flip closes one span and opens the next at the same instant. The final
    span's exit is None when the run ended still holding.
    """
    spans: list[tuple[int, int | None]] = []
    quantity = 0.0
    entry_ts: int | None = None

    for fill in fills:
        previous = quantity
        quantity += fill.signed_quantity
        was_flat = is_flat(previous)
        now_flat = is_flat(quantity)
        if was_flat and not now_flat:
            entry_ts = fill.ts
        elif not was_flat and now_flat:
            spans.append((entry_ts if entry_ts is not None else fill.ts, fill.ts))
            entry_ts = None
            quantity = 0.0
        elif not was_flat and (previous > 0) != (quantity > 0):
            spans.append((entry_ts if entry_ts is not None else fill.ts, fill.ts))
            entry_ts = fill.ts

    if entry_ts is not None:
        spans.append((entry_ts, None))
    return spans


def episode_returns(
    timestamps: Sequence[int],
    equity: Sequence[float],
    fills: Sequence[Fill],
    initial_cash: float,
) -> list[float]:
    """What the *portfolio* did across each position, as a fraction of itself.

    This is what a bootstrap has to resample. A trade's own return on its own
    notional answers a different question, and three ways of getting it wrong
    all showed up in this project's reports:

    * a trade held at half weight returning +100% moved the account by +50%,
      but entered the bootstrap as +100%;
    * a position still open at the end of the run had no completed trade at
      all, so a run ending 50% down could report a 0% probability of loss;
    * funding and financing are charged to the account rather than to the
      trade, so a position that lost 10% entirely to funding entered the
      bootstrap as a flat 0%.

    Measuring from the equity curve between entry and exit fixes all three
    by construction: whatever the account actually did is what gets counted.
    """
    if not equity or not timestamps:
        return []
    index_of = {int(ts): i for i, ts in enumerate(timestamps)}
    last = len(equity) - 1

    returns: list[float] = []
    for entry_ts, exit_ts in position_spans(fills):
        entry_index = index_of.get(int(entry_ts))
        if entry_index is None:
            continue
        # The bar before the entry: the fill happens at this bar's open, so
        # its close already contains part of the position's result.
        opening = equity[entry_index - 1] if entry_index > 0 else initial_cash
        exit_index = last if exit_ts is None else index_of.get(int(exit_ts), last)
        if opening > 0:
            returns.append(equity[exit_index] / opening - 1.0)
    return returns


def compute_metrics(
    timestamps: Sequence[int],
    equity: Sequence[float],
    fills: Sequence[Fill],
    initial_cash: float,
) -> Metrics:
    """Everything derivable from one run."""
    trades = trades_from_fills(fills)
    returns = per_bar_returns(equity)
    per_year = bars_per_year(timestamps)
    final = equity[-1] if equity else initial_cash
    total_return = final / initial_cash - 1.0

    span_ms = (timestamps[-1] - timestamps[0]) if len(timestamps) > 1 else 0
    years = span_ms / YEAR_MS
    cagr = _cagr(final, initial_cash, years)

    wins = [t for t in trades if t.is_win]
    gross_win = sum(t.net_pnl for t in wins)
    gross_loss = -sum(t.net_pnl for t in trades if not t.is_win)

    best = max((t.net_pnl for t in trades), default=0.0)
    # Static: the best trade's realised P&L taken straight off final equity. Not
    # a re-run of the strategy without that trade, so it does not account for the
    # path dependence — sizing, funding, drawdown — the removed trade sat inside.
    less_best = (final - best) / initial_cash - 1.0 if trades else total_return

    return Metrics(
        bars=len(equity),
        bars_per_year=per_year,
        total_return=total_return,
        cagr=cagr,
        sharpe=sharpe_ratio(returns, per_year),
        max_drawdown=max_drawdown(equity),
        longest_drawdown_days=longest_drawdown_ms(timestamps, equity) / (24 * 3600 * 1000),
        trades=len(trades),
        win_rate=len(wins) / len(trades) if trades else 0.0,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else math.inf,
        return_less_best_trade_pnl=less_best,
        best_trade_pnl=best,
    )
