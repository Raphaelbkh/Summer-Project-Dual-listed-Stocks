from datetime import datetime, timedelta, timezone

import pytest

from src.data.live.quote_models import EquityQuote, FXQuote
from src.signal.executable_spread import (
    FX_INVALID,
    FX_REQUIRED_BUT_MISSING,
    FX_STALE,
    INVALID_CONVERSION_RATIO,
    MISSING_LONG_ASK,
    MISSING_SHORT_BID,
    NET_EDGE_BELOW_THRESHOLD,
    NON_POSITIVE_PRICE,
    STALE_LONG_QUOTE,
    STALE_SHORT_QUOTE,
    calculate_executable_spread,
)


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def equity_quote(**overrides: object) -> EquityQuote:
    values = {
        "symbol": "ABC",
        "exchange": "NASDAQ STOCKHOLM",
        "currency": "SEK",
        "bid": 99.0,
        "ask": 100.0,
        "bid_size": 100.0,
        "ask_size": 100.0,
        "last": 999999.0,
        "timestamp": NOW,
    }
    values.update(overrides)
    return EquityQuote(**values)


def fx_quote(**overrides: object) -> FXQuote:
    values = {
        "pair": "EURSEK",
        "base_currency": "EUR",
        "quote_currency": "SEK",
        "bid": 11.0,
        "ask": 11.1,
        "last": 999999.0,
        "timestamp": NOW,
    }
    values.update(overrides)
    return FXQuote(**values)


def test_same_currency_spread_does_not_require_fx() -> None:
    snapshot = calculate_executable_spread(
        "PAIR",
        equity_quote(ask=100.0, currency="SEK"),
        equity_quote(bid=105.0, currency="SEK"),
        fx_quote=None,
        cost_buffer_bps=20,
        min_required_net_edge_bps=30,
        now=NOW,
    )

    assert snapshot.gross_edge == pytest.approx(0.05)
    assert snapshot.net_edge == pytest.approx(0.048)
    assert snapshot.signal is True
    assert snapshot.rejection_reason is None


def test_missing_long_ask_rejects() -> None:
    snapshot = calculate_executable_spread(
        "PAIR",
        equity_quote(ask=None),
        equity_quote(),
        now=NOW,
    )

    assert snapshot.signal is False
    assert snapshot.rejection_reason == MISSING_LONG_ASK


def test_missing_short_bid_rejects() -> None:
    snapshot = calculate_executable_spread(
        "PAIR",
        equity_quote(),
        equity_quote(bid=None),
        now=NOW,
    )

    assert snapshot.signal is False
    assert snapshot.rejection_reason == MISSING_SHORT_BID


def test_non_positive_price_rejects() -> None:
    snapshot = calculate_executable_spread(
        "PAIR",
        equity_quote(ask=0.0),
        equity_quote(),
        now=NOW,
    )

    assert snapshot.rejection_reason == NON_POSITIVE_PRICE


def test_stale_long_quote_rejects() -> None:
    snapshot = calculate_executable_spread(
        "PAIR",
        equity_quote(timestamp=NOW - timedelta(seconds=6)),
        equity_quote(),
        max_equity_quote_age_seconds=5,
        now=NOW,
    )

    assert snapshot.rejection_reason == STALE_LONG_QUOTE


def test_stale_short_quote_rejects() -> None:
    snapshot = calculate_executable_spread(
        "PAIR",
        equity_quote(),
        equity_quote(timestamp=NOW - timedelta(seconds=6)),
        max_equity_quote_age_seconds=5,
        now=NOW,
    )

    assert snapshot.rejection_reason == STALE_SHORT_QUOTE


def test_different_currency_without_fx_rejects() -> None:
    snapshot = calculate_executable_spread(
        "PAIR",
        equity_quote(currency="SEK"),
        equity_quote(currency="EUR"),
        fx_quote=None,
        now=NOW,
    )

    assert snapshot.rejection_reason == FX_REQUIRED_BUT_MISSING


def test_invalid_fx_rejects() -> None:
    snapshot = calculate_executable_spread(
        "PAIR",
        equity_quote(currency="SEK"),
        equity_quote(currency="EUR"),
        fx_quote=fx_quote(bid=None),
        now=NOW,
    )

    assert snapshot.rejection_reason == FX_INVALID


def test_stale_fx_rejects() -> None:
    snapshot = calculate_executable_spread(
        "PAIR",
        equity_quote(currency="SEK"),
        equity_quote(currency="EUR"),
        fx_quote=fx_quote(timestamp=NOW - timedelta(seconds=6)),
        max_fx_quote_age_seconds=5,
        now=NOW,
    )

    assert snapshot.rejection_reason == FX_STALE


def test_invalid_conversion_ratio_rejects() -> None:
    snapshot = calculate_executable_spread(
        "PAIR",
        equity_quote(),
        equity_quote(),
        conversion_ratio=0,
        now=NOW,
    )

    assert snapshot.rejection_reason == INVALID_CONVERSION_RATIO


def test_cost_buffer_deducted_correctly() -> None:
    snapshot = calculate_executable_spread(
        "PAIR",
        equity_quote(ask=100.0, currency="SEK"),
        equity_quote(bid=105.0, currency="SEK"),
        cost_buffer_bps=25,
        min_required_net_edge_bps=1,
        now=NOW,
    )

    assert snapshot.gross_edge == pytest.approx(0.05)
    assert snapshot.net_edge == pytest.approx(0.0475)


def test_signal_true_only_above_threshold() -> None:
    above = calculate_executable_spread(
        "PAIR",
        equity_quote(ask=100.0, currency="SEK"),
        equity_quote(bid=101.0, currency="SEK"),
        cost_buffer_bps=20,
        min_required_net_edge_bps=30,
        now=NOW,
    )
    below = calculate_executable_spread(
        "PAIR",
        equity_quote(ask=100.0, currency="SEK"),
        equity_quote(bid=100.5, currency="SEK"),
        cost_buffer_bps=20,
        min_required_net_edge_bps=30,
        now=NOW,
    )

    assert above.signal is True
    assert above.rejection_reason is None
    assert below.signal is False
    assert below.rejection_reason == NET_EDGE_BELOW_THRESHOLD


def test_last_and_mid_are_not_used_in_calculation() -> None:
    long_quote = equity_quote(
        currency="SEK",
        bid=1.0,
        ask=100.0,
        last=1_000_000.0,
    )
    short_quote = equity_quote(
        currency="EUR",
        bid=10.0,
        ask=1_000_000.0,
        last=1_000_000.0,
    )
    snapshot = calculate_executable_spread(
        "PAIR",
        long_quote,
        short_quote,
        fx_quote=fx_quote(bid=11.0, ask=1000.0, last=1_000_000.0),
        cost_buffer_bps=0,
        min_required_net_edge_bps=1,
        now=NOW,
    )

    assert snapshot.gross_edge == pytest.approx(0.10)
    assert snapshot.signal is True
