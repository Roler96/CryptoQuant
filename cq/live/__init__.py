"""Live and paper execution.

Everything that can place an order lives here, kept apart from `cq.data`, whose
`OkxPublicClient` touches only public endpoints and promises never to trade.
Paper/live supplies `LiveEngineFeed` and the OKX broker adapter to the same
`run_event_loop` used by backtests. Venue execution remains deliberately
different from simulation and is checked by the calibration protocol.
"""

from __future__ import annotations
