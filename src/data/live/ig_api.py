"""Minimal IG REST API client for observe-only demo connectivity."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import os

import requests

from src.data.live.quote_models import EquityQuote, FXQuote
from src.utils.time_utils import utc_now


@dataclass
class IGCredentials:
    api_key: str
    username: str
    password: str


@dataclass
class IGMarketSearchResult:
    epic: str
    instrument_name: str
    instrument_type: str | None
    expiry: str | None
    market_status: str | None
    bid: float | None = None
    offer: float | None = None
    currency: str | None = None


class IGAPIClient:
    """Small IG REST client with session login for demo/live environments."""

    def __init__(
        self,
        base_url: str,
        credentials: IGCredentials,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials
        self.session = session or requests.Session()
        self.cst: str | None = None
        self.security_token: str | None = None

    def login(self) -> dict[str, Any]:
        """Create an IG API session and store response tokens."""
        response = self.session.post(
            f"{self.base_url}/session",
            headers={
                "X-IG-API-KEY": self.credentials.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json; charset=UTF-8",
                "Version": "2",
            },
            json={
                "identifier": self.credentials.username,
                "password": self.credentials.password,
            },
            timeout=15,
        )
        _raise_for_ig_error(response)
        self.cst = response.headers.get("CST")
        self.security_token = response.headers.get("X-SECURITY-TOKEN")
        return response.json()

    def authenticated_headers(self, version: str | None = None) -> dict[str, str]:
        """Return headers for authenticated observe-only API requests."""
        if not self.cst or not self.security_token:
            raise ValueError("IG API client is not logged in.")
        headers = {
            "X-IG-API-KEY": self.credentials.api_key,
            "CST": self.cst,
            "X-SECURITY-TOKEN": self.security_token,
            "Accept": "application/json; charset=UTF-8",
        }
        if version is not None:
            headers["Version"] = version
        return headers

    def get_accounts(self) -> dict[str, Any]:
        """Fetch account metadata after login."""
        response = self.session.get(
            f"{self.base_url}/accounts",
            headers=self.authenticated_headers(),
            timeout=15,
        )
        _raise_for_ig_error(response)
        return response.json()

    def search_markets(self, search_term: str) -> dict[str, Any]:
        """Search IG markets for a user-supplied term."""
        response = self.session.get(
            f"{self.base_url}/markets",
            headers=self.authenticated_headers(version="1"),
            params={"searchTerm": search_term},
            timeout=15,
        )
        _raise_for_ig_error(response)
        return response.json()

    def get_market_details(self, epic: str) -> dict[str, Any]:
        """Fetch current IG market details for a known epic."""
        response = self.session.get(
            f"{self.base_url}/markets/{epic}",
            headers=self.authenticated_headers(version="3"),
            timeout=15,
        )
        _raise_for_ig_error(response)
        return response.json()

    def search_market_summaries(self, search_term: str) -> list[IGMarketSearchResult]:
        """Return normalized search results for display/review."""
        payload = self.search_markets(search_term)
        return [_market_search_result_from_payload(row) for row in payload.get("markets", [])]


class IGMarketDataProvider:
    """Observe-only IG market data provider that never constructs orders."""

    def __init__(self, client: IGAPIClient) -> None:
        self.client = client

    def search_markets(self, search_term: str) -> list[IGMarketSearchResult]:
        """Search IG markets and return normalized summaries."""
        return self.client.search_market_summaries(search_term)

    def get_equity_quote_from_epic(
        self,
        epic: str,
        symbol: str,
        exchange: str,
        currency: str | None = None,
    ) -> EquityQuote:
        """Fetch an equity quote from a manually selected IG epic."""
        details = self.client.get_market_details(epic)
        snapshot = details.get("snapshot", {})
        instrument = details.get("instrument", {})
        resolved_currency = currency or _currency_from_instrument(instrument)
        return EquityQuote(
            symbol=symbol,
            exchange=exchange,
            currency=resolved_currency or "",
            bid=_to_optional_float(snapshot.get("bid")),
            ask=_to_optional_float(snapshot.get("offer")),
            bid_size=None,
            ask_size=None,
            last=_to_optional_float(snapshot.get("lastTraded")),
            timestamp=_timestamp_from_snapshot(snapshot),
            source="IG_API",
            contract_id=None,
        )

    def get_fx_quote_from_epic(self, epic: str, pair: str) -> FXQuote:
        """Fetch an FX quote from a manually selected IG epic."""
        details = self.client.get_market_details(epic)
        snapshot = details.get("snapshot", {})
        normalized_pair = pair.replace("/", "").upper()
        return FXQuote(
            pair=normalized_pair,
            base_currency=normalized_pair[:3],
            quote_currency=normalized_pair[3:],
            bid=_to_optional_float(snapshot.get("bid")),
            ask=_to_optional_float(snapshot.get("offer")),
            last=_to_optional_float(snapshot.get("lastTraded")),
            timestamp=_timestamp_from_snapshot(snapshot),
            source="IG_API",
        )


def _raise_for_ig_error(response: requests.Response) -> None:
    """Raise an HTTP error that includes IG's JSON errorCode when available."""
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            body = response.json()
        except ValueError:
            body = response.text
        raise requests.HTTPError(
            f"{exc}; IG response body: {body}",
            response=response,
        ) from exc


def load_ig_credentials_from_env(config_dict: dict) -> IGCredentials:
    """Load IG credentials from environment variables named in config."""
    ig_config = config_dict["ig"]
    api_key = os.getenv(ig_config["api_key_env"], "")
    username = os.getenv(ig_config["username_env"], "")
    password = os.getenv(ig_config["password_env"], "")
    missing = [
        name
        for name, value in [
            (ig_config["api_key_env"], api_key),
            (ig_config["username_env"], username),
            (ig_config["password_env"], password),
        ]
        if not value
    ]
    if missing:
        raise ValueError("Missing IG environment variables: " + ", ".join(missing))
    return IGCredentials(api_key=api_key, username=username, password=password)


def ig_base_url(config_dict: dict) -> str:
    """Resolve the configured IG REST base URL."""
    ig_config = config_dict["ig"]
    environment = ig_config.get("environment", "demo")
    if environment == "demo":
        return ig_config["demo_base_url"]
    if environment == "live":
        return ig_config["live_base_url"]
    raise ValueError(f"Unsupported IG environment: {environment}")


def _market_search_result_from_payload(row: dict[str, Any]) -> IGMarketSearchResult:
    return IGMarketSearchResult(
        epic=row.get("epic", ""),
        instrument_name=row.get("instrumentName", ""),
        instrument_type=row.get("instrumentType"),
        expiry=row.get("expiry"),
        market_status=row.get("marketStatus"),
        bid=_to_optional_float(row.get("bid")),
        offer=_to_optional_float(row.get("offer")),
        currency=row.get("currency"),
    )


def _currency_from_instrument(instrument: dict[str, Any]) -> str | None:
    currencies = instrument.get("currencies")
    if isinstance(currencies, list) and currencies:
        first_currency = currencies[0]
        if isinstance(first_currency, dict):
            return first_currency.get("code")
    currency = instrument.get("currency")
    if isinstance(currency, str):
        return currency
    return None


def _timestamp_from_snapshot(snapshot: dict[str, Any]) -> datetime:
    # IG update timestamps are not consistent across endpoints; use receive time.
    return utc_now()


def _to_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
