"""Derivative data archival: funding rates and open interest.

Why this runs nightly and everything else does not: OKX serves roughly three
months of funding history and only ~30 days of open interest. A day that is
not archived is gone permanently — no backfill exists at any price. Funding
is also a correctness input, not a nice-to-have: a swap backtest that ignores
it overstates every multi-day holding period.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from cq.data.protocols import DerivativesSource
from cq.data.store import Store, WriteResult

# Funding depth is ~3 months at 3 settlements/day, so a handful of 100-row
# pages walks the entire available history. Sweeping it all every run keeps
# the archiver stateless and self-healing after an outage.
FUNDING_MAX_PAGES = 8
FUNDING_PAGE_SIZE = 100


@dataclass
class ArchiveSummary:
    """Outcome of one archival sweep."""

    kind: str
    results: dict[str, WriteResult] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def rows_new(self) -> int:
        return sum(r.new for r in self.results.values())

    @property
    def rows_seen(self) -> int:
        return sum(r.seen for r in self.results.values())

    @property
    def ok(self) -> bool:
        return not self.errors


def archive_funding(
    client: DerivativesSource,
    store: Store,
    inst_ids: list[str],
    max_pages: int = FUNDING_MAX_PAGES,
) -> ArchiveSummary:
    """Sweep the full available funding history for each instrument."""
    summary = ArchiveSummary(kind="funding")
    for inst_id in inst_ids:
        started = client.milliseconds()
        run_id = store.start_run("funding", inst_id, started)
        try:
            rows = _collect_funding(client, inst_id, max_pages)
            result = store.upsert_funding(rows)
            summary.results[inst_id] = result
            store.finish_run(run_id, client.milliseconds(), result, ok=True)
            logger.info(
                "funding {}: {} rows seen, {} new", inst_id, result.seen, result.new
            )
        except Exception as exc:  # noqa: BLE001 - recorded, then reported per target
            summary.errors[inst_id] = f"{type(exc).__name__}: {exc}"
            store.finish_run(
                run_id, client.milliseconds(), WriteResult(0, 0), ok=False, error=str(exc)
            )
            logger.error("funding {} failed: {}", inst_id, exc)
    return summary


def _collect_funding(client: DerivativesSource, inst_id: str, max_pages: int) -> list[tuple]:
    fetched_at = client.milliseconds()
    rows: list[tuple] = []
    before: int | None = None
    for _ in range(max_pages):
        page = client.funding_rate_history(inst_id, before_ts=before, limit=FUNDING_PAGE_SIZE)
        if not page:
            break
        for entry in page:
            rows.append(
                (
                    entry["instId"],
                    int(entry["fundingTime"]),
                    float(entry["fundingRate"]),
                    _optional_float(entry.get("realizedRate")),
                    fetched_at,
                )
            )
        before = int(page[-1]["fundingTime"])
    return rows


def archive_open_interest(
    client: DerivativesSource,
    store: Store,
    currencies: list[str],
    period: str = "1H",
) -> ArchiveSummary:
    """Archive the open interest / volume series for each currency."""
    summary = ArchiveSummary(kind="open_interest")
    for ccy in currencies:
        started = client.milliseconds()
        run_id = store.start_run("open_interest", ccy, started)
        try:
            fetched_at = client.milliseconds()
            page = client.open_interest_volume(ccy, period=period)
            rows = [
                (
                    ccy,
                    int(entry[0]),
                    _optional_float(entry[1]),
                    _optional_float(entry[2]),
                    fetched_at,
                )
                for entry in page
            ]
            result = store.upsert_open_interest(rows)
            summary.results[ccy] = result
            store.finish_run(run_id, client.milliseconds(), result, ok=True)
            logger.info("open interest {}: {} rows seen, {} new", ccy, result.seen, result.new)
        except Exception as exc:  # noqa: BLE001 - recorded, then reported per target
            summary.errors[ccy] = f"{type(exc).__name__}: {exc}"
            store.finish_run(
                run_id, client.milliseconds(), WriteResult(0, 0), ok=False, error=str(exc)
            )
            logger.error("open interest {} failed: {}", ccy, exc)
    return summary


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)  # type: ignore[arg-type]
