from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from src.data.live.ibkr_market_data import IBKREquityMarketDataProvider


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@dataclass
class FakeQualifiedContract:
    symbol: str
    exchange: str
    currency: str
    conId: int = 123


@dataclass
class FakeTicker:
    bid: float | None
    ask: float | None
    bidSize: float | None = 10.0
    askSize: float | None = 12.0
    last: float | None = 100.5
    time: datetime = NOW


class FakeIBClient:
    def __init__(
        self,
        ticker: FakeTicker | None = None,
        qualified_contracts: list[FakeQualifiedContract] | None = None,
    ) -> None:
        self.connected = False
        self.ticker = ticker or FakeTicker(bid=100.0, ask=101.0)
        self.qualified_contracts = (
            qualified_contracts
            if qualified_contracts is not None
            else [FakeQualifiedContract("ABC", "SMART", "SEK")]
        )
        self.connect_calls: list[dict] = []
        self.disconnect_calls = 0
        self.qualified_requests = []
        self.market_data_requests = []
        self.sleep_calls: list[float] = []
        self.order_calls = 0

    def connect(self, host: str, port: int, clientId: int, readonly: bool = False) -> None:
        self.connected = True
        self.connect_calls.append(
            {"host": host, "port": port, "clientId": clientId, "readonly": readonly}
        )

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


def test_provider_can_be_initialized() -> None:
    fake_ib = FakeIBClient()
    provider = IBKREquityMarketDataProvider(
        host="127.0.0.1",
        port=7497,
        client_id=1,
        ib_client=fake_ib,
    )

    assert provider.host == "127.0.0.1"
    assert provider.port == 7497
    assert provider.client_id == 1
    assert provider.ib is fake_ib


def test_fake_connection_works() -> None:
    fake_ib = FakeIBClient()
    provider = IBKREquityMarketDataProvider("127.0.0.1", 7497, 1, fake_ib)

    provider.connect()

    assert provider.is_connected() is True
    assert fake_ib.connect_calls == [
        {"host": "127.0.0.1", "port": 7497, "clientId": 1, "readonly": True}
    ]


def test_fake_disconnect_works() -> None:
    fake_ib = FakeIBClient()
    provider = IBKREquityMarketDataProvider("127.0.0.1", 7497, 1, fake_ib)

    provider.connect()
    provider.disconnect()

    assert provider.is_connected() is False
    assert fake_ib.disconnect_calls == 1


def test_fake_contract_qualification_works() -> None:
    fake_contract = FakeQualifiedContract("ABC", "SMART", "SEK", conId=456)
    fake_ib = FakeIBClient(qualified_contracts=[fake_contract])
    provider = IBKREquityMarketDataProvider("127.0.0.1", 7497, 1, fake_ib)

    qualified = provider.qualify_stock_contract("ABC", "SMART", "SEK")

    assert qualified is fake_contract
    requested = fake_ib.qualified_requests[0]
    assert requested.symbol == "ABC"
    assert requested.exchange == "SMART"
    assert requested.currency == "SEK"


def test_fake_ticker_converts_into_equity_quote() -> None:
    fake_ib = FakeIBClient(
        ticker=FakeTicker(bid=100.0, ask=101.0, bidSize=20.0, askSize=30.0)
    )
    provider = IBKREquityMarketDataProvider("127.0.0.1", 7497, 1, fake_ib)

    quote = provider.get_equity_quote("ABC", "SMART", "SEK")

    assert quote.symbol == "ABC"
    assert quote.exchange == "SMART"
    assert quote.currency == "SEK"
    assert quote.bid == 100.0
    assert quote.ask == 101.0
    assert quote.bid_size == 20.0
    assert quote.ask_size == 30.0
    assert quote.contract_id == 123
    assert quote.is_valid is True
    assert fake_ib.market_data_requests[0]["snapshot"] is True


def test_missing_bid_ask_returns_invalid_equity_quote_but_does_not_crash() -> None:
    fake_ib = FakeIBClient(ticker=FakeTicker(bid=None, ask=None))
    provider = IBKREquityMarketDataProvider("127.0.0.1", 7497, 1, fake_ib)

    quote = provider.get_equity_quote("ABC", "SMART", "SEK")

    assert quote.bid is None
    assert quote.ask is None
    assert quote.is_valid is False


def test_qualification_failure_handled_clearly() -> None:
    fake_ib = FakeIBClient(qualified_contracts=[])
    provider = IBKREquityMarketDataProvider("127.0.0.1", 7497, 1, fake_ib)

    with pytest.raises(ValueError, match="contract qualification failed"):
        provider.get_equity_quote("BAD", "SMART", "SEK")


def test_no_order_methods_are_called() -> None:
    fake_ib = FakeIBClient()
    provider = IBKREquityMarketDataProvider("127.0.0.1", 7497, 1, fake_ib)

    provider.get_equity_quote("ABC", "SMART", "SEK")

    assert fake_ib.order_calls == 0
