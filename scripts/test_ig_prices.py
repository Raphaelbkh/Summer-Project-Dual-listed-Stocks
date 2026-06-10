"""Manual observe-only IG prices endpoint smoke test."""

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
    parser = ArgumentParser(description="Fetch IG recent prices by epic.")
    parser.add_argument(
        "epics",
        nargs="+",
        help="IG epics, for example UD.D.TSLA.CASH.IP",
    )
    parser.add_argument("--resolution", default="MINUTE", help="IG price resolution.")
    parser.add_argument("--points", type=int, default=1, help="Number of price points.")
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

    print("connected: True")
    print(f"environment: {config_dict['ig']['environment']}")

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
            if "unauthorised.access.to.equity.exception" in str(exc):
                print(
                    "diagnosis: IG accepted the session but denied equity price "
                    "access for this account/environment. Check whether real-time "
                    "share data is enabled for the same IG account used by the API."
                )
            continue

        prices = payload.get("prices", [])
        allowance = payload.get("allowance", {})
        print(
            "allowance: "
            f"remaining={allowance.get('remainingAllowance')} "
            f"total={allowance.get('totalAllowance')} "
            f"reset_seconds={allowance.get('allowanceExpiry')}"
        )
        if not prices:
            print("prices: 0")
            continue

        for price in prices:
            close_price = price.get("closePrice", {})
            open_price = price.get("openPrice", {})
            print(
                " | ".join(
                    [
                        f"time_utc={price.get('snapshotTimeUTC')}",
                        f"close_bid={close_price.get('bid')}",
                        f"close_ask={close_price.get('ask')}",
                        f"close_last={close_price.get('last')}",
                        f"open_bid={open_price.get('bid')}",
                        f"open_ask={open_price.get('ask')}",
                        f"volume={price.get('lastTradedVolume')}",
                    ]
                )
            )


if __name__ == "__main__":
    main()
