"""Data models for CryptoQuant platform.

Defines dataclasses for OHLCV candles, tickers, and order book data.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from decimal import Decimal


@dataclass(frozen=True)
class OHLCVCandle:
    """OHLCV candlestick data.

    Attributes:
        timestamp: Unix timestamp in milliseconds
        open_price: Opening price
        high_price: Highest price during the period
        low_price: Lowest price during the period
        close_price: Closing price
        volume: Trading volume
        pair: Trading pair symbol (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "1h", "1d")
    """
    timestamp: int
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    pair: str
    timeframe: str

    @property
    def datetime(self) -> datetime:
        """Convert timestamp to datetime object."""
        return datetime.fromtimestamp(self.timestamp / 1000)

    @property
    def price_range(self) -> Decimal:
        """Calculate price range (high - low)."""
        return self.high_price - self.low_price

    @property
    def price_change(self) -> Decimal:
        """Calculate price change (close - open)."""
        return self.close_price - self.open_price

    @property
    def price_change_pct(self) -> Decimal:
        """Calculate price change percentage."""
        if self.open_price == 0:
            return Decimal('0')
        return (self.price_change / self.open_price) * 100


@dataclass(frozen=True)
class Ticker:
    """Real-time ticker data.

    Attributes:
        pair: Trading pair symbol
        bid: Best bid price
        ask: Best ask price
        last: Last traded price
        high: 24h high price
        low: 24h low price
        volume: 24h trading volume
        timestamp: Unix timestamp in milliseconds
    """
    pair: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    high: Decimal
    low: Decimal
    volume: Decimal
    timestamp: int

    @property
    def datetime(self) -> datetime:
        """Convert timestamp to datetime object."""
        return datetime.fromtimestamp(self.timestamp / 1000)

    @property
    def spread(self) -> Decimal:
        """Calculate bid-ask spread."""
        return self.ask - self.bid

    @property
    def spread_pct(self) -> Decimal:
        """Calculate spread as percentage of mid price."""
        mid = (self.bid + self.ask) / 2
        if mid == 0:
            return Decimal('0')
        return (self.spread / mid) * 100

    @property
    def mid_price(self) -> Decimal:
        """Calculate mid price between bid and ask."""
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class OrderBookLevel:
    """Single level in the order book.

    Attributes:
        price: Price level
        size: Amount available at this price
    """
    price: Decimal
    size: Decimal


@dataclass
class OrderBook:
    """Order book data (market depth).

    Attributes:
        pair: Trading pair symbol
        bids: List of bid levels (highest to lowest price)
        asks: List of ask levels (lowest to highest price)
        timestamp: Unix timestamp in milliseconds
    """
    pair: str
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    timestamp: int

    @property
    def datetime(self) -> datetime:
        """Convert timestamp to datetime object."""
        return datetime.fromtimestamp(self.timestamp / 1000)

    @property
    def best_bid(self) -> Optional[OrderBookLevel]:
        """Get best (highest) bid level."""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[OrderBookLevel]:
        """Get best (lowest) ask level."""
        return self.asks[0] if self.asks else None

    @property
    def spread(self) -> Optional[Decimal]:
        """Calculate bid-ask spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None

    @property
    def mid_price(self) -> Optional[Decimal]:
        """Calculate mid price."""
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2
        return None

    def get_bid_depth(self, depth_pct: Decimal = Decimal('0.01')) -> Decimal:
        """Calculate total bid volume within depth_pct of best bid.

        Args:
            depth_pct: Percentage depth from best bid (default 1%)

        Returns:
            Total bid volume within the depth range
        """
        if not self.best_bid:
            return Decimal('0')

        min_price = self.best_bid.price * (1 - depth_pct)
        total = Decimal('0')
        for bid in self.bids:
            if bid.price >= min_price:
                total += bid.size
            else:
                break
        return total

    def get_ask_depth(self, depth_pct: Decimal = Decimal('0.01')) -> Decimal:
        """Calculate total ask volume within depth_pct of best ask.

        Args:
            depth_pct: Percentage depth from best ask (default 1%)

        Returns:
            Total ask volume within the depth range
        """
        if not self.best_ask:
            return Decimal('0')

        max_price = self.best_ask.price * (1 + depth_pct)
        total = Decimal('0')
        for ask in self.asks:
            if ask.price <= max_price:
                total += ask.size
            else:
                break
        return total


@dataclass
class Balance:
    """Account balance information.

    Attributes:
        currency: Currency code (e.g., "BTC", "USDT")
        free: Available balance
        used: Balance locked in orders
        total: Total balance (free + used)
    """
    currency: str
    free: Decimal
    used: Decimal
    total: Decimal


@dataclass
class AccountBalance:
    """Complete account balance across all currencies.

    Attributes:
        balances: Dict of currency to Balance
        timestamp: Unix timestamp in milliseconds
    """
    balances: Dict[str, Balance] = field(default_factory=dict)
    timestamp: int = 0

    def get(self, currency: str) -> Optional[Balance]:
        """Get balance for specific currency."""
        return self.balances.get(currency)

    @property
    def total_usd_value(self) -> Decimal:
        """Calculate total portfolio value in USD.

        Note: This requires current market prices. For accurate
        calculation, use the Risk Manager which has price data.
        """
        return sum(b.total for b in self.balances.values())

    def get_non_zero_balances(self) -> Dict[str, Balance]:
        """Get only currencies with non-zero balances."""
        return {
            currency: balance
            for currency, balance in self.balances.items()
            if balance.total > 0
        }
