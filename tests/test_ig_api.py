from src.data.live.ig_api import (
    IGAPIClient,
    IGCredentials,
    IGMarketDataProvider,
    ig_base_url,
    load_ig_credentials_from_env,
)
import requests
import pytest


class FakeResponse:
    def __init__(self, body, headers=None, status_code=200) -> None:
        self.body = body
        self.headers = headers or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP error", response=self)

    def json(self):
        return self.body


class FakeSession:
    def __init__(self) -> None:
        self.posts = []
        self.gets = []

    def post(self, url, headers, json, timeout):
        self.posts.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return FakeResponse(
            {"currentAccountId": "ABC123"},
            headers={"CST": "cst-token", "X-SECURITY-TOKEN": "security-token"},
        )

    def get(self, url, headers, timeout, params=None):
        self.gets.append(
            {"url": url, "headers": headers, "timeout": timeout, "params": params}
        )
        if url.endswith("/markets"):
            return FakeResponse(
                {
                    "markets": [
                        {
                            "epic": "CS.D.AAPL.CFD.IP",
                            "instrumentName": "Apple Inc",
                            "instrumentType": "SHARES",
                            "expiry": "-",
                            "marketStatus": "TRADEABLE",
                            "bid": 307.5,
                            "offer": 308.5,
                            "currency": "USD",
                        }
                    ]
                }
            )
        if "/markets/" in url:
            return FakeResponse(
                {
                    "instrument": {
                        "name": "Apple Inc",
                        "currencies": [{"code": "USD"}],
                    },
                    "snapshot": {
                        "bid": 307.5,
                        "offer": 308.5,
                        "lastTraded": 308.0,
                    },
                }
            )
        return FakeResponse({"accounts": [{"accountId": "ABC123"}]})


def test_ig_login_stores_tokens() -> None:
    session = FakeSession()
    client = IGAPIClient(
        "https://demo-api.ig.com/gateway/deal",
        IGCredentials("key", "user", "pass"),
        session=session,
    )

    body = client.login()

    assert body["currentAccountId"] == "ABC123"
    assert client.cst == "cst-token"
    assert client.security_token == "security-token"
    assert session.posts[0]["headers"]["X-IG-API-KEY"] == "key"
    assert session.posts[0]["json"] == {"identifier": "user", "password": "pass"}


def test_get_accounts_uses_authenticated_headers() -> None:
    session = FakeSession()
    client = IGAPIClient(
        "https://demo-api.ig.com/gateway/deal",
        IGCredentials("key", "user", "pass"),
        session=session,
    )
    client.login()

    accounts = client.get_accounts()

    assert accounts["accounts"][0]["accountId"] == "ABC123"
    assert session.gets[0]["headers"]["CST"] == "cst-token"
    assert session.gets[0]["headers"]["X-SECURITY-TOKEN"] == "security-token"


def test_search_markets_uses_ig_market_search_endpoint() -> None:
    session = FakeSession()
    client = IGAPIClient(
        "https://demo-api.ig.com/gateway/deal",
        IGCredentials("key", "user", "pass"),
        session=session,
    )
    client.login()

    results = client.search_market_summaries("AAPL")

    assert results[0].epic == "CS.D.AAPL.CFD.IP"
    assert results[0].instrument_name == "Apple Inc"
    assert session.gets[-1]["url"].endswith("/markets")
    assert session.gets[-1]["params"] == {"searchTerm": "AAPL"}
    assert session.gets[-1]["headers"]["Version"] == "1"


def test_get_market_details_uses_epic_endpoint() -> None:
    session = FakeSession()
    client = IGAPIClient(
        "https://demo-api.ig.com/gateway/deal",
        IGCredentials("key", "user", "pass"),
        session=session,
    )
    client.login()

    details = client.get_market_details("CS.D.AAPL.CFD.IP")

    assert details["snapshot"]["bid"] == 307.5
    assert session.gets[-1]["url"].endswith("/markets/CS.D.AAPL.CFD.IP")
    assert session.gets[-1]["headers"]["Version"] == "3"


def test_ig_market_data_provider_maps_equity_quote() -> None:
    session = FakeSession()
    client = IGAPIClient(
        "https://demo-api.ig.com/gateway/deal",
        IGCredentials("key", "user", "pass"),
        session=session,
    )
    client.login()
    provider = IGMarketDataProvider(client)

    quote = provider.get_equity_quote_from_epic(
        "CS.D.AAPL.CFD.IP",
        symbol="AAPL",
        exchange="IG",
    )

    assert quote.symbol == "AAPL"
    assert quote.exchange == "IG"
    assert quote.currency == "USD"
    assert quote.bid == 307.5
    assert quote.ask == 308.5
    assert quote.source == "IG_API"
    assert quote.is_valid


def test_ig_market_data_provider_maps_fx_quote() -> None:
    session = FakeSession()
    client = IGAPIClient(
        "https://demo-api.ig.com/gateway/deal",
        IGCredentials("key", "user", "pass"),
        session=session,
    )
    client.login()
    provider = IGMarketDataProvider(client)

    quote = provider.get_fx_quote_from_epic("CS.D.EURSEK.CFD.IP", pair="EURSEK")

    assert quote.pair == "EURSEK"
    assert quote.base_currency == "EUR"
    assert quote.quote_currency == "SEK"
    assert quote.bid == 307.5
    assert quote.ask == 308.5
    assert quote.source == "IG_API"


def test_load_ig_credentials_from_env(monkeypatch) -> None:
    config = {
        "ig": {
            "api_key_env": "IG_API_KEY",
            "username_env": "IG_USERNAME",
            "password_env": "IG_PASSWORD",
        }
    }
    monkeypatch.setenv("IG_API_KEY", "key")
    monkeypatch.setenv("IG_USERNAME", "user")
    monkeypatch.setenv("IG_PASSWORD", "pass")

    credentials = load_ig_credentials_from_env(config)

    assert credentials == IGCredentials(api_key="key", username="user", password="pass")


def test_ig_base_url_uses_demo_by_default() -> None:
    config = {
        "ig": {
            "environment": "demo",
            "demo_base_url": "https://demo-api.ig.com/gateway/deal",
            "live_base_url": "https://api.ig.com/gateway/deal",
        }
    }

    assert ig_base_url(config) == "https://demo-api.ig.com/gateway/deal"


def test_ig_http_error_includes_response_body() -> None:
    class ErrorSession:
        def post(self, url, headers, json, timeout):
            return FakeResponse({"errorCode": "error.security.invalid-details"}, status_code=403)

    client = IGAPIClient(
        "https://demo-api.ig.com/gateway/deal",
        IGCredentials("key", "user", "pass"),
        session=ErrorSession(),
    )

    with pytest.raises(requests.HTTPError, match="error.security.invalid-details"):
        client.login()
