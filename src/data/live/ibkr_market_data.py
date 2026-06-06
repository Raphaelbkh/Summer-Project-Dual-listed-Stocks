"""IBKR market data configuration and observe-only equity quote provider."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import asyncio

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
        self.ib.connect(self.host, self.port, clientId=self.client_id)

    def disconnect(self) -> None:
        """Disconnect the injected IB client."""
        self.ib.disconnect()

    def is_connected(self) -> bool:
        """Return True when the injected IB client reports an active connection."""
        return bool(self.ib.isConnected())

    def qualify_stock_contract(self, symbol: str, exchange: str, currency: str) -> Any:
        """Build and qualify an IBKR Stock contract for one user-provided symbol."""
        contract = _stock_contract(symbol, exchange, currency)
        qualified_contracts = self.ib.qualifyContracts(contract)
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
        self.ib.sleep(1)

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


def _ensure_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _ib_client() -> Any:
    _ensure_event_loop()
    from ib_insync import IB

    return IB()


def _stock_contract(symbol: str, exchange: str, currency: str) -> Any:
    _ensure_event_loop()
    from ib_insync import Stock

    return Stock(symbol, exchange, currency)
