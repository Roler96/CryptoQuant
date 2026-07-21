"""Live and paper execution.

Everything that can place an order lives here, kept apart from `cq.data`, whose
`OkxPublicClient` touches only public endpoints and promises never to trade. The
loop that drives a paper session reuses the backtest engine's sizing and the
same closed-bar `LiveFeed`, so a paper run cannot be more optimistic than the
backtest that vetted the strategy — there is no second execution model to drift
from.
"""

from __future__ import annotations
