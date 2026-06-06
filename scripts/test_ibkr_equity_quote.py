"""Manual observe-only IBKR equity quote smoke test for active pairs."""

from pathlib import Path
import sys

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.live.ibkr_market_data import (  # noqa: E402
    IBKREquityMarketDataProvider,
    load_ibkr_connection_config,
    resolve_ibkr_port,
)
from src.data.mappings.listing_master import get_active_pairs, validate_resolved_pairs  # noqa: E402


CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def load_active_pairs(config_dict: dict) -> pd.DataFrame:
    universe_config = config_dict["universe_selection"]
    live_test_pairs_path = PROJECT_ROOT / universe_config["live_test_pairs_path"]
    resolved_pairs_path = PROJECT_ROOT / universe_config["resolved_pairs_path"]

    live_test_pairs = pd.read_csv(live_test_pairs_path, dtype=str, keep_default_na=False)
    validate_resolved_pairs(live_test_pairs)
    active_live_test_pairs = get_active_pairs(live_test_pairs)
    if not active_live_test_pairs.empty:
        return active_live_test_pairs

    resolved_pairs = pd.read_csv(resolved_pairs_path, dtype=str, keep_default_na=False)
    validate_resolved_pairs(resolved_pairs)
    return get_active_pairs(resolved_pairs)


def print_quote(label: str, quote) -> None:
    print(f"leg: {label}")
    print(f"symbol: {quote.symbol}")
    print(f"exchange: {quote.exchange}")
    print(f"currency: {quote.currency}")
    print(f"bid: {quote.bid}")
    print(f"ask: {quote.ask}")
    print(f"bid_size: {quote.bid_size}")
    print(f"ask_size: {quote.ask_size}")
    print(f"last: {quote.last}")
    print(f"timestamp: {quote.timestamp.isoformat()}")
    print(f"is_valid: {quote.is_valid}")
    print(f"spread_pct: {quote.spread_pct}")
    if quote.bid is None or quote.ask is None:
        print("warning: missing bid/ask")


def print_leg_quote(
    provider: IBKREquityMarketDataProvider,
    label: str,
    symbol: str,
    exchange: str,
    currency: str,
) -> None:
    try:
        quote = provider.get_equity_quote(symbol, exchange, currency)
    except Exception as exc:
        print(f"leg: {label}")
        print(f"symbol: {symbol}")
        print(f"exchange: {exchange}")
        print(f"currency: {currency}")
        print(f"error: {exc}")
        return

    print_quote(label, quote)


def main() -> None:
    config_dict = load_config()
    connection_config = load_ibkr_connection_config(config_dict)
    port = resolve_ibkr_port(connection_config)
    active_pairs = load_active_pairs(config_dict)

    if active_pairs.empty:
        print("No active pairs found. Manually set active=true before running.")
        return

    provider = IBKREquityMarketDataProvider(
        host=connection_config.host,
        port=port,
        client_id=connection_config.client_id_market_data,
    )

    try:
        provider.connect()
        for _, row in active_pairs.iterrows():
            print(f"pair_id: {row['pair_id']}")
            print_leg_quote(
                provider,
                "long",
                row["long_symbol"],
                row["long_exchange"],
                row["long_currency"],
            )
            print_leg_quote(
                provider,
                "short",
                row["short_symbol"],
                row["short_exchange"],
                row["short_currency"],
            )
    finally:
        if provider.is_connected():
            provider.disconnect()


if __name__ == "__main__":
    main()
