"""Manual observe-only IG live-account prices smoke test."""

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
    ig_base_url_for_profile,
    load_ig_credentials_for_profile_from_env,
    load_ig_session_settings_for_profile_from_env,
)


CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"
PROFILE_NAME = "ig_live_data"


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
    parser = ArgumentParser(description="Fetch IG live-account prices by epic.")
    parser.add_argument("epics", nargs="+", help="IG epics to fetch prices for.")
    parser.add_argument("--resolution", default="MINUTE", help="IG price resolution.")
    parser.add_argument("--points", type=int, default=1, help="Number of price points.")
    return parser.parse_args()


def validate_live_data_profile(config_dict: dict) -> None:
    profile = config_dict[PROFILE_NAME]
    if profile.get("environment") != "live":
        raise ValueError("ig_live_data.environment must be live.")
    if profile.get("purpose") != "market_data_only":
        raise ValueError("ig_live_data.purpose must be market_data_only.")
    if profile.get("observe_only") is not True:
        raise ValueError("ig_live_data.observe_only must be true.")


def main() -> None:
    args = parse_args()
    load_dotenv_if_present()
    config_dict = load_config()
    validate_live_data_profile(config_dict)

    credentials = load_ig_credentials_for_profile_from_env(config_dict, PROFILE_NAME)
    session_settings = load_ig_session_settings_for_profile_from_env(
        config_dict,
        PROFILE_NAME,
    )
    client = IGAPIClient(ig_base_url_for_profile(config_dict, PROFILE_NAME), credentials)

    try:
        session = client.login()
        if session_settings.account_id:
            session = client.switch_account(session_settings.account_id)
    except requests.HTTPError as exc:
        print("connected: False")
        print("environment: live")
        print(f"error: {exc}")
        raise SystemExit(1) from exc

    print("connected: True")
    print("environment: live")
    print("purpose: market_data_only")
    print(f"current_account_id: {session.get('currentAccountId')}")

    for epic in args.epics:
        print("")
        print(f"epic: {epic}")
        try:
            payload = client.get_prices(
                epic,
                resolution=args.resolution,
                num_points=args.points,
            )
        except requests.HTTPError as exc:
            print(f"error: {exc}")
            continue

        prices = payload.get("prices", [])
        if not prices:
            print("prices: 0")
            continue

        for price in prices:
            close_price = price.get("closePrice", {})
            print(
                " | ".join(
                    [
                        f"time_utc={price.get('snapshotTimeUTC')}",
                        f"close_bid={close_price.get('bid')}",
                        f"close_ask={close_price.get('ask')}",
                        f"close_last={close_price.get('last')}",
                        f"volume={price.get('lastTradedVolume')}",
                    ]
                )
            )


if __name__ == "__main__":
    main()
