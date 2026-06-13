"""Manual IBKR contract-detail search for user-provided symbols."""

from pathlib import Path
from typing import Any
import asyncio
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.live.ibkr_market_data import (  # noqa: E402
    load_ibkr_connection_config,
    resolve_ibkr_port,
)


SETTINGS_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    with SETTINGS_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def ensure_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def value(source: Any, name: str, default: Any = "") -> Any:
    return getattr(source, name, default)


def print_contract_detail(detail: Any) -> None:
    contract = detail.contract
    print(
        " | ".join(
            [
                f"conId={value(contract, 'conId')}",
                f"symbol={value(contract, 'symbol')}",
                f"localSymbol={value(contract, 'localSymbol')}",
                f"tradingClass={value(contract, 'tradingClass')}",
                f"secType={value(contract, 'secType')}",
                f"exchange={value(contract, 'exchange')}",
                f"primaryExchange={value(contract, 'primaryExchange')}",
                f"currency={value(contract, 'currency')}",
                f"marketName={value(detail, 'marketName')}",
                f"longName={value(detail, 'longName')}",
            ]
        )
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/search_ibkr_contracts.py SYMBOL [SYMBOL ...]")
        raise SystemExit(2)

    config_dict = load_config()
    connection_config = load_ibkr_connection_config(config_dict)
    port = resolve_ibkr_port(connection_config)

    ensure_event_loop()
    from ib_async import IB, Stock

    ib = IB()
    try:
        ib.connect(
            connection_config.host,
            port,
            clientId=connection_config.client_id_market_data + 10,
            readonly=True,
        )
        for symbol in sys.argv[1:]:
            print("")
            print(f"search_symbol: {symbol}")
            contract = Stock(symbol, "SMART", "")
            details = ib.reqContractDetails(contract)
            if not details:
                print("results: 0")
                continue
            for detail in details:
                print_contract_detail(detail)
    finally:
        if ib.isConnected():
            ib.disconnect()


if __name__ == "__main__":
    main()
