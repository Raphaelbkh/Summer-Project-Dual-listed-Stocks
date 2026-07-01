"""Manual observe-only IBKR connection smoke test."""

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
from src.data.live.ibapi_client import IBAPIClient  # noqa: E402


SETTINGS_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    with SETTINGS_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def main() -> None:
    config_dict = load_config()
    connection_config = load_ibkr_connection_config(config_dict)
    port = resolve_ibkr_port(connection_config)

    ib = IBAPIClient()
    try:
        ib.connect(
            connection_config.host,
            port,
            clientId=connection_config.client_id_market_data,
            readonly=True,
        )
        print(f"host: {connection_config.host}")
        print(f"port: {port}")
        print(f"mode: {connection_config.mode}")
        print(f"connected: {ib.isConnected()}")
    finally:
        if ib.isConnected():
            ib.disconnect()


if __name__ == "__main__":
    main()
