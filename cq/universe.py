"""The set of instruments the platform tracks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

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
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return Universe(
        spot=tuple(raw.get("spot", ())),
        swap=tuple(raw.get("swap", ())),
        open_interest_currencies=tuple(raw.get("open_interest_currencies", ())),
    )
