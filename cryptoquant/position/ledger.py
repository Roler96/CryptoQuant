"""Managed Position Ledger — strategy position ownership and realized PnL.

Phase 2 module. Tracks every buy/sell the strategy executes, maintains FIFO
cost basis, and computes realized PnL correctly (exit_proceeds - entry_cost - fees).

Separated from Broker so:
- PaperBroker and real Broker share the same position tracking
- Realized PnL is computed from actual fill prices, not balance deltas
- Partial closes work correctly via FIFO lot consumption
- Spot and swap positions are tracked uniformly
"""

from dataclasses import dataclass


@dataclass
class Lot:
    """A single purchase lot consumed in FIFO order on sells."""

    amount: float       # base currency amount (e.g., BTC)
    price: float        # fill price per unit
    fee: float          # fee paid in quote currency
    timestamp: int      # unix ms when filled
    symbol: str = ""    # for multi-symbol tracking


@dataclass
class ClosedTrade:
    """A completed round-trip trade with realized PnL."""

    symbol: str
    side: str               # "long" or "short"
    amount: float           # total base amount closed
    entry_price: float      # volume-weighted average entry
    exit_price: float       # fill price
    entry_fee: float        # total fees paid on entry
    exit_fee: float         # fees paid on exit
    realized_pnl: float     # exit_proceeds - entry_cost - fees (quote currency)
    realized_pnl_pct: float # percentage return
    entry_time: int         # unix ms
    exit_time: int          # unix ms
    exit_reason: str = ""


@dataclass
class PositionSnapshot:
    """Current strategy-owned position snapshot."""

    symbol: str
    side: str               # "long" or "short"
    amount: float           # total base amount held
    avg_entry_price: float  # volume-weighted average entry
    total_fees: float       # cumulative entry fees
    timestamp: int          # unix ms of last update

    @property
    def cost_basis(self) -> float:
        """Total cost including fees."""
        return self.amount * self.avg_entry_price + self.total_fees

    @property
    def is_open(self) -> bool:
        return self.amount > 0


class ManagedPositionLedger:
    """Tracks strategy-owned positions with FIFO cost basis and realized PnL.

    Usage:
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, fee=5.0, ts=...)
        trade = ledger.record_sell("BTC/USDT", 0.1, 51000.0, fee=5.0, ts=...,
                                   exit_reason="take_profit")
        assert trade.realized_pnl > 0
    """

    def __init__(self):
        self._lots: dict[str, list[Lot]] = {}         # symbol → FIFO queue
        self._closed: list[ClosedTrade] = []

    # ── Recording ───────────────────────────────────────────────────────

    def record_buy(
        self,
        symbol: str,
        amount: float,
        price: float,
        fee: float = 0.0,
        timestamp: int = 0,
    ) -> None:
        """Record a buy order fill. Adds a FIFO lot."""
        if amount <= 0:
            raise ValueError(f"Buy amount must be positive, got {amount}")
        if price <= 0:
            raise ValueError(f"Buy price must be positive, got {price}")
        if fee < 0:
            raise ValueError(f"Buy fee cannot be negative, got {fee}")
        lot = Lot(
            amount=amount,
            price=price,
            fee=fee,
            timestamp=timestamp,
            symbol=symbol,
        )
        self._lots.setdefault(symbol, []).append(lot)

    def record_sell(
        self,
        symbol: str,
        amount: float,
        price: float,
        fee: float = 0.0,
        timestamp: int = 0,
        exit_reason: str = "",
    ) -> ClosedTrade:
        """Record a sell order fill. Consumes FIFO lots, returns PnL.

        Raises ValueError if trying to sell more than owned.
        """
        if amount <= 0:
            raise ValueError(f"Sell amount must be positive, got {amount}")
        if price <= 0:
            raise ValueError(f"Sell price must be positive, got {price}")
        if fee < 0:
            raise ValueError(f"Sell fee cannot be negative, got {fee}")

        lots = self._lots.get(symbol, [])
        total_held = sum(lot.amount for lot in lots)
        if total_held < amount:
            raise ValueError(
                f"Insufficient position: {total_held} < {amount} for {symbol}"
            )

        # Consume lots FIFO
        remaining = amount
        consumed: list[tuple[Lot, float]] = []  # (lot, consumed_amount)
        entry_cost = 0.0
        entry_fee = 0.0

        while remaining > 0 and lots:
            lot = lots[0]
            take = min(lot.amount, remaining)
            consumed.append((lot, take))
            entry_cost += take * lot.price
            # Prorate the lot's fee
            allocated_fee = (
                (take / lot.amount) * lot.fee if lot.amount > 0 else 0
            )
            entry_fee += allocated_fee
            lot.amount -= take
            lot.fee -= allocated_fee
            remaining -= take
            if lot.amount <= 0:
                lots.pop(0)

        # Clean up empty symbol entry
        if not lots:
            del self._lots[symbol]

        # Calculate PnL
        exit_proceeds = amount * price
        total_fees = entry_fee + fee
        realized_pnl = exit_proceeds - entry_cost - total_fees

        # Volume-weighted average entry price
        total_consumed = amount - remaining
        avg_entry = entry_cost / total_consumed if total_consumed > 0 else 0.0

        # Percentage PnL relative to entry cost + fees
        cost_basis_total = entry_cost + entry_fee
        realized_pnl_pct = (
            (realized_pnl / cost_basis_total * 100) if cost_basis_total > 0 else 0.0
        )

        # Use the earliest entry time among consumed lots
        entry_time = min(lot.timestamp for lot, _ in consumed) if consumed else 0

        trade = ClosedTrade(
            symbol=symbol,
            side="long",
            amount=amount,
            entry_price=round(avg_entry, 8),
            exit_price=price,
            entry_fee=round(entry_fee, 8),
            exit_fee=fee,
            realized_pnl=round(realized_pnl, 8),
            realized_pnl_pct=round(realized_pnl_pct, 6),
            entry_time=entry_time,
            exit_time=timestamp,
            exit_reason=exit_reason,
        )
        self._closed.append(trade)
        return trade

    # ── Queries ─────────────────────────────────────────────────────────

    def get_position(self, symbol: str) -> PositionSnapshot | None:
        """Return current strategy-owned position, or None if flat."""
        lots = self._lots.get(symbol, [])
        total = sum(lot.amount for lot in lots)
        if total <= 0:
            return None

        total_cost = sum(lot.amount * lot.price for lot in lots)
        avg_price = total_cost / total if total > 0 else 0.0
        total_fees = sum(lot.fee for lot in lots)
        latest_ts = max((lot.timestamp for lot in lots), default=0)

        return PositionSnapshot(
            symbol=symbol,
            side="long",
            amount=total,
            avg_entry_price=round(avg_price, 8),
            total_fees=round(total_fees, 8),
            timestamp=latest_ts,
        )

    def has_position(self, symbol: str) -> bool:
        """Check if any position is open for this symbol."""
        pos = self.get_position(symbol)
        return pos is not None and pos.amount > 0

    def get_total_held(self, symbol: str) -> float:
        """Total base amount held for symbol (0 if flat)."""
        pos = self.get_position(symbol)
        return pos.amount if pos else 0.0

    def get_realized_pnl(self, symbol: str | None = None) -> float:
        """Total realized PnL, optionally filtered by symbol."""
        trades = self._closed
        if symbol:
            trades = [t for t in trades if t.symbol == symbol]
        return sum(t.realized_pnl for t in trades)

    @property
    def closed_trades(self) -> list[ClosedTrade]:
        """All completed trades (read-only copy)."""
        return list(self._closed)

    @property
    def active_symbols(self) -> list[str]:
        """Symbols with open positions."""
        return [
            s
            for s, lots in self._lots.items()
            if sum(lot.amount for lot in lots) > 0
        ]

    # ── State serialization ─────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize to dict for state persistence."""
        return {
            "lots": {
                sym: [
                    {"amount": lot.amount, "price": lot.price, "fee": lot.fee,
                     "timestamp": lot.timestamp, "symbol": lot.symbol}
                    for lot in lots
                ]
                for sym, lots in self._lots.items()
            },
            "closed": [
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "amount": t.amount,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "entry_fee": t.entry_fee,
                    "exit_fee": t.exit_fee,
                    "realized_pnl": t.realized_pnl,
                    "realized_pnl_pct": t.realized_pnl_pct,
                    "entry_time": t.entry_time,
                    "exit_time": t.exit_time,
                    "exit_reason": t.exit_reason,
                }
                for t in self._closed
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ManagedPositionLedger":
        """Restore from serialized dict."""
        ledger = cls()
        for sym, lot_list in data.get("lots", {}).items():
            ledger._lots[sym] = [
                Lot(
                    amount=raw["amount"],
                    price=raw["price"],
                    fee=raw.get("fee", 0.0),
                    timestamp=raw.get("timestamp", 0),
                    symbol=raw.get("symbol", sym),
                )
                for raw in lot_list
            ]
        ledger._closed = [
            ClosedTrade(
                symbol=t["symbol"],
                side=t.get("side", "long"),
                amount=t["amount"],
                entry_price=t["entry_price"],
                exit_price=t["exit_price"],
                entry_fee=t.get("entry_fee", 0.0),
                exit_fee=t.get("exit_fee", 0.0),
                realized_pnl=t["realized_pnl"],
                realized_pnl_pct=t.get("realized_pnl_pct", 0.0),
                entry_time=t.get("entry_time", 0),
                exit_time=t.get("exit_time", 0),
                exit_reason=t.get("exit_reason", ""),
            )
            for t in data.get("closed", [])
        ]
        return ledger

    def restore(self, data: dict) -> None:
        """Repopulate this ledger in place from a serialized dict (see to_dict).

        Unlike from_dict, mutates the existing instance rather than creating
        a new one, so callers who already share this ledger by reference
        (Broker, ExecutionLifecycle) see the restored state.
        """
        restored = self.from_dict(data)
        self._lots = restored._lots
        self._closed = restored._closed
