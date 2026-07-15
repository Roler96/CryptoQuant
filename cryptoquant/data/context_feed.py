"""Closed-bar feed that joins auxiliary OHLCV markets to a primary market."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import pandas as pd

from cryptoquant.data.closed_bar import BarFetchMeta, ClosedBarFeed
from cryptoquant.data.quality import QualityReport
from cryptoquant.exceptions import DataError, DataValidationError
from cryptoquant.strategy.base import MarketContext


class ContextualClosedBarFeed(ClosedBarFeed):
    """Align closed auxiliary bars without changing the traded market.

    The primary feed owns ``open/high/low/close/volume`` and determines whether
    a new decision bar exists.  Context feeds contribute only declared,
    prefixed columns. Missing timestamps remain NaN so strategies fail closed;
    stale auxiliary values are never forward-filled.
    """

    def __init__(
        self,
        primary: ClosedBarFeed,
        contexts: Sequence[tuple[MarketContext, ClosedBarFeed]],
    ):
        if not contexts:
            raise ValueError("ContextualClosedBarFeed needs at least one context")
        self._primary = primary
        self._contexts = tuple(contexts)
        outputs = [
            column
            for market, _feed in self._contexts
            for column in market.output_columns
        ]
        if len(outputs) != len(set(outputs)):
            raise DataValidationError("Context markets produce duplicate columns")
        self._last_common_ts: pd.Timestamp | None = None
        self._context_errors: dict[str, str] = {}

    def fetch(self, lookback: int) -> tuple[pd.DataFrame, BarFetchMeta]:
        primary, primary_meta = self._primary.fetch(lookback)
        result = primary.copy()
        context_frames: list[pd.DataFrame] = []
        self._context_errors = {}
        for market, feed in self._contexts:
            try:
                context, _context_meta = feed.fetch(lookback)
            except DataError as error:
                # Auxiliary failure must block entries, not prevent the live
                # engine from managing an already-open primary position.
                self._context_errors[market.alias] = str(error)
                for output in market.output_columns:
                    result[output] = float("nan")
                continue
            missing = sorted(set(market.columns).difference(context.columns))
            if missing:
                raise DataValidationError(
                    f"Context {market.live_symbol} missing columns: {missing}"
                )
            selected = context.loc[:, list(market.columns)].rename(
                columns={
                    column: f"{market.alias}_{column}"
                    for column in market.columns
                }
            )
            result = result.join(selected, how="left")
            context_frames.append(context)

        # A decision bar is new only after every context contains the primary
        # feed's latest closed timestamp. This avoids trading on a late
        # auxiliary candle and also lets that candle trigger later even when
        # the primary feed itself reports no newly closed bar on the retry.
        primary_latest = (
            cast(pd.Timestamp, primary.index[-1])
            if len(primary) and isinstance(primary.index, pd.DatetimeIndex)
            else None
        )
        contexts_ready = (
            primary_latest is not None
            and not self._context_errors
            and len(context_frames) == len(self._contexts)
            and all(
                len(frame) > 0 and frame.index[-1] == primary_latest
                for frame in context_frames
            )
            and all(
                result.loc[primary_latest, list(market.output_columns)].notna().all()
                for market, _feed in self._contexts
            )
            and all(
                feed.last_quality_report is None
                or feed.last_quality_report.is_healthy
                for _market, feed in self._contexts
            )
        )
        has_new_common = bool(
            contexts_ready and primary_latest != self._last_common_ts
        )
        if has_new_common:
            self._last_common_ts = primary_latest
        meta = BarFetchMeta(
            has_new_closed=has_new_common,
            stripped=primary_meta.stripped,
            common_bar_ts=(
                int(primary_latest.value // 1_000_000)
                if contexts_ready and primary_latest is not None
                else 0
            ),
            decision_ready=contexts_ready,
            issues=tuple(
                f"{alias}: {error}"
                for alias, error in sorted(self._context_errors.items())
            ),
            execution_price=primary_meta.execution_price,
        )
        return result.iloc[-lookback:], meta

    @property
    def last_fetch_ts(self) -> int:
        return min(
            [self._primary.last_fetch_ts]
            + [feed.last_fetch_ts for _market, feed in self._contexts]
        )

    @property
    def last_quality_report(self) -> QualityReport | None:
        named_reports = [("primary", self._primary.last_quality_report)] + [
            (market.alias, feed.last_quality_report)
            for market, feed in self._contexts
        ]
        reports = [(name, report) for name, report in named_reports if report is not None]
        if not reports and not self._context_errors:
            return None
        return QualityReport(
            is_healthy=(
                not self._context_errors
                and all(report.is_healthy for _name, report in reports)
            ),
            gap_count=sum(report.gap_count for _name, report in reports),
            stale_bars=sum(report.stale_bars for _name, report in reports),
            outlier_count=sum(report.outlier_count for _name, report in reports),
            volume_anomaly_count=sum(
                report.volume_anomaly_count for _name, report in reports
            ),
            details={
                **{name: report.details for name, report in reports},
                "context_errors": self._context_errors.copy(),
            },
        )

    @property
    def symbol(self) -> str:
        return self._primary.symbol

    @property
    def timeframe(self) -> str:
        return self._primary.timeframe

    def stats(self) -> dict:
        return {
            "primary": self._primary.stats(),
            "contexts": {
                market.alias: feed.stats() for market, feed in self._contexts
            },
        }
