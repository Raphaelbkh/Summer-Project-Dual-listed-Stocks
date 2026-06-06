"""Observe-only IBKR IDEALPRO FX quote provider."""

from datetime import datetime
from typing import Any
import asyncio

from src.data.live.quote_models import FXQuote
from src.utils.time_utils import utc_now


class IBKRFXProvider:
    """IBKR IDEALPRO snapshot FX provider for the observe-only MVP."""

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

    def qualify_fx_contract(self, pair: str) -> Any:
        """Build and qualify an IBKR Forex contract for one currency pair."""
        contract = _forex_contract(pair)
        qualified_contracts = self.ib.qualifyContracts(contract)
        if not qualified_contracts:
            raise ValueError(f"IBKR FX contract qualification failed for pair={pair}.")
        return qualified_contracts[0]

    def get_fx_quote(self, pair: str) -> FXQuote:
        """Fetch one observe-only FX snapshot quote and convert it to FXQuote."""
        contract = self.qualify_fx_contract(pair)
        ticker = self.ib.reqMktData(
            contract,
            genericTickList="",
            snapshot=True,
            regulatorySnapshot=False,
        )
        self._wait_for_bid_ask(ticker)
        base_currency, quote_currency = _split_pair(pair)

        return FXQuote(
            pair=pair.upper(),
            base_currency=base_currency,
            quote_currency=quote_currency,
            bid=_optional_float(getattr(ticker, "bid", None)),
            ask=_optional_float(getattr(ticker, "ask", None)),
            last=_optional_float(getattr(ticker, "last", None)),
            timestamp=_ticker_timestamp(ticker),
        )

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


def _split_pair(pair: str) -> tuple[str, str]:
    normalized = pair.strip().upper()
    if len(normalized) != 6:
        raise ValueError(f"FX pair must be a six-letter currency pair: {pair}")
    return normalized[:3], normalized[3:]


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


def _forex_contract(pair: str) -> Any:
    _ensure_event_loop()
    from ib_insync import Forex

    return Forex(pair.upper())
