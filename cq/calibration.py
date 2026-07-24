"""Fail-closed engine calibration verdicts.

A passing test suite is evidence of internal consistency, not an external
calibration.  Research output is therefore published only when a capability-
specific artifact proves that the current engine sources passed the frozen
paper-vs-backtest protocol.

Artifacts are deliberately bound to source content rather than only a git
commit: an uncommitted engine edit invalidates yesterday's calibration just as
surely as a committed one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Capability = Literal["spot", "swap"]
SizingMode = Literal["on_entry", "rebalance"]

SCHEMA_VERSION = 1
PROTOCOL_VERSION = "2026-07-24.2"
DEFAULT_ARTIFACT_DIR = Path("reports/calibration")
SPOT_REBALANCE_CHECKS = frozenset(
    {
        "decision_parity",
        "frozen_calibration_sequence",
        "accounting_consistency",
        "band_semantics",
        "event_coverage",
        "backtest_available",
        "backtest_complete",
    }
)
REQUIRED_CHECKS: dict[tuple[Capability, SizingMode], frozenset[str]] = {
    ("spot", "rebalance"): SPOT_REBALANCE_CHECKS,
}

# Every source whose behavior the spot paper-vs-backtest check speaks for.
# Swap remains a separate capability and cannot inherit a spot PASS.
CALIBRATION_INPUTS = (
    "cq/calibration.py",
    "cq/context.py",
    "cq/core",
    "cq/data/feed.py",
    "cq/data/protocols.py",
    "cq/data/resample.py",
    "cq/data/store.py",
    "cq/engine",
    "cq/live",
    "cq/strategy/doge_constant_mix.py",
    "cq/config/universe.yaml",
    "cq/universe.py",
    "scripts/reconcile_paper.py",
    "docs/engine_calibration_protocol.md",
)
HASHED_SUFFIXES = {".py", ".yaml", ".md"}


class CalibrationClosed(RuntimeError):
    """Research output was requested without a current passing calibration."""


@dataclass(frozen=True)
class GateStatus:
    capability: Capability
    sizing: SizingMode
    is_open: bool
    reason: str
    artifact_path: Path
    engine_fingerprint: str | None = None


def repository_root() -> Path:
    """The source checkout containing this module."""
    return Path(__file__).resolve().parent.parent


def default_artifact_path(capability: Capability, sizing: SizingMode) -> Path:
    return DEFAULT_ARTIFACT_DIR / f"{capability}_{sizing}.json"


def engine_fingerprint(root: Path | str | None = None) -> str:
    """Hash every frozen calibration input, failing if any is unavailable."""
    base = Path(root) if root is not None else repository_root()
    files: list[Path] = []
    missing: list[str] = []
    for relative in CALIBRATION_INPUTS:
        candidate = base / relative
        if candidate.is_file():
            files.append(candidate)
        elif candidate.is_dir():
            files.extend(
                path
                for path in candidate.rglob("*")
                if path.is_file()
                and path.suffix in HASHED_SUFFIXES
                and "__pycache__" not in path.parts
            )
        else:
            missing.append(relative)
    if missing:
        raise CalibrationClosed(
            "calibration inputs are unavailable: " + ", ".join(sorted(missing))
        )

    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(base).as_posix()):
        relative = path.relative_to(base).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_gate_artifact(
    capability: Capability,
    sizing: SizingMode,
    *,
    checks: Mapping[str, bool],
    evidence: Mapping[str, Any],
    source_sha256: str,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Build a verdict; a missing or false check can never produce PASS."""
    normalized_checks = {str(name): bool(value) for name, value in checks.items()}
    required = REQUIRED_CHECKS.get((capability, sizing))
    passed = (
        required is not None
        and required.issubset(normalized_checks)
        and all(normalized_checks[name] for name in required)
        and all(normalized_checks.values())
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "capability": capability,
        "sizing": sizing,
        "status": "PASS" if passed else "FAILED",
        "engine_fingerprint": engine_fingerprint(root),
        "source_sha256": source_sha256,
        "checks": normalized_checks,
        "evidence": dict(evidence),
    }


def write_gate_artifact(payload: Mapping[str, Any], path: Path | str) -> Path:
    """Atomically publish one machine-readable calibration verdict."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def calibration_status(
    capability: Capability,
    sizing: SizingMode,
    artifact_path: Path | str | None = None,
    *,
    root: Path | str | None = None,
) -> GateStatus:
    """Validate an artifact against the current protocol and source content."""
    path = (
        Path(artifact_path)
        if artifact_path is not None
        else default_artifact_path(capability, sizing)
    )
    required = REQUIRED_CHECKS.get((capability, sizing))
    if required is None:
        return GateStatus(
            capability,
            sizing,
            False,
            f"no calibration protocol is implemented for {capability}/{sizing}",
            path,
        )
    if not path.exists():
        return GateStatus(capability, sizing, False, f"missing artifact {path}", path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return GateStatus(capability, sizing, False, f"invalid artifact: {exc}", path)
    if not isinstance(payload, dict):
        return GateStatus(capability, sizing, False, "artifact root is not an object", path)

    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "capability": capability,
        "sizing": sizing,
        "status": "PASS",
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            return GateStatus(
                capability,
                sizing,
                False,
                f"artifact {field} is {payload.get(field)!r}, expected {value!r}",
                path,
            )

    checks = payload.get("checks")
    if (
        not isinstance(checks, dict)
        or not checks
        or not all(value is True for value in checks.values())
    ):
        return GateStatus(
            capability,
            sizing,
            False,
            "artifact contains a missing or failed check",
            path,
        )
    missing_checks = sorted(required - set(checks))
    if missing_checks:
        return GateStatus(
            capability,
            sizing,
            False,
            "artifact omits required checks: " + ", ".join(missing_checks),
            path,
        )
    source_sha256 = payload.get("source_sha256")
    if (
        not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source_sha256.lower())
    ):
        return GateStatus(
            capability,
            sizing,
            False,
            "artifact has no valid source SHA-256",
            path,
        )

    try:
        current = engine_fingerprint(root)
    except CalibrationClosed as exc:
        return GateStatus(capability, sizing, False, str(exc), path)
    recorded = payload.get("engine_fingerprint")
    if recorded != current:
        return GateStatus(
            capability,
            sizing,
            False,
            "engine sources changed after calibration",
            path,
            engine_fingerprint=current,
        )
    return GateStatus(
        capability,
        sizing,
        True,
        "current engine matches a passing calibration artifact",
        path,
        engine_fingerprint=current,
    )


def require_calibration(
    capability: Capability,
    sizing: SizingMode,
    artifact_path: Path | str | None = None,
    *,
    root: Path | str | None = None,
) -> GateStatus:
    status = calibration_status(capability, sizing, artifact_path, root=root)
    if not status.is_open:
        raise CalibrationClosed(
            f"{capability}/{sizing} calibration gate is CLOSED: {status.reason}"
        )
    return status


def register(subparsers: argparse._SubParsersAction) -> None:
    status = subparsers.add_parser("status", help="validate a calibration artifact")
    status.add_argument("--capability", choices=("spot", "swap"), default="spot")
    status.add_argument(
        "--sizing",
        choices=("on_entry", "rebalance"),
        default="rebalance",
    )
    status.add_argument(
        "--artifact",
        help="artifact path (default: reports/calibration/<capability>_<sizing>.json)",
    )
    status.set_defaults(handler=cmd_status)


def cmd_status(args: argparse.Namespace) -> int:
    capability: Capability = args.capability
    sizing: SizingMode = args.sizing
    status = calibration_status(capability, sizing, args.artifact)
    state = "OPEN" if status.is_open else "CLOSED"
    print(f"{capability}/{sizing} calibration gate: {state} — {status.reason}")
    print(f"artifact: {status.artifact_path}")
    if status.engine_fingerprint is not None:
        print(f"engine: {status.engine_fingerprint}")
    return 0 if status.is_open else 1
