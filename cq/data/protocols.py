"""Structural interfaces for data sources.

The archival functions depend on these rather than on `OkxPublicClient` so
that a test double is a first-class implementation rather than something
smuggled past the type checker.
"""

from __future__ import annotations

from typing import Protocol


class DerivativesSource(Protocol):
    """What the derivative archiver needs from a market data client."""

    def milliseconds(self) -> int: ...

    def funding_rate_history(
        self, inst_id: str, before_ts: int | None = ..., limit: int = ...
    ) -> list[dict]: ...

    def open_interest_volume(self, ccy: str, period: str = ...) -> list[list]: ...
