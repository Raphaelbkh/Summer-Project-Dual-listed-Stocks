"""Manual observe-only IG demo API connection smoke test."""

from pathlib import Path
import os
import sys

import yaml
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.live.ig_api import (  # noqa: E402
    IGAPIClient,
    ig_base_url,
    load_ig_credentials_from_env,
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


def main() -> None:
    load_dotenv_if_present()
    config_dict = load_config()
    credentials = load_ig_credentials_from_env(config_dict)
    client = IGAPIClient(ig_base_url(config_dict), credentials)
    try:
        session = client.login()
        accounts = client.get_accounts()
    except requests.HTTPError as exc:
        print("connected: False")
        print(f"environment: {config_dict['ig']['environment']}")
        print(f"error: {exc}")
        raise SystemExit(1) from exc

    print(f"environment: {config_dict['ig']['environment']}")
    print(f"current_account_id: {session.get('currentAccountId')}")
    print(f"accounts_count: {len(accounts.get('accounts', []))}")
    print("connected: True")


if __name__ == "__main__":
    main()
