"""Pure quote and spread snapshot data models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class EquityQuote:
    symbol: str
    exchange: str
    currency: str
    bid: float | None
    ask: float | None
    bid_size: float | None
    ask_size: float | None
    last: float | None
    timestamp: datetime
    source: str = "IBKR"
    contract_id: int | None = None

    @property
    def is_valid(self) -> bool:
        """Return True when bid/ask are usable executable prices."""
        return (
            self.bid is not None
            and self.ask is not None
            and self.bid > 0
            and self.ask > 0
            and self.ask >= self.bid
        )

    @property
    def mid(self) -> float | None:
        """Return the bid/ask midpoint for valid quotes."""
        if not self.is_valid:
            return None
        return (self.bid + self.ask) / 2

    @property
    def spread_pct(self) -> float | None:
        """Return bid/ask spread as a fraction of midpoint."""
        mid = self.mid
        if mid is None:
            return None
        return (self.ask - self.bid) / mid


@dataclass
class FXQuote:
    pair: str
    base_currency: str
    quote_currency: str
    bid: float | None
    ask: float | None
    last: float | None
    timestamp: datetime
    source: str = "IBKR_IDEALPRO"

    @property
    def is_valid(self) -> bool:
        """Return True when bid/ask are usable executable FX prices."""
        return (
            self.bid is not None
            and self.ask is not None
            and self.bid > 0
            and self.ask > 0
            and self.ask >= self.bid
        )

    @property
    def mid(self) -> float | None:
        """Return the bid/ask midpoint for valid quotes."""
        if not self.is_valid:
            return None
        return (self.bid + self.ask) / 2

    @property
    def spread_pct(self) -> float | None:
        """Return bid/ask spread as a fraction of midpoint."""
        mid = self.mid
        if mid is None:
            return None
        return (self.ask - self.bid) / mid


@dataclass
class SpreadSnapshot:
    timestamp: datetime
    pair_id: str
    long_leg_symbol: str
    short_leg_symbol: str
    long_leg_exchange: str
    short_leg_exchange: str
    long_leg_currency: str
    short_leg_currency: str
    long_leg_ask: float | None
    short_leg_bid: float | None
    fx_pair: str | None
    fx_bid: float | None
    fx_ask: float | None
    gross_edge: float | None
    cost_buffer_bps: float
    net_edge: float | None
    signal: bool
    rejection_reason: str | None
