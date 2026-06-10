from src.data.live.ig_api import (
    IGAPIClient,
    IGCredentials,
    IGMarketDataProvider,
    ig_base_url,
    ig_base_url_for_profile,
    load_ig_credentials_for_profile_from_env,
    load_ig_credentials_from_env,
    load_ig_session_settings_for_profile_from_env,
    load_ig_session_settings_from_env,
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
        self.puts = []
        self.gets = []

    def post(self, url, headers, json, timeout):
        self.posts.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return FakeResponse(
            {"currentAccountId": "ABC123"},
            headers={"CST": "cst-token", "X-SECURITY-TOKEN": "security-token"},
        )

    def put(self, url, headers, json, timeout):
        self.puts.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return FakeResponse(
            {"currentAccountId": json["accountId"]},
            headers={"CST": "new-cst-token", "X-SECURITY-TOKEN": "new-security-token"},
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
        if "/prices/" in url:
            return FakeResponse(
                {
                    "prices": [
                        {
                            "snapshotTimeUTC": "2026/06/10 18:00:00",
                            "closePrice": {
                                "bid": 307.5,
                                "ask": 308.5,
                                "last": 308.0,
                            },
                        }
                    ]
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


def test_switch_account_updates_session_tokens() -> None:
    session = FakeSession()
    client = IGAPIClient(
        "https://demo-api.ig.com/gateway/deal",
        IGCredentials("key", "user", "pass"),
        session=session,
    )
    client.login()

    response = client.switch_account("CFD123")

    assert response["currentAccountId"] == "CFD123"
    assert client.cst == "new-cst-token"
    assert client.security_token == "new-security-token"
    assert session.puts[0]["json"] == {"accountId": "CFD123", "defaultAccount": False}
    assert session.puts[0]["headers"]["Version"] == "1"


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


def test_get_prices_uses_ig_prices_endpoint() -> None:
    session = FakeSession()
    client = IGAPIClient(
        "https://demo-api.ig.com/gateway/deal",
        IGCredentials("key", "user", "pass"),
        session=session,
    )
    client.login()

    prices = client.get_prices("CS.D.AAPL.CFD.IP", resolution="MINUTE", num_points=1)

    assert prices["prices"][0]["closePrice"]["bid"] == 307.5
    assert session.gets[-1]["url"].endswith("/prices/CS.D.AAPL.CFD.IP")
    assert session.gets[-1]["params"] == {"resolution": "MINUTE", "max": 1}
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


def test_ig_market_data_provider_maps_equity_quote_from_prices() -> None:
    session = FakeSession()
    client = IGAPIClient(
        "https://demo-api.ig.com/gateway/deal",
        IGCredentials("key", "user", "pass"),
        session=session,
    )
    client.login()
    provider = IGMarketDataProvider(client)

    quote = provider.get_equity_quote_from_prices(
        "CS.D.AAPL.CFD.IP",
        symbol="AAPL",
        exchange="IG",
        currency="USD",
    )

    assert quote.symbol == "AAPL"
    assert quote.currency == "USD"
    assert quote.bid == 307.5
    assert quote.ask == 308.5
    assert quote.last == 308.0
    assert quote.source == "IG_API_PRICES"
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


def test_ig_market_data_provider_maps_fx_quote_from_prices() -> None:
    session = FakeSession()
    client = IGAPIClient(
        "https://demo-api.ig.com/gateway/deal",
        IGCredentials("key", "user", "pass"),
        session=session,
    )
    client.login()
    provider = IGMarketDataProvider(client)

    quote = provider.get_fx_quote_from_prices("CS.D.EURSEK.CFD.IP", pair="EURSEK")

    assert quote.pair == "EURSEK"
    assert quote.bid == 307.5
    assert quote.ask == 308.5
    assert quote.source == "IG_API_PRICES"


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


def test_load_ig_session_settings_from_env(monkeypatch) -> None:
    config = {"ig": {"account_id_env": "IG_ACCOUNT_ID"}}
    monkeypatch.setenv("IG_ACCOUNT_ID", "CFD123")

    settings = load_ig_session_settings_from_env(config)

    assert settings.account_id == "CFD123"


def test_load_ig_credentials_for_named_profile(monkeypatch) -> None:
    config = {
        "ig_live_data": {
            "api_key_env": "IG_LIVE_API_KEY",
            "username_env": "IG_LIVE_USERNAME",
            "password_env": "IG_LIVE_PASSWORD",
        }
    }
    monkeypatch.setenv("IG_LIVE_API_KEY", "live-key")
    monkeypatch.setenv("IG_LIVE_USERNAME", "live-user")
    monkeypatch.setenv("IG_LIVE_PASSWORD", "live-pass")

    credentials = load_ig_credentials_for_profile_from_env(config, "ig_live_data")

    assert credentials == IGCredentials(
        api_key="live-key",
        username="live-user",
        password="live-pass",
    )


def test_load_ig_session_settings_for_named_profile(monkeypatch) -> None:
    config = {"ig_live_data": {"account_id_env": "IG_LIVE_ACCOUNT_ID"}}
    monkeypatch.setenv("IG_LIVE_ACCOUNT_ID", "LIVE123")

    settings = load_ig_session_settings_for_profile_from_env(config, "ig_live_data")

    assert settings.account_id == "LIVE123"


def test_ig_base_url_uses_demo_by_default() -> None:
    config = {
        "ig": {
            "environment": "demo",
            "demo_base_url": "https://demo-api.ig.com/gateway/deal",
            "live_base_url": "https://api.ig.com/gateway/deal",
        }
    }

    assert ig_base_url(config) == "https://demo-api.ig.com/gateway/deal"


def test_ig_base_url_for_live_profile() -> None:
    config = {
        "ig_live_data": {
            "environment": "live",
            "demo_base_url": "https://demo-api.ig.com/gateway/deal",
            "live_base_url": "https://api.ig.com/gateway/deal",
        }
    }

    assert (
        ig_base_url_for_profile(config, "ig_live_data")
        == "https://api.ig.com/gateway/deal"
    )


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
