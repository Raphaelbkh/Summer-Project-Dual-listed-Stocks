from dataclasses import dataclass
from datetime import datetime, timezone

from src.fx.ibkr_fx import IBKRFXProvider


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@dataclass
class FakeFXContract:
    symbol: str
    secType: str = "CASH"
    exchange: str = "IDEALPRO"


@dataclass
class FakeTicker:
    bid: float | None
    ask: float | None
    last: float | None = 11.05
    time: datetime = NOW


class FakeIBClient:
    def __init__(
        self,
        ticker: FakeTicker | None = None,
        qualified_contracts: list[FakeFXContract] | None = None,
    ) -> None:
        self.connected = False
        self.ticker = ticker or FakeTicker(bid=11.0, ask=11.1)
        self.qualified_contracts = (
            qualified_contracts
            if qualified_contracts is not None
            else [FakeFXContract("EURSEK")]
        )
        self.connect_calls: list[tuple[str, int, int]] = []
        self.disconnect_calls = 0
        self.qualified_requests = []
        self.market_data_requests = []
        self.sleep_calls: list[float] = []
        self.external_fx_calls = 0
        self.order_calls = 0

    def connect(self, host: str, port: int, clientId: int) -> None:
        self.connected = True
        self.connect_calls.append((host, port, clientId))

    def disconnect(self) -> None:
        self.connected = False
        self.disconnect_calls += 1

    def isConnected(self) -> bool:
        return self.connected

    def qualifyContracts(self, contract):
        self.qualified_requests.append(contract)
        return self.qualified_contracts

    def reqMktData(
        self,
        contract,
        genericTickList: str,
        snapshot: bool,
        regulatorySnapshot: bool,
    ) -> FakeTicker:
        self.market_data_requests.append(
            {
                "contract": contract,
                "genericTickList": genericTickList,
                "snapshot": snapshot,
                "regulatorySnapshot": regulatorySnapshot,
            }
        )
        return self.ticker

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)

    def placeOrder(self, *args, **kwargs):
        self.order_calls += 1
        raise AssertionError("placeOrder must not be called")

    def external_fx_provider(self):
        self.external_fx_calls += 1
        raise AssertionError("external FX provider must not be called")


def provider_for_pair(pair: str, ticker: FakeTicker | None = None) -> tuple[IBKRFXProvider, FakeIBClient]:
    fake_ib = FakeIBClient(
        ticker=ticker,
        qualified_contracts=[FakeFXContract(pair)],
    )
    return IBKRFXProvider("127.0.0.1", 7497, 2, fake_ib), fake_ib


def test_provider_initializes() -> None:
    fake_ib = FakeIBClient()
    provider = IBKRFXProvider("127.0.0.1", 7497, 2, fake_ib)

    assert provider.host == "127.0.0.1"
    assert provider.port == 7497
    assert provider.client_id == 2
    assert provider.ib is fake_ib


def test_fake_connection_works() -> None:
    provider, fake_ib = provider_for_pair("EURSEK")

    provider.connect()

    assert provider.is_connected() is True
    assert fake_ib.connect_calls == [("127.0.0.1", 7497, 2)]


def test_fake_disconnect_works() -> None:
    provider, fake_ib = provider_for_pair("EURSEK")

    provider.connect()
    provider.disconnect()

    assert provider.is_connected() is False
    assert fake_ib.disconnect_calls == 1


def test_eursek_fake_quote_returns_fx_quote() -> None:
    provider, fake_ib = provider_for_pair("EURSEK")

    quote = provider.get_fx_quote("EURSEK")

    assert quote.pair == "EURSEK"
    assert quote.base_currency == "EUR"
    assert quote.quote_currency == "SEK"
    assert quote.bid == 11.0
    assert quote.ask == 11.1
    assert quote.source == "IBKR_IDEALPRO"
    assert quote.is_valid is True
    assert fake_ib.market_data_requests[0]["snapshot"] is True


def test_eurdkk_fake_quote_returns_fx_quote() -> None:
    provider, _ = provider_for_pair("EURDKK", FakeTicker(bid=7.45, ask=7.46))

    quote = provider.get_fx_quote("EURDKK")

    assert quote.pair == "EURDKK"
    assert quote.base_currency == "EUR"
    assert quote.quote_currency == "DKK"
    assert quote.bid == 7.45
    assert quote.ask == 7.46


def test_dkksek_optional_fake_quote_can_return_fx_quote() -> None:
    provider, _ = provider_for_pair("DKKSEK", FakeTicker(bid=1.47, ask=1.48))

    quote = provider.get_fx_quote("DKKSEK")

    assert quote.pair == "DKKSEK"
    assert quote.base_currency == "DKK"
    assert quote.quote_currency == "SEK"
    assert quote.is_valid is True


def test_missing_bid_ask_creates_invalid_fx_quote() -> None:
    provider, _ = provider_for_pair("EURSEK", FakeTicker(bid=None, ask=None))

    quote = provider.get_fx_quote("EURSEK")

    assert quote.bid is None
    assert quote.ask is None
    assert quote.is_valid is False


def test_no_external_fx_provider_is_called() -> None:
    provider, fake_ib = provider_for_pair("EURSEK")

    provider.get_fx_quote("EURSEK")

    assert fake_ib.external_fx_calls == 0


def test_no_order_methods_are_called() -> None:
    provider, fake_ib = provider_for_pair("EURSEK")

    provider.get_fx_quote("EURSEK")

    assert fake_ib.order_calls == 0
