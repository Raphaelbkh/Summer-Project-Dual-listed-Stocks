"""Executable spread calculation using tradable bid/ask prices only."""

from datetime import datetime

from src.data.live.quote_models import EquityQuote, FXQuote, SpreadSnapshot
from src.utils.time_utils import is_stale, utc_now


MISSING_LONG_ASK = "MISSING_LONG_ASK"
MISSING_SHORT_BID = "MISSING_SHORT_BID"
STALE_LONG_QUOTE = "STALE_LONG_QUOTE"
STALE_SHORT_QUOTE = "STALE_SHORT_QUOTE"
FX_REQUIRED_BUT_MISSING = "FX_REQUIRED_BUT_MISSING"
FX_INVALID = "FX_INVALID"
FX_STALE = "FX_STALE"
INVALID_CONVERSION_RATIO = "INVALID_CONVERSION_RATIO"
NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
NET_EDGE_BELOW_THRESHOLD = "NET_EDGE_BELOW_THRESHOLD"


def _snapshot(
    *,
    pair_id: str,
    long_quote: EquityQuote,
    short_quote: EquityQuote,
    fx_quote: FXQuote | None,
    timestamp: datetime,
    cost_buffer_bps: float,
    gross_edge: float | None = None,
    net_edge: float | None = None,
    signal: bool = False,
    rejection_reason: str | None = None,
) -> SpreadSnapshot:
    return SpreadSnapshot(
        timestamp=timestamp,
        pair_id=pair_id,
        long_leg_symbol=long_quote.symbol,
        short_leg_symbol=short_quote.symbol,
        long_leg_exchange=long_quote.exchange,
        short_leg_exchange=short_quote.exchange,
        long_leg_currency=long_quote.currency,
        short_leg_currency=short_quote.currency,
        long_leg_ask=long_quote.ask,
        short_leg_bid=short_quote.bid,
        fx_pair=fx_quote.pair if fx_quote is not None else None,
        fx_bid=fx_quote.bid if fx_quote is not None else None,
        fx_ask=fx_quote.ask if fx_quote is not None else None,
        gross_edge=gross_edge,
        cost_buffer_bps=cost_buffer_bps,
        net_edge=net_edge,
        signal=signal,
        rejection_reason=rejection_reason,
    )


def _converted_short_bid_to_long_currency(
    short_bid: float,
    short_currency: str,
    long_currency: str,
    fx_quote: FXQuote,
) -> float | None:
    short_currency = short_currency.upper()
    long_currency = long_currency.upper()
    base_currency = fx_quote.base_currency.upper()
    quote_currency = fx_quote.quote_currency.upper()

    if short_currency == base_currency and long_currency == quote_currency:
        return short_bid * fx_quote.bid
    if short_currency == quote_currency and long_currency == base_currency:
        return short_bid / fx_quote.ask
    return None


def calculate_executable_spread(
    pair_id: str,
    long_quote: EquityQuote,
    short_quote: EquityQuote,
    fx_quote: FXQuote | None = None,
    conversion_ratio: float = 1.0,
    cost_buffer_bps: float = 20.0,
    min_required_net_edge_bps: float = 30.0,
    max_equity_quote_age_seconds: float = 5.0,
    max_fx_quote_age_seconds: float = 5.0,
    now: datetime | None = None,
) -> SpreadSnapshot:
    """Calculate executable spread after bid/ask FX and cost buffer."""
    timestamp = now if now is not None else utc_now()

    if conversion_ratio <= 0:
        return _snapshot(
            pair_id=pair_id,
            long_quote=long_quote,
            short_quote=short_quote,
            fx_quote=fx_quote,
            timestamp=timestamp,
            cost_buffer_bps=cost_buffer_bps,
            rejection_reason=INVALID_CONVERSION_RATIO,
        )
    if long_quote.ask is None:
        return _snapshot(
            pair_id=pair_id,
            long_quote=long_quote,
            short_quote=short_quote,
            fx_quote=fx_quote,
            timestamp=timestamp,
            cost_buffer_bps=cost_buffer_bps,
            rejection_reason=MISSING_LONG_ASK,
        )
    if short_quote.bid is None:
        return _snapshot(
            pair_id=pair_id,
            long_quote=long_quote,
            short_quote=short_quote,
            fx_quote=fx_quote,
            timestamp=timestamp,
            cost_buffer_bps=cost_buffer_bps,
            rejection_reason=MISSING_SHORT_BID,
        )
    if long_quote.ask <= 0 or short_quote.bid <= 0:
        return _snapshot(
            pair_id=pair_id,
            long_quote=long_quote,
            short_quote=short_quote,
            fx_quote=fx_quote,
            timestamp=timestamp,
            cost_buffer_bps=cost_buffer_bps,
            rejection_reason=NON_POSITIVE_PRICE,
        )
    if is_stale(long_quote.timestamp, max_equity_quote_age_seconds, now=timestamp):
        return _snapshot(
            pair_id=pair_id,
            long_quote=long_quote,
            short_quote=short_quote,
            fx_quote=fx_quote,
            timestamp=timestamp,
            cost_buffer_bps=cost_buffer_bps,
            rejection_reason=STALE_LONG_QUOTE,
        )
    if is_stale(short_quote.timestamp, max_equity_quote_age_seconds, now=timestamp):
        return _snapshot(
            pair_id=pair_id,
            long_quote=long_quote,
            short_quote=short_quote,
            fx_quote=fx_quote,
            timestamp=timestamp,
            cost_buffer_bps=cost_buffer_bps,
            rejection_reason=STALE_SHORT_QUOTE,
        )

    if long_quote.currency.upper() == short_quote.currency.upper():
        short_value_in_long_currency = short_quote.bid
    else:
        if fx_quote is None:
            return _snapshot(
                pair_id=pair_id,
                long_quote=long_quote,
                short_quote=short_quote,
                fx_quote=fx_quote,
                timestamp=timestamp,
                cost_buffer_bps=cost_buffer_bps,
                rejection_reason=FX_REQUIRED_BUT_MISSING,
            )
        if not fx_quote.is_valid:
            return _snapshot(
                pair_id=pair_id,
                long_quote=long_quote,
                short_quote=short_quote,
                fx_quote=fx_quote,
                timestamp=timestamp,
                cost_buffer_bps=cost_buffer_bps,
                rejection_reason=FX_INVALID,
            )
        if is_stale(fx_quote.timestamp, max_fx_quote_age_seconds, now=timestamp):
            return _snapshot(
                pair_id=pair_id,
                long_quote=long_quote,
                short_quote=short_quote,
                fx_quote=fx_quote,
                timestamp=timestamp,
                cost_buffer_bps=cost_buffer_bps,
                rejection_reason=FX_STALE,
            )

        short_value_in_long_currency = _converted_short_bid_to_long_currency(
            short_quote.bid,
            short_quote.currency,
            long_quote.currency,
            fx_quote,
        )
        if short_value_in_long_currency is None:
            return _snapshot(
                pair_id=pair_id,
                long_quote=long_quote,
                short_quote=short_quote,
                fx_quote=fx_quote,
                timestamp=timestamp,
                cost_buffer_bps=cost_buffer_bps,
                rejection_reason=FX_INVALID,
            )

    executable_sell_value = short_value_in_long_currency * conversion_ratio
    executable_buy_cost = long_quote.ask
    gross_edge = (executable_sell_value - executable_buy_cost) / executable_buy_cost
    net_edge = gross_edge - cost_buffer_bps / 10000
    threshold = min_required_net_edge_bps / 10000
    signal = net_edge > threshold

    return _snapshot(
        pair_id=pair_id,
        long_quote=long_quote,
        short_quote=short_quote,
        fx_quote=fx_quote,
        timestamp=timestamp,
        cost_buffer_bps=cost_buffer_bps,
        gross_edge=gross_edge,
        net_edge=net_edge,
        signal=signal,
        rejection_reason=None if signal else NET_EDGE_BELOW_THRESHOLD,
    )
