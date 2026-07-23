"""Data splits and the honesty they enforce.

`FORWARD_FREEZE` is the boundary of the current research program: data before
it is for exploration, data at or after it is validation the program commits
not to look at while exploring. Splits are fingerprinted so a study cannot
quietly move its own boundaries between runs, and every read of a holdout is
recorded — an unrecorded peek is indistinguishable from no peek, and the count
of reads is itself the multiple-testing correction.

The boundary was reset to 2025-06-01 when the prior strategy research was
abandoned wholesale. One caveat travels with that reset and must not be
forgotten: the abandoned program did observe DOGE data through 2026-07, so the
2025-06 → 2026-07 slice of the validation window was seen before this boundary
was drawn. Validation there is the weakest grade — a robustness check, not
untouched evidence — because discarding the old strategies does not un-see the
period's price action. Genuinely untouched adjudication is the part of the
window after 2026-07, and it grows one bar at a time as 2027 accrues; it cannot
be hurried.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
from dataclasses import asdict, dataclass
from pathlib import Path

# The explore/validate boundary of the research program reset in 2026-07, when
# the prior strategy corpus was abandoned. Not an "unseen data" line: the
# 2025-06..2026-07 slice was observed by the abandoned program (see module
# docstring), so validation there is robustness-grade, not untouched OOS.
FORWARD_FREEZE = "2025-06-01"

DEFAULT_AUDIT_PATH = Path("reports/holdout_access.jsonl")


class ProtocolError(Exception):
    """A research rule was broken."""


def to_ms(date: str) -> int:
    parsed = dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=dt.UTC)
    return int(parsed.timestamp() * 1000)


def from_ms(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class Segment:
    """One named span of the timeline."""

    name: str
    start: str
    end: str
    role: str = "explore"  # explore | holdout

    def __post_init__(self) -> None:
        if to_ms(self.end) <= to_ms(self.start):
            raise ProtocolError(f"segment {self.name}: end must be after start")
        if self.role not in ("explore", "holdout"):
            raise ProtocolError(f"segment {self.name}: unknown role {self.role!r}")

    @property
    def start_ms(self) -> int:
        return to_ms(self.start)

    @property
    def end_ms(self) -> int:
        return to_ms(self.end)

    @property
    def is_peeked(self) -> bool:
        """Whether this span predates the freeze and has therefore been seen."""
        return self.start_ms < to_ms(FORWARD_FREEZE)

    def contains(self, ts_ms: int) -> bool:
        return self.start_ms <= ts_ms < self.end_ms


@dataclass(frozen=True)
class SplitPlan:
    """A named, fingerprinted set of segments."""

    study: str
    segments: tuple[Segment, ...]
    freeze_point: str = FORWARD_FREEZE

    def __post_init__(self) -> None:
        names = [s.name for s in self.segments]
        if len(names) != len(set(names)):
            raise ProtocolError(f"duplicate segment names in {self.study}")
        ordered = sorted(self.segments, key=lambda s: s.start_ms)
        for earlier, later in itertools.pairwise(ordered):
            if later.start_ms < earlier.end_ms:
                raise ProtocolError(
                    f"{self.study}: segments {earlier.name} and {later.name} overlap; "
                    f"a bar in two segments is trained on and tested on at once"
                )

    @property
    def fingerprint(self) -> str:
        """Stable hash of the boundaries.

        Recorded in every report so a study that moved its own split shows up
        as a different fingerprint rather than as a better result.
        """
        payload = json.dumps(
            {
                "study": self.study,
                "freeze_point": self.freeze_point,
                "segments": [asdict(s) for s in sorted(self.segments, key=lambda s: s.name)],
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def segment(self, name: str) -> Segment:
        for candidate in self.segments:
            if candidate.name == name:
                return candidate
        available = [s.name for s in self.segments]
        raise KeyError(f"{self.study} has no segment {name!r}; has {available}")

    @property
    def has_genuine_holdout(self) -> bool:
        """True only if some segment starts after the freeze point."""
        return any(not s.is_peeked for s in self.segments)

    def warnings(self) -> list[str]:
        """What this plan cannot claim, stated plainly."""
        notes: list[str] = []
        peeked = [s.name for s in self.segments if s.is_peeked]
        if peeked:
            notes.append(
                f"segments {peeked} start before the {self.freeze_point} freeze and have "
                f"already been searched over; results there are hypotheses, not evidence"
            )
        if not self.has_genuine_holdout:
            notes.append(
                "this plan has no post-freeze segment, so it cannot adjudicate anything; "
                "real out-of-sample evidence can only come from data arriving after "
                f"{self.freeze_point}"
            )
        return notes


def forward_holdout(study: str, end: str | None = None) -> SplitPlan:
    """The validation split: the holdout window from the freeze to `end`."""
    end = end or dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    if to_ms(end) <= to_ms(FORWARD_FREEZE):
        raise ProtocolError(
            f"no out-of-sample data exists yet: the freeze is {FORWARD_FREEZE} and "
            f"the requested end is {end}. This is expected early on — the clock "
            f"starts at the freeze and cannot be hurried."
        )
    return SplitPlan(
        study=study,
        segments=(Segment("forward", FORWARD_FREEZE, end, role="holdout"),),
    )


def record_holdout_access(
    study: str,
    segment: str,
    hypothesis: str,
    fingerprint: str,
    path: Path | str = DEFAULT_AUDIT_PATH,
) -> None:
    """Append a holdout read to the audit log.

    Required before touching a holdout: the count of how many times a
    holdout has been consulted is itself the multiple-testing correction, and
    a peek nobody wrote down cannot be corrected for.
    """
    if not hypothesis.strip():
        raise ProtocolError(
            "a holdout read must state the hypothesis it tests, before the result "
            "is known; otherwise the hypothesis gets written afterwards to fit"
        )
    entry = {
        "at": dt.datetime.now(dt.UTC).isoformat(),
        "study": study,
        "segment": segment,
        "hypothesis": hypothesis,
        "split_fingerprint": fingerprint,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def holdout_access_count(
    study: str, path: Path | str = DEFAULT_AUDIT_PATH
) -> int:
    """How many times this study has already consulted a holdout."""
    target = Path(path)
    if not target.exists():
        return 0
    count = 0
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if json.loads(line).get("study") == study:
            count += 1
    return count
