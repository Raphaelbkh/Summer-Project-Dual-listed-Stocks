from datetime import date, datetime, timezone

import pandas as pd
import pytest

from src.data.live.quote_models import EquityQuote, FXQuote
from src.paper.tieto_readiness import (
    build_paper_signal,
    executable_spread_metrics,
    generate_daily_report,
    require_dry_run,
    validate_fx_contract,
    validate_stock_contract,
)


class Contract:
    conId = 123
    symbol = "TIETO"
    exchange = "HEX"
    currency = "EUR"
    tradingClass = "TIETO"
    localSymbol = "TIETO"


class FakeContractProvider:
    def __init__(self, missing: bool = False) -> None:
        self.missing = missing
        self.order_calls = 0

    def qualify_stock_contract(self, symbol, exchange, currency):
        if self.missing:
            raise ValueError("not found")
        return Contract()

    def qualify_fx_contract(self, pair):
        if self.missing:
            raise ValueError("not found")
        return Contract()

    def placeOrder(self, *args, **kwargs):
        self.order_calls += 1
        raise AssertionError("No order method may be called")


def equity(symbol: str, currency: str, bid: float, ask: float) -> EquityQuote:
    return EquityQuote(
        symbol=symbol,
        exchange="TEST",
        currency=currency,
        bid=bid,
        ask=ask,
        bid_size=1,
        ask_size=1,
        last=(bid + ask) / 2,
        timestamp=datetime(2026, 6, 18, 14, tzinfo=timezone.utc),
    )


def eursek(bid: float = 10.9, ask: float = 11.0) -> FXQuote:
    return FXQuote(
        pair="EURSEK",
        base_currency="EUR",
        quote_currency="SEK",
        bid=bid,
        ask=ask,
        last=(bid + ask) / 2,
        timestamp=datetime(2026, 6, 18, 14, tzinfo=timezone.utc),
    )


def test_contract_validation_fails_clearly_for_missing_contract() -> None:
    provider = FakeContractProvider(missing=True)

    with pytest.raises(ValueError, match="Unable to resolve Tieto Sweden contract"):
        validate_stock_contract(
            provider,
            "Tieto Sweden",
            {"symbol": "TIETOS", "exchange": "SMART:SFB", "currency": "SEK"},
        )


def test_contract_validation_print_fields_without_calling_orders() -> None:
    provider = FakeContractProvider()

    stock = validate_stock_contract(
        provider,
        "Tieto Finland",
        {"symbol": "TIETO", "exchange": "SMART:HEX", "currency": "EUR"},
    )
    fx = validate_fx_contract(provider, "EURSEK")

    assert stock.conId == 123
    assert stock.trading_class == "TIETO"
    assert stock.local_symbol == "TIETO"
    assert fx.conId == 123
    assert provider.order_calls == 0


def test_executable_spread_uses_bid_ask_not_mid_or_last() -> None:
    sweden = equity("TIETOS", "SEK", bid=110.0, ask=112.0)
    finland = equity("TIETO", "EUR", bid=9.8, ask=10.0)
    fx = eursek(bid=10.9, ask=11.0)

    metrics = executable_spread_metrics(sweden, finland, fx)

    expected_short = (110.0 - 10.0 * 11.0) / (10.0 * 11.0) * 10000
    expected_long = (9.8 * 10.9 - 112.0) / 112.0 * 10000
    assert metrics["short_sweden_long_finland_executable_spread_bps"] == pytest.approx(
        expected_short
    )
    assert metrics["long_sweden_short_finland_executable_spread_bps"] == pytest.approx(
        expected_long
    )


def test_paper_signal_blocks_entry_but_never_exit_at_excluded_hour() -> None:
    profile = {"pair_id": "tieto_fi_se", "exclude_entry_hours_utc": [15, 16]}
    quotes = {
        "sweden": equity("TIETOS", "SEK", 110, 112),
        "finland": equity("TIETO", "EUR", 9.8, 10.0),
        "eursek": eursek(),
    }
    timestamp = datetime(2026, 6, 18, 15, tzinfo=timezone.utc)

    entry = build_paper_signal(
        timestamp=timestamp,
        profile_name="tieto_30m_paper_start",
        profile=profile,
        action="ENTRY",
        direction="SHORT_SWEDEN_LONG_FINLAND",
        zscore=2.1,
        dry_run=True,
        **quotes,
    )
    exit_signal = build_paper_signal(
        timestamp=timestamp,
        profile_name="tieto_30m_paper_start",
        profile=profile,
        action="EXIT",
        direction="SHORT_SWEDEN_LONG_FINLAND",
        zscore=0.9,
        dry_run=True,
        **quotes,
    )

    assert entry.allowed_by_entry_policy is False
    assert entry.would_trade_boolean is False
    assert entry.block_reason == "excluded_entry_hour_observe_only"
    assert exit_signal.allowed_by_entry_policy is True
    assert exit_signal.would_trade_boolean is True


def test_daily_report_summarizes_policy_and_market_data() -> None:
    signals = pd.DataFrame(
        [
            {
                "action": "ENTRY",
                "allowed_by_entry_policy": True,
                "block_reason": "",
                "mid_spread_bps": 20,
                "executable_spread_bps": 10,
                "sweden_bid": 100,
                "sweden_ask": 101,
                "finland_bid": 10,
                "finland_ask": 10.1,
                "eursek_bid": 11,
                "eursek_ask": 11.1,
            },
            {
                "action": "ENTRY",
                "allowed_by_entry_policy": False,
                "block_reason": "excluded_entry_hour_observe_only",
                "mid_spread_bps": 40,
                "executable_spread_bps": 30,
                "sweden_bid": None,
                "sweden_ask": None,
                "finland_bid": 10,
                "finland_ask": 10.1,
                "eursek_bid": 11,
                "eursek_ask": 11.1,
            },
        ]
    )

    report = generate_daily_report(signals, date(2026, 6, 18)).iloc[0]

    assert report["total_signals"] == 2
    assert report["allowed_signals"] == 1
    assert report["blocked_observe_only_signals"] == 1
    assert report["excluded_hour_signal_count"] == 1
    assert report["missing_market_data_count"] == 1
    assert report["average_mid_spread_bps"] == 30


def test_non_dry_run_is_impossible() -> None:
    with pytest.raises(RuntimeError, match="dry_run=True"):
        require_dry_run(False)
