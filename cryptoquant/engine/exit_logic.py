"""Pure exit-check functions used by backtest and live engines."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ExitCheck:
    """Result of a single exit condition check."""

    should_exit: bool
    reason: str


def check_stop_loss(
    side: str,
    bar_high: float,
    bar_low: float,
    stop_loss_price: float | None,
    use_lows_for_stops: bool = True,
) -> ExitCheck:
    """Check whether stop-loss is triggered on this bar.

    For longs: triggered when bar_low <= stop_loss_price.
    For shorts: triggered when bar_high >= stop_loss_price.
    """
    if stop_loss_price is None or not use_lows_for_stops:
        return ExitCheck(False, "")

    if side == "long":
        if bar_low <= stop_loss_price:
            return ExitCheck(True, "stop_loss")
    else:
        if bar_high >= stop_loss_price:
            return ExitCheck(True, "stop_loss")

    return ExitCheck(False, "")


def check_take_profit(
    side: str,
    bar_high: float,
    bar_low: float,
    take_profit_price: float | None,
) -> ExitCheck:
    """Check whether take-profit is triggered on this bar.

    For longs: triggered when bar_high >= take_profit_price.
    For shorts: triggered when bar_low <= take_profit_price.
    """
    if take_profit_price is None:
        return ExitCheck(False, "")

    if side == "long":
        if bar_high >= take_profit_price:
            return ExitCheck(True, "take_profit")
    else:
        if bar_low <= take_profit_price:
            return ExitCheck(True, "take_profit")

    return ExitCheck(False, "")


def check_time_exit(
    entry_time: int,
    current_time: int,
    max_hold_time: int | None,
) -> ExitCheck:
    """Check whether max hold duration has been exceeded.

    Args:
        entry_time: Entry timestamp (engine-specific units).
        current_time: Current timestamp (same units as entry_time).
        max_hold_time: Maximum allowed hold duration (same units).
    """
    if max_hold_time is None:
        return ExitCheck(False, "")

    if (current_time - entry_time) >= max_hold_time:
        return ExitCheck(True, "time_exit")

    return ExitCheck(False, "")


def check_signal_reverse(
    current_signal: int,
    entry_signal: int,
) -> ExitCheck:
    """Check whether the current signal reverses the entry direction."""
    if current_signal != 0 and current_signal != entry_signal:
        return ExitCheck(True, "signal_reverse")

    return ExitCheck(False, "")


def determine_exit(*checks: ExitCheck) -> ExitCheck:
    """Select the highest-priority exit from a set of checks.

    Priority order: stop_loss > trailing_stop > take_profit > time_exit >
    signal_reverse.
    """
    priority = [
        "stop_loss",
        "trailing_stop",
        "take_profit",
        "time_exit",
        "signal_reverse",
    ]
    for reason in priority:
        for check in checks:
            if check.should_exit and check.reason == reason:
                return check
    return ExitCheck(False, "")
