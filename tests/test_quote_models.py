from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from src.data.live.quote_models import EquityQuote, FXQuote, SpreadSnapshot


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_equity_quote(**overrides: object) -> EquityQuote:
    values = {
        "symbol": "ABC",
        "exchange": "SFB",
        "currency": "SEK",
        "bid": 100.0,
        "ask": 102.0,
        "bid_size": 10.0,
        "ask_size": 12.0,
        "last": 101.0,
        "timestamp": NOW,
    }
    values.update(overrides)
    return EquityQuote(**values)


def make_fx_quote(**overrides: object) -> FXQuote:
    values = {
        "pair": "EURSEK",
        "base_currency": "EUR",
        "quote_currency": "SEK",
        "bid": 11.0,
        "ask": 11.1,
        "last": 11.05,
        "timestamp": NOW,
    }
    values.update(overrides)
    return FXQuote(**values)


def test_valid_equity_quote_has_correct_mid() -> None:
    quote = make_equity_quote()

    assert quote.is_valid is True
    assert quote.mid == 101.0


def test_invalid_equity_quote_when_bid_missing() -> None:
    quote = make_equity_quote(bid=None)

    assert quote.is_valid is False
    assert quote.mid is None
    assert quote.spread_pct is None


def test_invalid_equity_quote_when_ask_less_than_bid() -> None:
    quote = make_equity_quote(bid=102.0, ask=100.0)

    assert quote.is_valid is False
    assert quote.mid is None


def test_equity_quote_spread_pct_correct() -> None:
    quote = make_equity_quote(bid=100.0, ask=102.0)

    assert quote.spread_pct == pytest.approx(2.0 / 101.0)


def test_valid_fx_quote_has_correct_mid() -> None:
    quote = make_fx_quote()

    assert quote.is_valid is True
    assert quote.mid == pytest.approx(11.05)


def test_fx_quote_spread_pct_correct() -> None:
    quote = make_fx_quote(bid=11.0, ask=11.1)

    assert quote.spread_pct == pytest.approx(0.1 / 11.05)


def test_spread_snapshot_can_be_instantiated() -> None:
    snapshot = SpreadSnapshot(
        timestamp=NOW,
        pair_id="ABC-SEK-EUR",
        long_leg_symbol="ABC",
        short_leg_symbol="ABC",
        long_leg_exchange="SFB",
        short_leg_exchange="HEX",
        long_leg_currency="SEK",
        short_leg_currency="EUR",
        long_leg_ask=102.0,
        short_leg_bid=9.1,
        fx_pair="EURSEK",
        fx_bid=11.0,
        fx_ask=11.1,
        gross_edge=0.02,
        cost_buffer_bps=20,
        net_edge=0.018,
        signal=False,
        rejection_reason=None,
    )

    assert snapshot.pair_id == "ABC-SEK-EUR"
    assert snapshot.signal is False


def test_dataclasses_can_be_converted_to_dict() -> None:
    equity_quote = make_equity_quote(contract_id=123)
    fx_quote = make_fx_quote()
    snapshot = SpreadSnapshot(
        timestamp=NOW,
        pair_id="ABC-SEK-EUR",
        long_leg_symbol="ABC",
        short_leg_symbol="ABC",
        long_leg_exchange="SFB",
        short_leg_exchange="HEX",
        long_leg_currency="SEK",
        short_leg_currency="EUR",
        long_leg_ask=102.0,
        short_leg_bid=9.1,
        fx_pair="EURSEK",
        fx_bid=11.0,
        fx_ask=11.1,
        gross_edge=0.02,
        cost_buffer_bps=20,
        net_edge=0.018,
        signal=False,
        rejection_reason=None,
    )

    assert asdict(equity_quote)["contract_id"] == 123
    assert asdict(fx_quote)["source"] == "IBKR_IDEALPRO"
    assert asdict(snapshot)["pair_id"] == "ABC-SEK-EUR"
