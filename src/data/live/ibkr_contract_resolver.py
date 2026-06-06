"""Resolve user-provided tickers into supported IBKR listing candidates."""

from dataclasses import dataclass
from typing import Any


SUPPORTED_COUNTRIES = {"Sweden", "Finland", "Denmark"}
SUPPORTED_CURRENCIES = {"SEK", "EUR", "DKK"}
SUPPORTED_EXCHANGES = {
    "NASDAQ STOCKHOLM",
    "NASDAQ HELSINKI",
    "NASDAQ COPENHAGEN",
}
UNSUPPORTED_COUNTRIES = {"Norway"}
UNSUPPORTED_CURRENCIES = {"NOK"}
UNSUPPORTED_EXCHANGE_MARKERS = {
    "OSLO",
    "OSLO BORS",
    "OSLO BØRS",
    "EURONEXT OSLO",
}
ALLOWED_STATUSES = {
    "resolved",
    "ambiguous",
    "not_found",
    "unsupported_market",
    "unsupported_currency",
    "pending_user_review",
}


@dataclass
class ResolvedListingCandidate:
    watchlist_ticker: str
    resolved_symbol: str
    company_name: str
    exchange: str
    currency: str
    country: str
    primary_exchange: str
    sec_type: str
    ibkr_conid: int | None
    ibkr_local_symbol: str
    ibkr_trading_class: str
    resolution_source: str
    resolved_status: str
    rejection_reason: str
    notes: str


def _get_value(source: Any, name: str, default: Any = "") -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _contract_from_detail(contract_detail: Any) -> Any:
    return _get_value(contract_detail, "contract", contract_detail)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _normalized(value: Any) -> str:
    return _text(value).strip().upper()


def _country_for_contract(contract_detail: Any) -> str:
    country = _text(_get_value(contract_detail, "country", "")).strip()
    if country:
        return country

    contract = _contract_from_detail(contract_detail)
    exchange_text = " ".join(
        [
            _text(_get_value(contract, "exchange", "")),
            _text(_get_value(contract, "primaryExchange", "")),
        ]
    )
    exchange_upper = _normalized(exchange_text)
    if "STOCKHOLM" in exchange_upper:
        return "Sweden"
    if "HELSINKI" in exchange_upper:
        return "Finland"
    if "COPENHAGEN" in exchange_upper:
        return "Denmark"
    if "OSLO" in exchange_upper:
        return "Norway"
    return ""


def _market_name(contract_detail: Any) -> str:
    contract = _contract_from_detail(contract_detail)
    return " ".join(
        [
            _text(_get_value(contract, "exchange", "")),
            _text(_get_value(contract, "primaryExchange", "")),
            _text(_get_value(contract_detail, "marketName", "")),
        ]
    )


def _status_and_reason(contract_detail: Any) -> tuple[str, str]:
    contract = _contract_from_detail(contract_detail)
    currency = _normalized(_get_value(contract, "currency", ""))
    country = _country_for_contract(contract_detail)
    country_upper = _normalized(country)
    market_upper = _normalized(_market_name(contract_detail))

    if currency in UNSUPPORTED_CURRENCIES:
        return "unsupported_currency", f"Unsupported currency for MVP: {currency}"
    if currency and currency not in SUPPORTED_CURRENCIES:
        return "unsupported_currency", f"Unsupported currency for MVP: {currency}"
    if country_upper in {country.upper() for country in UNSUPPORTED_COUNTRIES}:
        return "unsupported_market", f"Unsupported country for MVP: {country}"
    if any(marker in market_upper for marker in UNSUPPORTED_EXCHANGE_MARKERS):
        return "unsupported_market", "Unsupported exchange for MVP"
    if country and country not in SUPPORTED_COUNTRIES:
        return "unsupported_market", f"Unsupported country for MVP: {country}"

    exchange_supported = any(
        exchange in market_upper for exchange in SUPPORTED_EXCHANGES
    )
    if not exchange_supported:
        return "unsupported_market", "Unsupported exchange for MVP"

    return "resolved", ""


def filter_supported_nordic_contracts(contract_details: list[Any]) -> list[Any]:
    """Return only supported Sweden/Finland/Denmark SEK/EUR/DKK contracts."""
    return [
        contract_detail
        for contract_detail in contract_details
        if _status_and_reason(contract_detail)[0] == "resolved"
    ]


def contract_detail_to_candidate(
    watchlist_ticker: str,
    contract_detail: Any,
) -> ResolvedListingCandidate:
    """Convert one IBKR contract detail object into a listing candidate."""
    contract = _contract_from_detail(contract_detail)
    status, rejection_reason = _status_and_reason(contract_detail)

    return ResolvedListingCandidate(
        watchlist_ticker=watchlist_ticker,
        resolved_symbol=_text(_get_value(contract, "symbol", "")),
        company_name=_text(_get_value(contract_detail, "longName", "")),
        exchange=_text(_get_value(contract, "exchange", "")),
        currency=_text(_get_value(contract, "currency", "")),
        country=_country_for_contract(contract_detail),
        primary_exchange=_text(_get_value(contract, "primaryExchange", "")),
        sec_type=_text(_get_value(contract, "secType", "")),
        ibkr_conid=_get_value(contract, "conId", None),
        ibkr_local_symbol=_text(_get_value(contract, "localSymbol", "")),
        ibkr_trading_class=_text(_get_value(contract, "tradingClass", "")),
        resolution_source="IBKR",
        resolved_status=status,
        rejection_reason=rejection_reason,
        notes="",
    )


def _not_found_candidate(ticker: str) -> ResolvedListingCandidate:
    return ResolvedListingCandidate(
        watchlist_ticker=ticker,
        resolved_symbol="",
        company_name="",
        exchange="",
        currency="",
        country="",
        primary_exchange="",
        sec_type="",
        ibkr_conid=None,
        ibkr_local_symbol="",
        ibkr_trading_class="",
        resolution_source="IBKR",
        resolved_status="not_found",
        rejection_reason="No IBKR contract details found for user-provided ticker.",
        notes="",
    )


def resolve_watchlist_ticker_with_ibkr(
    ib_client: Any,
    ticker: str,
) -> list[ResolvedListingCandidate]:
    """Resolve one user-supplied ticker using the provided IBKR-like client."""
    contract_details = ib_client.reqContractDetails(ticker)
    if not contract_details:
        return [_not_found_candidate(ticker)]

    candidates = [
        contract_detail_to_candidate(ticker, contract_detail)
        for contract_detail in contract_details
    ]
    supported_candidates = [
        candidate
        for candidate in candidates
        if candidate.resolved_status == "resolved"
    ]

    if len(supported_candidates) > 1:
        return [
            ResolvedListingCandidate(
                **{
                    **candidate.__dict__,
                    "resolved_status": "ambiguous",
                    "rejection_reason": (
                        "Multiple supported IBKR contracts found; user review required."
                    ),
                }
            )
            for candidate in supported_candidates
        ]

    return candidates
