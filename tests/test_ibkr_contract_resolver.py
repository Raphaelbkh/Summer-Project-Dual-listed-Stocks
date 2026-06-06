from dataclasses import dataclass

from src.data.live.ibkr_contract_resolver import (
    ResolvedListingCandidate,
    contract_detail_to_candidate,
    filter_supported_nordic_contracts,
    resolve_watchlist_ticker_with_ibkr,
)


@dataclass
class FakeContract:
    symbol: str
    exchange: str
    currency: str
    primaryExchange: str
    secType: str = "STK"
    conId: int = 1
    localSymbol: str = "ABC"
    tradingClass: str = "ABC"


@dataclass
class FakeContractDetail:
    contract: FakeContract
    longName: str
    country: str = ""
    marketName: str = ""


class FakeIBClient:
    def __init__(self, contract_details: list[FakeContractDetail]) -> None:
        self.contract_details = contract_details
        self.requested_tickers: list[str] = []

    def reqContractDetails(self, ticker: str) -> list[FakeContractDetail]:
        self.requested_tickers.append(ticker)
        return self.contract_details


def detail(
    *,
    symbol: str = "ABC",
    exchange: str,
    currency: str,
    primary_exchange: str,
    country: str,
    con_id: int = 1,
) -> FakeContractDetail:
    return FakeContractDetail(
        contract=FakeContract(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primaryExchange=primary_exchange,
            conId=con_id,
        ),
        longName=f"{symbol} Company",
        country=country,
    )


def test_stockholm_sek_contract_accepted() -> None:
    contract_detail = detail(
        exchange="SMART",
        currency="SEK",
        primary_exchange="NASDAQ STOCKHOLM",
        country="Sweden",
    )

    candidate = contract_detail_to_candidate("ABC", contract_detail)

    assert candidate.resolved_status == "resolved"
    assert candidate.currency == "SEK"
    assert candidate.country == "Sweden"


def test_helsinki_eur_contract_accepted() -> None:
    contract_detail = detail(
        exchange="SMART",
        currency="EUR",
        primary_exchange="NASDAQ HELSINKI",
        country="Finland",
    )

    assert contract_detail_to_candidate("ABC", contract_detail).resolved_status == "resolved"


def test_copenhagen_dkk_contract_accepted() -> None:
    contract_detail = detail(
        exchange="SMART",
        currency="DKK",
        primary_exchange="NASDAQ COPENHAGEN",
        country="Denmark",
    )

    assert contract_detail_to_candidate("ABC", contract_detail).resolved_status == "resolved"


def test_oslo_nok_contract_rejected() -> None:
    contract_detail = detail(
        exchange="SMART",
        currency="NOK",
        primary_exchange="EURONEXT OSLO",
        country="Norway",
    )

    candidate = contract_detail_to_candidate("ABC", contract_detail)

    assert candidate.resolved_status == "unsupported_currency"
    assert "NOK" in candidate.rejection_reason


def test_unrelated_ticker_not_added() -> None:
    ib_client = FakeIBClient(
        [
            detail(
                symbol="ABC",
                exchange="SMART",
                currency="SEK",
                primary_exchange="NASDAQ STOCKHOLM",
                country="Sweden",
            )
        ]
    )

    candidates = resolve_watchlist_ticker_with_ibkr(ib_client, "USER_TICKER")

    assert ib_client.requested_tickers == ["USER_TICKER"]
    assert {candidate.watchlist_ticker for candidate in candidates} == {"USER_TICKER"}


def test_ambiguous_multiple_contracts_marked_ambiguous() -> None:
    ib_client = FakeIBClient(
        [
            detail(
                symbol="ABC",
                exchange="SMART",
                currency="SEK",
                primary_exchange="NASDAQ STOCKHOLM",
                country="Sweden",
                con_id=1,
            ),
            detail(
                symbol="ABC",
                exchange="SMART",
                currency="EUR",
                primary_exchange="NASDAQ HELSINKI",
                country="Finland",
                con_id=2,
            ),
        ]
    )

    candidates = resolve_watchlist_ticker_with_ibkr(ib_client, "ABC")

    assert [candidate.resolved_status for candidate in candidates] == [
        "ambiguous",
        "ambiguous",
    ]
    assert all("user review" in candidate.rejection_reason for candidate in candidates)


def test_no_contract_marked_not_found() -> None:
    candidates = resolve_watchlist_ticker_with_ibkr(FakeIBClient([]), "MISSING")

    assert len(candidates) == 1
    assert candidates[0].resolved_status == "not_found"
    assert candidates[0].watchlist_ticker == "MISSING"


def test_unsupported_currency_marked_unsupported_currency() -> None:
    contract_detail = detail(
        exchange="SMART",
        currency="USD",
        primary_exchange="NASDAQ STOCKHOLM",
        country="Sweden",
    )

    candidate = contract_detail_to_candidate("ABC", contract_detail)

    assert candidate.resolved_status == "unsupported_currency"


def test_unsupported_market_marked_unsupported_market() -> None:
    contract_detail = detail(
        exchange="SMART",
        currency="SEK",
        primary_exchange="NYSE",
        country="United States",
    )

    candidate = contract_detail_to_candidate("ABC", contract_detail)

    assert candidate.resolved_status == "unsupported_market"


def test_filter_supported_nordic_contracts_returns_only_supported() -> None:
    supported = detail(
        exchange="SMART",
        currency="SEK",
        primary_exchange="NASDAQ STOCKHOLM",
        country="Sweden",
    )
    unsupported = detail(
        exchange="SMART",
        currency="NOK",
        primary_exchange="EURONEXT OSLO",
        country="Norway",
    )

    assert filter_supported_nordic_contracts([supported, unsupported]) == [supported]


def test_resolved_listing_candidate_has_no_active_field() -> None:
    fields = ResolvedListingCandidate.__dataclass_fields__

    assert "active" not in fields
