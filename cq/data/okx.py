"""OKX public-endpoint client.

Only public market data is touched here — no credentials are read, so this
module can never place an order.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import ccxt
from loguru import logger

# OKX rejects the default `python-requests` user agent with HTTP 403.
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

RETRYABLE = (
    ccxt.NetworkError,
    ccxt.RequestTimeout,
    ccxt.ExchangeNotAvailable,
    ccxt.DDoSProtection,
)


class OkxPublicClient:
    """ccxt-backed OKX client for public endpoints, with retries.

    Calls ccxt's implicit (raw endpoint) methods with OKX-native instrument
    ids such as ``DOGE-USDT-SWAP``, rather than the unified ``fetch_*`` API,
    because:

    * the archive is keyed by native id, and the open-interest endpoint is
      keyed by currency with no unified equivalent at all;
    * unified ``fetch_funding_rate_history`` returns only symbol/rate/time and
      pushes ``realizedRate`` into ``info``, so the raw payload gets parsed
      either way;
    * implicit calls skip ``load_markets()``, which costs ~10s and 4k markets
      that a nightly archiver has no use for.

    ``load_markets()`` itself works fine once the proxy issue below is fixed —
    it is skipped as an unnecessary cost, not because it fails.
    """

    def __init__(
        self,
        timeout_ms: int = 30_000,
        max_retries: int = 5,
        backoff_base_s: float = 1.0,
        trust_env: bool = True,
    ):
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self._ex = ccxt.okx({"enableRateLimit": True, "timeout": timeout_ms})
        # ccxt sets `trust_env = False` on its session, which makes requests
        # ignore HTTPS_PROXY. On a network that can only reach OKX through a
        # proxy that turns every call into a connect timeout.
        session = self._ex.session
        if session is None:  # pragma: no cover - ccxt always builds one
            raise RuntimeError("ccxt did not create a requests session to configure")
        session.trust_env = trust_env
        self._ex.headers = {"User-Agent": BROWSER_UA}

    @property
    def exchange(self) -> ccxt.okx:
        return self._ex

    def milliseconds(self) -> int:
        return self._ex.milliseconds()

    def _call(self, fn: Callable[..., Any], params: dict[str, str]) -> list:
        """Invoke an OKX endpoint, retrying transient failures."""
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = fn(params)
            except RETRYABLE as exc:
                last = exc
                delay = self.backoff_base_s * (2**attempt)
                logger.warning(
                    "OKX call failed ({}), retry {}/{} in {:.1f}s: {}",
                    type(exc).__name__,
                    attempt + 1,
                    self.max_retries,
                    delay,
                    params,
                )
                time.sleep(delay)
                continue
            return response.get("data", [])
        if last is None:
            # Only reachable with max_retries <= 0, i.e. a misconfiguration.
            raise RuntimeError(f"no attempt was made for {params}: max_retries={self.max_retries}")
        raise last

    # ---- endpoints ----------------------------------------------------

    def funding_rate_history(
        self, inst_id: str, before_ts: int | None = None, limit: int = 100
    ) -> list[dict]:
        """One page of funding settlements, newest first.

        ``before_ts`` pages *backwards*: OKX returns settlements strictly
        older than it (the parameter is named ``after`` in their API, which
        reads backwards from how it behaves).
        """
        params = {"instId": inst_id, "limit": str(limit)}
        if before_ts is not None:
            params["after"] = str(before_ts)
        return self._call(self._ex.publicGetPublicFundingRateHistory, params)

    def open_interest_volume(self, ccy: str, period: str = "1H") -> list[list]:
        """Open interest and volume history for a currency, newest first.

        Rows are ``[ts, oi_usd, volume_usd]``. OKX serves ~30 days.
        """
        return self._call(
            self._ex.publicGetRubikStatContractsOpenInterestVolume,
            {"ccy": ccy, "period": period},
        )

    def history_candles(
        self, inst_id: str, bar: str = "1H", before_ts: int | None = None, limit: int = 100
    ) -> list[list]:
        """One page of closed candles, newest first.

        Rows are ``[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]``.
        """
        params = {"instId": inst_id, "bar": bar, "limit": str(limit)}
        if before_ts is not None:
            params["after"] = str(before_ts)
        return self._call(self._ex.publicGetMarketHistoryCandles, params)
