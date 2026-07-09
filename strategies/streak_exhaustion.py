"""Streak Exhaustion Fade — short-only FOMO-exhaustion reversal.

Aha: five consecutive hourly up-closes are not strength — they are
exhaustion. On BTC 5m data (2025-26), forward returns after an hourly
up-streak of >= 5 bars are strongly negative (~-40 bps over 12h vs -6 bps
unconditional), while the mirror image (down-streaks) shows no bounce at
all. The effect is monotone in streak length and present at 30m/1h/2h
scales. Mechanism: late FOMO buyers chase persistent green candles;
once the marginal buyer is in, price mean-reverts.

Entry (short): hourly close completes an up-streak of >= `streak_len`
bars whose cumulative return exceeds `min_streak_ret`.
Exit: time exit only — run the backtest/live engine with
``max_hold_bars`` equal to `hold_bars_5m` (default 144 = 12h).
The strategy never emits +1; it is short-only by design (the long
mirror has no edge).

Signals are emitted on the 5m grid: -1 on the 5m bar that closes the
streak-completing hour, so the engine enters at the next 5m open.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy


class StreakExhaustionFade(Strategy):
    """Short after >=N consecutive hourly up-closes; time-exit after 12h."""

    timeframe = "5m"
    min_bars = 300
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "streak_len": 5,
        "min_streak_ret": 0.005,
        "hold_bars_5m": 144,  # pass to engine as max_hold_bars
    }

    @property
    def name(self) -> str:
        return "StreakExhaustionFade"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        close: pd.Series = df["close"]

        k = int(self.params["streak_len"])
        min_ret = float(self.params["min_streak_ret"])

        # Hourly closes; bar labels are open times, so the hour labeled
        # 10:00 closes with the 5m bar labeled 10:55.
        hourly_close = close.resample("1h", label="left", closed="left").last()
        hourly_close = hourly_close.dropna()
        log_close = np.log(hourly_close)
        ret = log_close.diff()

        up = ret > 0
        # Consecutive up-close streak length, reset on any non-up bar
        groups = (up != up.shift()).cumsum()
        streak = up.groupby(groups).cumcount() + 1
        streak = streak.where(up, 0)

        cum_ret = log_close - log_close.shift(k)
        onset = (streak >= k) & (cum_ret > min_ret)

        # Map hourly onsets to the 5m bar that closes that hour. A 5m
        # bar closes its hour when its open time + 5min lands on the
        # hour boundary; this also keeps live windows ending mid-hour
        # from firing on an incomplete hourly bar.
        is_hour_close = (df.index + pd.Timedelta("5min")).minute == 0
        bar_hour = df.index.floor("1h")
        onset_at_bar = onset.reindex(bar_hour).fillna(False).to_numpy()

        signal = np.where(is_hour_close & onset_at_bar, -1, 0)
        return pd.Series(signal, index=df.index, dtype=int)
