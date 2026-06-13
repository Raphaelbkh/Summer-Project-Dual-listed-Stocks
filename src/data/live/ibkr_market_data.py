"""IBKR market data configuration and observe-only equity quote provider."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import asyncio

import pandas as pd

from src.data.live.quote_models import EquityQuote
from src.utils.time_utils import utc_now


SUPPORTED_MODES = {"paper", "live"}


@dataclass
class IBKRConnectionConfig:
    host: str
    paper_port: int
    live_port: int
    gateway_paper_port: int
    gateway_live_port: int
    client_id_market_data: int
    mode: str
    use_gateway: bool = False
    client_id_fx: int | None = None
    client_id_orders: int | None = None
    account: str | None = None


@dataclass
class _SimpleStockContract:
    symbol: str
    exchange: str
    currency: str
    primaryExchange: str | None = None


def resolve_ibkr_port(config: IBKRConnectionConfig) -> int:
    """Resolve the configured IBKR port for TWS or IB Gateway."""
    mode = config.mode.lower()
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported IBKR mode: {config.mode}")

    if config.use_gateway:
        return config.gateway_paper_port if mode == "paper" else config.gateway_live_port
    return config.paper_port if mode == "paper" else config.live_port


def validate_observe_only_config(config_dict: dict) -> None:
    """Ensure the MVP is configured for observation only."""
    observe_only = config_dict.get("execution", {}).get("observe_only")
    if observe_only is not True:
        raise ValueError("MVP requires execution.observe_only=true.")


def load_ibkr_connection_config(config_dict: dict) -> IBKRConnectionConfig:
    """Load IBKR connection settings from the project config dictionary."""
    validate_observe_only_config(config_dict)
    ibkr_config = config_dict["ibkr"]
    mode = ibkr_config.get("mode", "paper")
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported IBKR mode: {mode}")

    return IBKRConnectionConfig(
        host=ibkr_config["host"],
        paper_port=int(ibkr_config["paper_port"]),
        live_port=int(ibkr_config["live_port"]),
        gateway_paper_port=int(ibkr_config["gateway_paper_port"]),
        gateway_live_port=int(ibkr_config["gateway_live_port"]),
        client_id_market_data=int(ibkr_config["client_id_market_data"]),
        mode=mode,
        use_gateway=bool(ibkr_config.get("use_gateway", False)),
        client_id_fx=int(ibkr_config.get("client_id_fx", 2)),
        client_id_orders=int(ibkr_config.get("client_id_orders", 3)),
        account=ibkr_config.get("account"),
    )


class IBKREquityMarketDataProvider:
    """Observe-only IBKR equity market data provider for snapshot quotes."""

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        ib_client: Any | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = ib_client if ib_client is not None else _ib_client()

    def connect(self) -> None:
        """Connect the injected IB client to TWS or IB Gateway."""
        self.ib.connect(self.host, self.port, clientId=self.client_id, readonly=True)

    def disconnect(self) -> None:
        """Disconnect the injected IB client."""
        self.ib.disconnect()

    def is_connected(self) -> bool:
        """Return True when the injected IB client reports an active connection."""
        return bool(self.ib.isConnected())

    def qualify_stock_contract(
        self,
        symbol: str,
        exchange: str,
        currency: str,
        primary_exchange: str | None = None,
    ) -> Any:
        """Build and qualify an IBKR Stock contract for one user-provided symbol."""
        contract = _stock_contract(symbol, exchange, currency, primary_exchange)
        return self._qualify_contract(contract, symbol, exchange, currency)

    def _qualify_contract(
        self,
        contract: Any,
        symbol: str,
        exchange: str,
        currency: str,
    ) -> Any:
        qualified_contracts = [
            qualified_contract
            for qualified_contract in self.ib.qualifyContracts(contract)
            if qualified_contract is not None
        ]
        if not qualified_contracts:
            raise ValueError(
                "IBKR contract qualification failed for "
                f"symbol={symbol}, exchange={exchange}, currency={currency}."
            )
        return qualified_contracts[0]

    def get_equity_quote(
        self,
        symbol: str,
        exchange: str,
        currency: str,
    ) -> EquityQuote:
        """Fetch one observe-only snapshot quote and convert it to EquityQuote."""
        contract = self.qualify_stock_contract(symbol, exchange, currency)
        ticker = self.ib.reqMktData(
            contract,
            genericTickList="",
            snapshot=True,
            regulatorySnapshot=False,
        )
        self._wait_for_bid_ask(ticker)

        return EquityQuote(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            bid=_optional_float(getattr(ticker, "bid", None)),
            ask=_optional_float(getattr(ticker, "ask", None)),
            bid_size=_optional_float(getattr(ticker, "bidSize", None)),
            ask_size=_optional_float(getattr(ticker, "askSize", None)),
            last=_optional_float(getattr(ticker, "last", None)),
            timestamp=_ticker_timestamp(ticker),
            contract_id=getattr(contract, "conId", None),
        )

    def get_historical_bars(
        self,
        symbol: str,
        exchange: str,
        currency: str,
        duration_str: str = "1 W",
        bar_size_setting: str = "1 day",
        what_to_show: str = "TRADES",
        use_rth: bool = True,
    ) -> pd.DataFrame:
        """Fetch historical bars using a direct-exchange IBKR stock contract."""
        historical_contract = _historical_stock_contract(symbol, exchange, currency)
        contract = self._qualify_contract(historical_contract, symbol, exchange, currency)
        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration_str,
            barSizeSetting=bar_size_setting,
            whatToShow=what_to_show,
            useRTH=use_rth,
            formatDate=1,
        )
        return _bars_to_dataframe(bars)

    def _wait_for_bid_ask(self, ticker: Any, timeout_seconds: float = 5.0) -> None:
        """Wait briefly for IBKR snapshot fields to populate."""
        elapsed = 0.0
        step = 0.25
        while elapsed < timeout_seconds:
            if _optional_float(getattr(ticker, "bid", None)) is not None and _optional_float(
                getattr(ticker, "ask", None)
            ) is not None:
                return
            self.ib.sleep(step)
            elapsed += step


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _ticker_timestamp(ticker: Any) -> datetime:
    for attr_name in ("time", "rtTime"):
        value = getattr(ticker, attr_name, None)
        if isinstance(value, datetime):
            return value
    return utc_now()


def _bars_to_dataframe(bars: list[Any]) -> pd.DataFrame:
    rows = []
    for bar in bars:
        rows.append(
            {
                "date": getattr(bar, "date", None),
                "open": _optional_float(getattr(bar, "open", None)),
                "high": _optional_float(getattr(bar, "high", None)),
                "low": _optional_float(getattr(bar, "low", None)),
                "close": _optional_float(getattr(bar, "close", None)),
                "volume": _optional_float(getattr(bar, "volume", None)),
                "bar_count": _optional_float(getattr(bar, "barCount", None)),
                "average": _optional_float(getattr(bar, "average", None)),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "bar_count",
            "average",
        ],
    )


def _ensure_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _ib_client() -> Any:
    _ensure_event_loop()
    from ib_async import IB

    return IB()


def _stock_contract(
    symbol: str,
    exchange: str,
    currency: str,
    primary_exchange: str | None = None,
) -> Any:
    _ensure_event_loop()
    try:
        from ib_async import Stock
    except ModuleNotFoundError:
        Stock = _SimpleStockContract

    resolved_exchange, resolved_primary_exchange = _split_exchange(exchange)
    contract = Stock(symbol, resolved_exchange, currency)
    primary = primary_exchange or resolved_primary_exchange
    if primary:
        contract.primaryExchange = primary
    return contract


def _historical_stock_contract(symbol: str, exchange: str, currency: str) -> Any:
    _ensure_event_loop()
    try:
        from ib_async import Stock
    except ModuleNotFoundError:
        Stock = _SimpleStockContract

    route_exchange, primary_exchange = _split_exchange(exchange)
    direct_exchange = primary_exchange or route_exchange
    return Stock(symbol, direct_exchange, currency)


def _split_exchange(exchange: str) -> tuple[str, str | None]:
    if ":" not in exchange:
        return exchange, None
    route_exchange, primary_exchange = exchange.split(":", 1)
    return route_exchange, primary_exchange or None
