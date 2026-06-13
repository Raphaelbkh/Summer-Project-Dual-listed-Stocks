"""Manual observe-only IBKR historical equity bars smoke test."""

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


SETTINGS_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    with SETTINGS_PATH.open("r", encoding="utf-8") as config_file:
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


def print_bars(label: str, symbol: str, exchange: str, currency: str, bars: pd.DataFrame) -> None:
    print(f"leg: {label}")
    print(f"symbol: {symbol}")
    print(f"exchange: {exchange}")
    print(f"currency: {currency}")
    print(f"bars: {len(bars)}")
    if bars.empty:
        print("warning: no historical bars returned")
        return
    for _, row in bars.tail(5).iterrows():
        print(
            " | ".join(
                [
                    f"date={row['date']}",
                    f"open={row['open']}",
                    f"high={row['high']}",
                    f"low={row['low']}",
                    f"close={row['close']}",
                    f"volume={row['volume']}",
                ]
            )
        )


def print_leg_bars(
    provider: IBKREquityMarketDataProvider,
    label: str,
    symbol: str,
    exchange: str,
    currency: str,
) -> None:
    try:
        bars = provider.get_historical_bars(
            symbol,
            exchange,
            currency,
            duration_str="1 W",
            bar_size_setting="1 day",
            what_to_show="TRADES",
            use_rth=True,
        )
    except Exception as exc:
        print(f"leg: {label}")
        print(f"symbol: {symbol}")
        print(f"exchange: {exchange}")
        print(f"currency: {currency}")
        print(f"error: {exc}")
        return

    print_bars(label, symbol, exchange, currency, bars)


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
            print_leg_bars(
                provider,
                "long",
                row["long_symbol"],
                row["long_exchange"],
                row["long_currency"],
            )
            print_leg_bars(
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
