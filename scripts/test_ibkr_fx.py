"""Manual observe-only IBKR IDEALPRO FX quote smoke test."""

from pathlib import Path
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.live.ibkr_market_data import (  # noqa: E402
    load_ibkr_connection_config,
    resolve_ibkr_port,
)
from src.fx.ibkr_fx import IBKRFXProvider  # noqa: E402


CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def print_quote(provider: IBKRFXProvider, pair: str, optional: bool = False) -> None:
    try:
        contract = provider.qualify_fx_contract(pair)
        print(f"qualified_contract: {contract}")
        quote = provider.get_fx_quote(pair)
    except Exception as exc:
        if optional:
            print(f"pair: {pair}")
            print(f"optional_error: {exc}")
            return
        raise

    print(f"pair: {quote.pair}")
    print(f"bid: {quote.bid}")
    print(f"ask: {quote.ask}")
    print(f"last: {quote.last}")
    print(f"timestamp: {quote.timestamp.isoformat()}")
    print(f"is_valid: {quote.is_valid}")
    print(f"spread_pct: {quote.spread_pct}")
    if quote.bid is None or quote.ask is None or quote.bid <= 0 or quote.ask <= 0:
        print("warning: missing or non-positive IBKR FX bid/ask")


def main() -> None:
    config_dict = load_config()
    connection_config = load_ibkr_connection_config(config_dict)
    port = resolve_ibkr_port(connection_config)
    fx_config = config_dict["fx"]

    provider = IBKRFXProvider(
        host=connection_config.host,
        port=port,
        client_id=int(config_dict["ibkr"]["client_id_fx"]),
    )

    try:
        provider.connect()
        provider.ib.errorEvent += lambda *args: print(f"ibkr_error: {args}")
        provider.ib.reqMarketDataType(1)
        for pair in fx_config["required_pairs"]:
            print_quote(provider, pair)
        for pair in fx_config.get("optional_pairs", []):
            print_quote(provider, pair, optional=True)
    finally:
        if provider.is_connected():
            provider.disconnect()


if __name__ == "__main__":
    main()
