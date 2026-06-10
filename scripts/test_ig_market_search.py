"""Manual observe-only IG market search and quote smoke test."""

from argparse import ArgumentParser, Namespace
from pathlib import Path
import os
import sys

import requests
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.live.ig_api import (  # noqa: E402
    IGAPIClient,
    IGMarketDataProvider,
    ig_base_url,
    load_ig_credentials_from_env,
    load_ig_session_settings_from_env,
)


CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def load_dotenv_if_present() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def parse_args() -> Namespace:
    parser = ArgumentParser(description="Search IG demo markets by term.")
    parser.add_argument(
        "terms",
        nargs="*",
        default=["AAPL", "EUR/USD"],
        help="Search terms, for example AAPL EUR/USD ERIC",
    )
    parser.add_argument("--limit", type=int, default=5, help="Rows to print per term.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv_if_present()
    config_dict = load_config()
    credentials = load_ig_credentials_from_env(config_dict)
    session_settings = load_ig_session_settings_from_env(config_dict)
    client = IGAPIClient(ig_base_url(config_dict), credentials)

    try:
        client.login()
        if session_settings.account_id:
            client.switch_account(session_settings.account_id)
    except requests.HTTPError as exc:
        print("connected: False")
        print(f"environment: {config_dict['ig']['environment']}")
        print(f"error: {exc}")
        raise SystemExit(1) from exc

    provider = IGMarketDataProvider(client)
    print(f"connected: True")
    print(f"environment: {config_dict['ig']['environment']}")

    for term in args.terms:
        print("")
        print(f"search_term: {term}")
        try:
            results = provider.search_markets(term)
        except requests.HTTPError as exc:
            print(f"error: {exc}")
            continue

        if not results:
            print("results: 0")
            continue

        for result in results[: args.limit]:
            detail_bid = result.bid
            detail_offer = result.offer
            detail_status = result.market_status
            detail_currency = result.currency
            try:
                details = client.get_market_details(result.epic)
                snapshot = details.get("snapshot", {})
                instrument = details.get("instrument", {})
                detail_bid = snapshot.get("bid", detail_bid)
                detail_offer = snapshot.get("offer", detail_offer)
                detail_status = snapshot.get("marketStatus", detail_status)
                detail_currency = _currency_from_instrument(instrument) or detail_currency
            except requests.HTTPError as exc:
                print(f"details_warning: epic={result.epic} error={exc}")

            print(
                " | ".join(
                    [
                        f"epic={result.epic}",
                        f"name={result.instrument_name}",
                        f"type={result.instrument_type}",
                        f"expiry={result.expiry}",
                        f"status={detail_status}",
                        f"bid={detail_bid}",
                        f"offer={detail_offer}",
                        f"currency={detail_currency}",
                    ]
                )
            )


def _currency_from_instrument(instrument: dict) -> str | None:
    currencies = instrument.get("currencies")
    if isinstance(currencies, list) and currencies:
        first_currency = currencies[0]
        if isinstance(first_currency, dict):
            return first_currency.get("code")
    currency = instrument.get("currency")
    if isinstance(currency, str):
        return currency
    return None


if __name__ == "__main__":
    main()
