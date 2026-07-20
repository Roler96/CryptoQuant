"""The set of instruments the platform tracks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# The default set, shipped inside the wheel. It lives in the package rather
# than at the repository root because `cq` is installable: a path relative to
# the working directory made every subcommand fail with a bare
# FileNotFoundError anywhere but the repository.
PACKAGED_UNIVERSE_PATH = Path(__file__).parent / "config" / "universe.yaml"

# An optional working-directory override, for running a different set of
# instruments without editing the package or passing --universe every time.
DEFAULT_UNIVERSE_PATH = Path("config/universe.yaml")


@dataclass(frozen=True)
class Universe:
    spot: tuple[str, ...]
    swap: tuple[str, ...]
    open_interest_currencies: tuple[str, ...]

    @property
    def all_instruments(self) -> tuple[str, ...]:
        return self.spot + self.swap

    def market_type(self, inst_id: str) -> str:
        if inst_id in self.swap:
            return "swap"
        if inst_id in self.spot:
            return "spot"
        raise KeyError(f"{inst_id} is not in the configured universe")


def load_universe(path: Path | str = DEFAULT_UNIVERSE_PATH) -> Universe:
    """Read a universe file, falling back to the packaged default.

    The fallback applies only to the default path: an explicit `--universe`
    that does not exist is an error, not an invitation to load something else.
    """
    target = Path(path)
    if target == DEFAULT_UNIVERSE_PATH and not target.exists():
        target = PACKAGED_UNIVERSE_PATH
    if not target.exists():
        raise FileNotFoundError(
            f"no universe file at {target}; pass --universe or create "
            f"{DEFAULT_UNIVERSE_PATH}"
        )
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return Universe(
        spot=tuple(raw.get("spot", ())),
        swap=tuple(raw.get("swap", ())),
        open_interest_currencies=tuple(raw.get("open_interest_currencies", ())),
    )
