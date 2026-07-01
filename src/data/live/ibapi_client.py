"""Synchronous, read-only adapter around the official IBKR TWS API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from types import SimpleNamespace
from typing import Any, Callable
import time


DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0


class EventHook:
    """Small event hook retained for existing diagnostic script compatibility."""

    def __init__(self) -> None:
        self._handlers: list[Callable[..., None]] = []

    def __iadd__(self, handler: Callable[..., None]):
        self._handlers.append(handler)
        return self

    def emit(self, *args: Any) -> None:
        for handler in tuple(self._handlers):
            handler(*args)


@dataclass
class _RequestState:
    event: Event
    result: Any
    auto_remove: bool = False


class IBAPIClient:
    """Blocking facade over the official callback-based ``ibapi`` client."""

    def __init__(self, request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS) -> None:
        try:
            from ibapi.client import EClient
            from ibapi.wrapper import EWrapper
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "The official IBKR TWS API package 'ibapi' is not installed in this "
                "Python environment. Install it into the active virtual environment "
                "from the downloaded TWS API source/pythonclient directory."
            ) from exc

        owner = self

        class _IBAPIApp(EWrapper, EClient):
            def __init__(self) -> None:
                EWrapper.__init__(self)
                EClient.__init__(self, wrapper=self)

            def nextValidId(self, orderId: int) -> None:
                owner._on_next_valid_id(orderId)

            def error(self, reqId: int, *args: Any) -> None:
                error_code, error_string, advanced_reject = _parse_error_args(args)
                owner._on_error(reqId, error_code, error_string, advanced_reject)

            def contractDetails(self, reqId: int, contractDetails: Any) -> None:
                owner._on_contract_details(reqId, contractDetails)

            def contractDetailsEnd(self, reqId: int) -> None:
                owner._finish_request(reqId)

            def tickPrice(self, reqId: int, tickType: int, price: float, attrib: Any) -> None:
                owner._on_tick_price(reqId, tickType, price)

            def tickSize(self, reqId: int, tickType: int, size: Any) -> None:
                owner._on_tick_size(reqId, tickType, size)

            def tickSnapshotEnd(self, reqId: int) -> None:
                owner._finish_request(reqId)

            def historicalData(self, reqId: int, bar: Any) -> None:
                owner._on_historical_bar(reqId, bar)

            def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:
                owner._finish_request(reqId)

            def connectionClosed(self) -> None:
                owner._connected.clear()

        self._app = _IBAPIApp()
        self._request_timeout_seconds = request_timeout_seconds
        self._connected = Event()
        self._request_lock = Lock()
        self._requests: dict[int, _RequestState] = {}
        self._request_errors: dict[int, tuple[int, str]] = {}
        self._next_request_id = 1
        self._network_thread: Thread | None = None
        self.errorEvent = EventHook()

    def connect(
        self,
        host: str,
        port: int,
        clientId: int,
        readonly: bool = True,
    ) -> None:
        """Connect in data-only mode and wait for the API handshake."""
        if readonly is not True:
            raise ValueError("IBAPIClient only supports readonly=True connections.")
        self._app.connect(host, port, clientId)
        self._network_thread = Thread(
            target=self._app.run,
            name=f"ibapi-{clientId}",
            daemon=True,
        )
        self._network_thread.start()
        if not self._connected.wait(self._request_timeout_seconds):
            self.disconnect()
            raise TimeoutError("Timed out waiting for the IBKR API connection handshake.")

    def disconnect(self) -> None:
        self._app.disconnect()
        self._connected.clear()
        thread = self._network_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def isConnected(self) -> bool:
        return self._connected.is_set() and bool(self._app.isConnected())

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def qualifyContracts(self, contract: Any) -> list[Any]:
        return [
            detail.contract
            for detail in self.reqContractDetails(contract)
            if getattr(detail, "contract", None) is not None
        ]

    def reqContractDetails(self, contract: Any) -> list[Any]:
        req_id, state = self._new_request([])
        self._app.reqContractDetails(req_id, contract)
        self._wait_for_request(req_id, state, "contract details")
        return list(state.result)

    def reqMktData(
        self,
        contract: Any,
        genericTickList: str,
        snapshot: bool,
        regulatorySnapshot: bool,
    ) -> Any:
        ticker = SimpleNamespace(
            bid=None,
            ask=None,
            bidSize=None,
            askSize=None,
            last=None,
            time=None,
        )
        req_id, _ = self._new_request(ticker, auto_remove=True)
        self._app.reqMktData(
            req_id,
            contract,
            genericTickList,
            snapshot,
            regulatorySnapshot,
            [],
        )
        return ticker

    def reqHistoricalData(
        self,
        contract: Any,
        endDateTime: str,
        durationStr: str,
        barSizeSetting: str,
        whatToShow: str,
        useRTH: bool,
        formatDate: int,
    ) -> list[Any]:
        req_id, state = self._new_request([])
        self._app.reqHistoricalData(
            req_id,
            contract,
            endDateTime,
            durationStr,
            barSizeSetting,
            whatToShow,
            int(useRTH),
            formatDate,
            False,
            [],
        )
        self._wait_for_request(req_id, state, "historical data")
        return list(state.result)

    def reqMarketDataType(self, market_data_type: int) -> None:
        self._app.reqMarketDataType(market_data_type)

    def _new_request(
        self,
        result: Any,
        auto_remove: bool = False,
    ) -> tuple[int, _RequestState]:
        with self._request_lock:
            req_id = self._next_request_id
            self._next_request_id += 1
            state = _RequestState(
                event=Event(),
                result=result,
                auto_remove=auto_remove,
            )
            self._requests[req_id] = state
        return req_id, state

    def _wait_for_request(
        self,
        req_id: int,
        state: _RequestState,
        description: str,
    ) -> None:
        if not state.event.wait(self._request_timeout_seconds):
            self._requests.pop(req_id, None)
            raise TimeoutError(f"Timed out waiting for IBKR {description}.")
        error = self._request_errors.pop(req_id, None)
        self._requests.pop(req_id, None)
        if error is not None:
            error_code, error_string = error
            raise RuntimeError(f"IBKR error {error_code}: {error_string}")

    def _finish_request(self, req_id: int) -> None:
        state = self._requests.get(req_id)
        if state is not None:
            state.event.set()
            if state.auto_remove:
                self._requests.pop(req_id, None)
                self._request_errors.pop(req_id, None)

    def _on_next_valid_id(self, order_id: int) -> None:
        with self._request_lock:
            self._next_request_id = max(self._next_request_id, order_id)
        self._connected.set()

    def _on_error(
        self,
        req_id: int,
        error_code: int,
        error_string: str,
        advanced_order_reject_json: str,
    ) -> None:
        self.errorEvent.emit(req_id, error_code, error_string, None)
        if req_id < 0 or error_code in {2104, 2106, 2107, 2108, 2158}:
            return
        self._request_errors[req_id] = (error_code, error_string)
        self._finish_request(req_id)

    def _on_contract_details(self, req_id: int, contract_details: Any) -> None:
        state = self._requests.get(req_id)
        if state is not None:
            state.result.append(contract_details)

    def _on_tick_price(self, req_id: int, tick_type: int, price: float) -> None:
        state = self._requests.get(req_id)
        if state is None:
            return
        field = {1: "bid", 2: "ask", 4: "last"}.get(tick_type)
        if field is not None:
            setattr(state.result, field, price)
            state.result.time = datetime.now(timezone.utc)

    def _on_tick_size(self, req_id: int, tick_type: int, size: Any) -> None:
        state = self._requests.get(req_id)
        if state is None:
            return
        field = {0: "bidSize", 3: "askSize"}.get(tick_type)
        if field is not None:
            setattr(state.result, field, float(size))
            state.result.time = datetime.now(timezone.utc)

    def _on_historical_bar(self, req_id: int, bar: Any) -> None:
        state = self._requests.get(req_id)
        if state is not None:
            state.result.append(bar)


def stock_contract(
    symbol: str,
    exchange: str,
    currency: str,
    primary_exchange: str | None = None,
) -> Any:
    """Build an official ``ibapi.contract.Contract`` for an equity."""
    contract = _contract()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = exchange
    contract.currency = currency
    if primary_exchange:
        contract.primaryExchange = primary_exchange
    return contract


def forex_contract(pair: str) -> Any:
    """Build an official IDEALPRO cash contract."""
    normalized = pair.strip().upper()
    if len(normalized) != 6:
        raise ValueError(f"FX pair must be a six-letter currency pair: {pair}")
    contract = _contract()
    contract.symbol = normalized[:3]
    contract.secType = "CASH"
    contract.exchange = "IDEALPRO"
    contract.currency = normalized[3:]
    return contract


def crypto_contract(symbol: str, exchange: str, currency: str) -> Any:
    """Build an official crypto contract."""
    contract = _contract()
    contract.symbol = symbol
    contract.secType = "CRYPTO"
    contract.exchange = exchange
    contract.currency = currency
    return contract


def _contract() -> Any:
    try:
        from ibapi.contract import Contract
    except ModuleNotFoundError:
        return SimpleNamespace(
            symbol="",
            secType="",
            exchange="",
            currency="",
            primaryExchange="",
            conId=0,
            localSymbol="",
            tradingClass="",
        )
    return Contract()


def _parse_error_args(args: tuple[Any, ...]) -> tuple[int, str, str]:
    """Support official API error callbacks with and without an error timestamp."""
    if len(args) >= 3 and isinstance(args[0], int) and isinstance(args[1], int):
        _, error_code, error_string, *remaining = args
    elif len(args) >= 2:
        error_code, error_string, *remaining = args
    else:
        return -1, "Unknown IBKR API error", ""
    advanced_reject = str(remaining[0]) if remaining else ""
    return int(error_code), str(error_string), advanced_reject
