"""Credentials for the trading endpoints.

Read from the environment (``.env`` is loaded on demand), never hard-coded, and
never logged. Demo and live keys are separate variables so that reaching for one
can never silently pick up the other: a paper session that fell back to the live
keys would trade real money while every label still said "paper".
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# OKX_SANDBOX_* are the demo-trading keys; OKX_* are the live ones. The suffixes
# match the layout already in .env.
_DEMO_PREFIX = "OKX_SANDBOX_"
_LIVE_PREFIX = "OKX_"
_SUFFIXES = ("API_KEY", "API_SECRET", "PASSPHRASE")


class CredentialsError(RuntimeError):
    """Raised when a required credential is absent or blank."""


@dataclass(frozen=True)
class OkxCredentials:
    """One authenticated identity — demo or live — for the OKX trade API."""

    api_key: str
    secret: str
    passphrase: str
    demo: bool

    @classmethod
    def from_env(
        cls, demo: bool = True, env_path: str | os.PathLike[str] | None = None
    ) -> OkxCredentials:
        """Load the demo (default) or live credentials from the environment.

        `.env` is loaded without overriding anything already exported, so a real
        environment variable still wins over the file. A missing or blank value
        is a hard error rather than a fall-through to the other identity.
        """
        load_dotenv(env_path, override=False)
        prefix = _DEMO_PREFIX if demo else _LIVE_PREFIX
        values = {suffix: os.getenv(f"{prefix}{suffix}", "").strip() for suffix in _SUFFIXES}
        missing = [f"{prefix}{suffix}" for suffix, value in values.items() if not value]
        if missing:
            identity = "demo" if demo else "live"
            raise CredentialsError(
                f"missing {identity} OKX credentials: {', '.join(missing)}; "
                f"set them in .env or the environment"
            )
        return cls(
            api_key=values["API_KEY"],
            secret=values["API_SECRET"],
            passphrase=values["PASSPHRASE"],
            demo=demo,
        )

    def __repr__(self) -> str:
        # A dataclass repr would print the secret; this one never does.
        identity = "demo" if self.demo else "live"
        return f"OkxCredentials({identity}, api_key=***{self.api_key[-4:]})"
