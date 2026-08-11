"""Causal SPDP v2 signal, fixed-hold strategy, and schedule."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from cq.context import Context
from cq.core.types import FLAT, Intent
from cq.research.spdp.data import HOUR_MS, StudyData

WINDOW_BARS = 743


@dataclass(frozen=True)
class SpdpConfig:
    share_quantile: float = 0.75
    minimum_share_migration: float = 0.03
    impulse_sigma: float = 1.50
    impulse_hours: int = 12
    history_hours: int = 720
    hold_hours: int = 48
    target_weight: float = 0.25
    evaluation_start_ms: int = -(2**63)
    evaluation_end_ms: int = 2**63 - 1
    use_share_level: bool = True
    use_share_migration: bool = True
    use_positive_impulse: bool = True

    def __post_init__(self) -> None:
        if self.impulse_hours != 12 or self.history_hours != 720:
            raise ValueError("SPDP v2 freezes impulse_hours=12 and history_hours=720")
        if self.hold_hours <= 0:
            raise ValueError("hold_hours must be positive")
        if not 0.0 <= self.share_quantile <= 1.0:
            raise ValueError("share_quantile must be in [0, 1]")
        if self.minimum_share_migration < 0 or self.impulse_sigma < 0:
            raise ValueError("thresholds must be non-negative")
        if not 0 < self.target_weight <= 1:
            raise ValueError("target_weight must be in (0, 1]")


@dataclass(frozen=True)
class SpdpFeature:
    current_share: float
    prior_share: float
    share_q: float
    share_migration: float
    return_12h: float
    sigma: float


@dataclass(frozen=True)
class SignalEvent:
    decision_index: int
    entry_index: int
    exit_index: int
    feature: SpdpFeature


class SpdpStrategy:
    name = "spdp-v2"

    def __init__(self, config: SpdpConfig | None = None):
        self.config = config or SpdpConfig()
        self._remaining = 0

    @property
    def warmup_bars(self) -> int:
        return WINDOW_BARS

    def reset(self) -> None:
        self._remaining = 0

    def on_bar(self, ctx: Context) -> Intent:
        config = self.config
        if ctx.now < config.evaluation_start_ms:
            self._remaining = 0
            return FLAT

        if self._remaining > 1:
            self._remaining -= 1
            return Intent(target=config.target_weight, reason="spdp-hold")
        if self._remaining == 1:
            self._remaining = 0
            return Intent(target=0.0, reason="spdp-time-exit")

        entry_time = ctx.decision_time
        exit_time = entry_time + config.hold_hours * HOUR_MS
        if exit_time >= config.evaluation_end_ms:
            return FLAT

        spot_qv = ctx.market("DOGE-USDT-QV", "1h")
        swap_qv = ctx.market("DOGE-USDT-SWAP-QV", "1h")
        feature = signal_values(
            ctx.close(WINDOW_BARS),
            spot_qv.close(WINDOW_BARS),
            swap_qv.close(WINDOW_BARS),
            spot_qv.volume(WINDOW_BARS),
            swap_qv.volume(WINDOW_BARS),
            config,
        )
        if feature is None:
            return FLAT
        self._remaining = config.hold_hours
        return Intent(target=config.target_weight, reason="spdp-entry")


def signal_values(
    spot_close: np.ndarray,
    spot_quote_volume: np.ndarray,
    swap_quote_volume: np.ndarray,
    spot_volume: np.ndarray,
    swap_volume: np.ndarray,
    config: SpdpConfig,
) -> SpdpFeature | None:
    feature, passed = _measure(
        spot_close,
        spot_quote_volume,
        swap_quote_volume,
        spot_volume,
        swap_volume,
        config,
    )
    return feature if feature is not None and all(passed) else None


def _measure(
    spot_close: np.ndarray,
    spot_quote_volume: np.ndarray,
    swap_quote_volume: np.ndarray,
    spot_volume: np.ndarray,
    swap_volume: np.ndarray,
    config: SpdpConfig,
) -> tuple[SpdpFeature | None, tuple[bool, bool, bool, bool, bool]]:
    arrays = (
        spot_close,
        spot_quote_volume,
        swap_quote_volume,
        spot_volume,
        swap_volume,
    )
    if any(len(values) != WINDOW_BARS for values in arrays):
        raise ValueError(f"SPDP signal requires exactly {WINDOW_BARS} closed bars")
    positive = all(bool(np.all(np.asarray(values) > 0.0)) for values in arrays[1:])
    if not positive:
        return None, (False, False, False, False, False)

    rolling_spot = np.convolve(spot_quote_volume, np.ones(12), mode="valid")
    rolling_swap = np.convolve(swap_quote_volume, np.ones(12), mode="valid")
    shares = rolling_spot / (rolling_spot + rolling_swap)
    share_history = shares[: config.history_hours]
    current_share = float(shares[-1])
    prior_share = float(shares[config.history_hours - 1])
    share_q = float(
        np.quantile(share_history, config.share_quantile, method="linear")
    )

    returns = np.diff(np.log(spot_close))
    return_history = returns[10 : 10 + config.history_hours]
    sigma = float(np.std(return_history, ddof=1))
    sigma_positive = math.isfinite(sigma) and sigma > 0.0
    return_12h = float(math.log(spot_close[-1] / spot_close[-13]))
    feature = SpdpFeature(
        current_share=current_share,
        prior_share=prior_share,
        share_q=share_q,
        share_migration=current_share - prior_share,
        return_12h=return_12h,
        sigma=sigma,
    )
    share_level = (not config.use_share_level) or current_share >= share_q
    migration = (not config.use_share_migration) or (
        current_share - prior_share >= config.minimum_share_migration
    )
    impulse = (not config.use_positive_impulse) or (
        return_12h
        >= config.impulse_sigma * math.sqrt(config.impulse_hours) * sigma
    )
    return feature, (positive, sigma_positive, share_level, migration, impulse)


def build_schedule(
    data: StudyData, config: SpdpConfig | None = None
) -> list[SignalEvent]:
    config = config or SpdpConfig()
    events: list[SignalEvent] = []
    blocked_through_decision = -1
    last_decision = len(data.spot) - config.hold_hours - 2
    for decision_index in range(WINDOW_BARS - 1, last_decision + 1):
        if decision_index <= blocked_through_decision:
            continue
        entry_index = decision_index + 1
        exit_index = entry_index + config.hold_hours
        if int(data.spot.ts[decision_index]) < config.evaluation_start_ms:
            continue
        if int(data.spot.ts[exit_index]) >= config.evaluation_end_ms:
            continue
        start = decision_index - (WINDOW_BARS - 1)
        feature = signal_values(
            data.spot.close[start : decision_index + 1],
            data.spot_qv.close[start : decision_index + 1],
            data.swap_qv.close[start : decision_index + 1],
            data.spot_qv.volume[start : decision_index + 1],
            data.swap_qv.volume[start : decision_index + 1],
            config,
        )
        if feature is None:
            continue
        events.append(SignalEvent(decision_index, entry_index, exit_index, feature))
        blocked_through_decision = exit_index - 1
    return events


def condition_funnel(
    data: StudyData, config: SpdpConfig | None = None
) -> dict[str, int]:
    config = config or SpdpConfig()
    counts = {
        "eligible_decisions": 0,
        "positive_signal_window": 0,
        "positive_sigma": 0,
        "share_level": 0,
        "share_migration": 0,
        "positive_impulse": 0,
        "accepted_schedule": 0,
    }
    last_decision = len(data.spot) - config.hold_hours - 2
    for decision_index in range(WINDOW_BARS - 1, last_decision + 1):
        if int(data.spot.ts[decision_index]) < config.evaluation_start_ms:
            continue
        exit_index = decision_index + 1 + config.hold_hours
        if int(data.spot.ts[exit_index]) >= config.evaluation_end_ms:
            continue
        counts["eligible_decisions"] += 1
        start = decision_index - (WINDOW_BARS - 1)
        feature, passed = _measure(
            data.spot.close[start : decision_index + 1],
            data.spot_qv.close[start : decision_index + 1],
            data.swap_qv.close[start : decision_index + 1],
            data.spot_qv.volume[start : decision_index + 1],
            data.swap_qv.volume[start : decision_index + 1],
            config,
        )
        names = (
            "positive_signal_window",
            "positive_sigma",
            "share_level",
            "share_migration",
            "positive_impulse",
        )
        for name, ok in zip(names, passed, strict=True):
            if not ok:
                break
            counts[name] += 1
        if feature is None:
            continue
    counts["accepted_schedule"] = len(build_schedule(data, config))
    return counts
