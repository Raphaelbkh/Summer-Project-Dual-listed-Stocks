"""Manual observe-only IBKR crypto quote smoke test."""

from pathlib import Path
from typing import Any
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.live.ibkr_market_data import (  # noqa: E402
    load_ibkr_connection_config,
    resolve_ibkr_port,
)
from src.data.live.ibapi_client import IBAPIClient, crypto_contract  # noqa: E402
from src.data.live.quote_models import EquityQuote  # noqa: E402
from src.utils.time_utils import utc_now  # noqa: E402


SETTINGS_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    with SETTINGS_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def ticker_time(ticker: Any):
    value = getattr(ticker, "time", None) or getattr(ticker, "rtTime", None)
    return value if value is not None else utc_now()


def print_crypto_quote(ib, symbol: str, exchange: str, currency: str) -> None:
    contract = crypto_contract(symbol, exchange, currency)
    qualified_contracts = ib.qualifyContracts(contract)
    if not qualified_contracts:
        print(f"symbol: {symbol}")
        print("error: contract qualification failed")
        return

    qualified_contract = qualified_contracts[0]
    print(f"qualified_contract: {qualified_contract}")
    ticker = ib.reqMktData(
        qualified_contract,
        genericTickList="",
        snapshot=True,
        regulatorySnapshot=False,
    )

    elapsed = 0.0
    while elapsed < 8.0:
        bid = optional_float(getattr(ticker, "bid", None))
        ask = optional_float(getattr(ticker, "ask", None))
        last = optional_float(getattr(ticker, "last", None))
        if (bid is not None and ask is not None) or last is not None:
            break
        ib.sleep(0.25)
        elapsed += 0.25

    quote = EquityQuote(
        symbol=symbol,
        exchange=exchange,
        currency=currency,
        bid=optional_float(getattr(ticker, "bid", None)),
        ask=optional_float(getattr(ticker, "ask", None)),
        bid_size=optional_float(getattr(ticker, "bidSize", None)),
        ask_size=optional_float(getattr(ticker, "askSize", None)),
        last=optional_float(getattr(ticker, "last", None)),
        timestamp=ticker_time(ticker),
        source="IBKR_CRYPTO",
        contract_id=getattr(qualified_contract, "conId", None),
    )

    print(f"symbol: {quote.symbol}")
    print(f"exchange: {quote.exchange}")
    print(f"currency: {quote.currency}")
    print(f"bid: {quote.bid}")
    print(f"ask: {quote.ask}")
    print(f"last: {quote.last}")
    print(f"timestamp: {quote.timestamp.isoformat()}")
    print(f"is_valid: {quote.is_valid}")
    print(f"spread_pct: {quote.spread_pct}")
    if not quote.is_valid:
        print("warning: missing or non-positive IBKR crypto bid/ask")


def main() -> None:
    config_dict = load_config()
    connection_config = load_ibkr_connection_config(config_dict)
    port = resolve_ibkr_port(connection_config)

    ib = IBAPIClient()
    try:
        ib.connect(
            connection_config.host,
            port,
            clientId=int(config_dict["ibkr"]["client_id_market_data"]),
            readonly=True,
        )
        ib.errorEvent += lambda *args: print(f"ibkr_error: {args}")
        ib.reqMarketDataType(1)
        print_crypto_quote(ib, "BTC", "PAXOS", "USD")
        print_crypto_quote(ib, "ETH", "PAXOS", "USD")
    finally:
        if ib.isConnected():
            ib.disconnect()


if __name__ == "__main__":
    main()
